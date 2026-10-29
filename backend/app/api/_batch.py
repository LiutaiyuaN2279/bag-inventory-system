"""批量操作统一执行器。

设计要点：
1. **逐条独立事务**：每条记录处理成功后立即 commit，失败则 rollback 后继续下一条。
   这样一条失败不会回滚掉前面已成功的记录，也不会让后续记录全部连带失败。
2. **部分成功可接受**：返回结构固定为
   {total, success_count, fail_count, success_ids, failed:[{id, reason}]}
   前端据此提示「成功 N 条，失败 M 条」并列出失败原因。
3. **不做全量校验**：批量场景下逐条校验才有意义（否则一条非法就全军覆没），
   调用方只需把单条业务逻辑写成 handler。
"""
from typing import Callable

from sqlalchemy.orm import Session

from app.core.exceptions import BizException, PermissionException
from app.crud.crud_auth import (
    get_user_permission_overrides,
    get_user_permissions,
    get_user_roles,
)
from app.models.rbac import User
from app.utils.response import success

# 单次批量操作上限：防止前端误传全表 id 导致长事务/长时间占用连接
MAX_BATCH = 500


def ensure_perm(db: Session, user: User, perm_code: str) -> None:
    """批量接口内按具体动作二次校验权限。

    批量接口一个端点承担多个动作（启用/停用/删除…），而每个动作对应的权限码不同，
    不能只用路由级单一依赖一刀切；这里按动作逐个校验，判定顺序与 require_permissions 保持一致：
    用户级禁止 > admin 放行 > 权限码命中。
    """
    _grants, denies = get_user_permission_overrides(db, user)
    if perm_code in denies:
        raise PermissionException("该权限已被单独禁用，请联系系统管理员")
    if "admin" in get_user_roles(db, user):
        return
    if perm_code not in get_user_permissions(db, user):
        raise PermissionException()


def run_batch_guarded(
    db: Session,
    user: User,
    payload,
    action_perms: dict[str, str],
    handler: Callable[[Session, int, str], None],
) -> object:
    """按动作校验权限后执行批量操作。

    批量接口一个端点承担多个动作（启用/停用/删除…），各动作权限码不同，
    无法用单一路由依赖覆盖；这里先确认动作合法、再校验该动作所需权限，最后交给 run_batch。

    action_perms: {动作名: 所需权限码}
    handler:      (db, obj_id, action) -> None，只做「取对象 → 校验 → 改状态」，不 commit
    """
    action = (payload.action or "").strip()
    if action not in action_perms:
        raise BizException(f"不支持的批量动作：{action or '(空)'}")
    ensure_perm(db, user, action_perms[action])
    return run_batch(db, payload.ids, lambda i: handler(db, i, action))


def run_batch(db: Session, ids: list[int], handler: Callable[[int], None]) -> object:
    """逐条执行 handler(obj_id)，返回统一的成功/失败明细。

    handler 内部只需做「取对象 → 校验 → 改状态」，**不需要自己 commit**；
    commit 由本函数在每条成功后统一负责，保证单条失败不影响其它记录。
    """
    if not ids:
        raise BizException("请先勾选要操作的数据")
    # 去重但保持前端传入顺序，避免重复提交导致同一张单被处理两次
    seen: set[int] = set()
    uniq: list[int] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            uniq.append(i)
    if len(uniq) > MAX_BATCH:
        raise BizException(f"单次最多批量操作 {MAX_BATCH} 条，当前已选 {len(uniq)} 条")

    ok: list[int] = []
    failed: list[dict] = []
    for obj_id in uniq:
        try:
            handler(obj_id)
            db.commit()
            ok.append(obj_id)
        except BizException as e:
            db.rollback()
            failed.append({"id": obj_id, "reason": e.message})
        except Exception as e:  # noqa: BLE001 - 单条异常不应中断整批
            db.rollback()
            failed.append({"id": obj_id, "reason": str(e) or e.__class__.__name__})

    return success(
        {
            "total": len(uniq),
            "success_count": len(ok),
            "fail_count": len(failed),
            "success_ids": ok,
            "failed": failed,
        },
        message=_summary(len(ok), len(failed)),
    )


def _summary(ok: int, fail: int) -> str:
    if fail == 0:
        return f"已成功处理 {ok} 条"
    if ok == 0:
        return f"{fail} 条均处理失败，请查看失败原因"
    return f"成功 {ok} 条，失败 {fail} 条"
