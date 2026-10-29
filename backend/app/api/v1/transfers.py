"""仓库调拨：列表 / 详情 / 新建 / 编辑 / 审核（执行调拨，出入库各一次） / 作废（已执行则反向回滚）。
调拨 = 从调出仓库出库 + 向调入仓库入库，统一走 stock_service 的库存流水，保证台账可追溯、可逆。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api._batch import run_batch_guarded
from app.api._helpers import load_maps, material_meta
from app.api.deps import get_current_user, require_permissions
from app.core.database import get_db
from app.core.exceptions import BizException
from app.crud.crud_base import apply_ordering
from app.models.inventory import Inventory, TransferItem, TransferOrder
from app.models.master_data import Location, MaterialColorBatch, Warehouse
from app.models.rbac import User
from app.schemas.batch import BatchIn
from app.schemas.inventory import TransferCreate, TransferUpdate
from app.services.stock_service import post_inbound, post_outbound
from app.utils.numbering import gen_no
from app.utils.response import page_result, success

router = APIRouter(prefix="/transfers", tags=["仓库调拨"])

# 出入库流水标记
TXN_OUT = "调拨出库"          # 调出仓库出库（作废时用于调入仓库反冲出库）
TXN_IN = "调拨入库"           # 调入仓库入库（作废时用于调出仓库反冲入库）
TXN_REF = "仓库调拨"          # 流水来源单据类型


# ---------------- 内部工具 ----------------
def _to_float(v):
    """宽松转数值：空值/非法值按 0 处理。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _s(v) -> str:
    """去空白并限制长度，避免超长写库失败。"""
    return str(v or "").strip()[:255]


def _check_warehouse(db, wid, label: str) -> int:
    """校验仓库存在，返回仓库 id。"""
    try:
        wid = int(wid)
    except (TypeError, ValueError):
        raise BizException(f"请选择{label}")
    if not db.get(Warehouse, wid):
        raise BizException(f"{label}不存在")
    return wid


def _norm_items(raw_items) -> list[dict]:
    """规范化明细：物料必填、数量必须大于 0（逐行保留，不做同维度合并，便于对账）。"""
    items = []
    for it in raw_items or []:
        material_id = it.get("material_id")
        if not material_id:
            raise BizException("明细中存在未选择物料的记录")
        qty = _to_float(it.get("qty"))
        if qty <= 0:
            raise BizException("明细数量必须大于 0")
        items.append({
            "material_id": material_id,
            "qty": qty,
            "unit": _s(it.get("unit")) or "个",
            "color_batch_id": it.get("color_batch_id") or None,
            "from_location_id": it.get("from_location_id") or None,
            "to_location_id": it.get("to_location_id") or None,
            "remark": _s(it.get("remark")),
        })
    if not items:
        raise BizException("请至少添加一条调拨明细")
    return items


def _batch_map(db):
    """{色号缸号 id: "色号/缸号"}，用于明细展示。"""
    return {b.id: f"{b.color_no or ''}/{b.vat_no or ''}" for b in db.query(MaterialColorBatch).all()}


def _location_map(db):
    """{库位 id: 库位名称}。"""
    return {l.id: (l.location_name or l.location_code or "") for l in db.query(Location).all()}


def _get_inventory(db, material_id, warehouse_id, location_id, color_batch_id):
    """按 物料+仓库+库位+缸号批次 定位台账（与 stock_service._get_inventory 口径一致）。"""
    q = db.query(Inventory).filter(
        Inventory.material_id == material_id,
        Inventory.warehouse_id == warehouse_id,
        Inventory.location_id.is_(None) if location_id is None else Inventory.location_id == location_id,
        Inventory.color_batch_id.is_(None) if color_batch_id is None else Inventory.color_batch_id == color_batch_id,
    )
    return q.first()


def _warehouse_stock(db, material_id, warehouse_id, location_id, color_batch_id) -> float:
    """指定仓库+库位+批次下的可用库存（无台账记录视为 0）。"""
    inv = _get_inventory(db, material_id, warehouse_id, location_id, color_batch_id)
    return float(inv.qty or 0) if inv else 0.0


def _short_msg(material_name, need, avail) -> str:
    return f"物料 {material_name} 库存不足，当前可用 {avail}，本次需调出 {need}"


def _row_dict(r, whs):
    return {
        "id": r.id, "transfer_no": r.transfer_no,
        "from_warehouse_id": r.from_warehouse_id, "from_warehouse_name": whs.get(r.from_warehouse_id, ""),
        "to_warehouse_id": r.to_warehouse_id, "to_warehouse_name": whs.get(r.to_warehouse_id, ""),
        "status": r.status, "executed": bool(r.executed), "operator": r.operator, "remark": r.remark,
        "created_at": str(r.created_at)[:19] if r.created_at else "",
        "updated_at": str(r.updated_at)[:19] if r.updated_at else "",
        "approve_time": str(r.approve_time)[:19] if r.approve_time else "",
        "void_time": str(r.void_time)[:19] if r.void_time else "",
    }


# ---------------- 单条业务核心（单条端点与批量端点共用） ----------------
def _do_approve(db: Session, tid: int, operator: str) -> None:
    """审核并执行一张调拨单：先对全部明细整体校验库存，再逐条「调出仓库出库 → 调入仓库入库」。
    任一明细库存不足或中途异常即整单回滚，单据状态与库存均保持原样。
    一张单 = 一个事务（不 commit，由调用方统一提交）。"""
    order = db.get(TransferOrder, tid)
    if not order:
        raise BizException("调拨单不存在")
    if order.status != "草稿":
        raise BizException("仅草稿可审核")
    if order.from_warehouse_id == order.to_warehouse_id:
        raise BizException("调出仓库与调入仓库不能相同")
    items = db.query(TransferItem).filter(TransferItem.transfer_id == tid).all()
    if not items:
        raise BizException("调拨单没有明细，无法审核")
    mats, _, _ = load_maps(db)
    # 先整体校验，避免前几行已扣减后才发现后续明细库存不足
    for it in items:
        if _to_float(it.qty) <= 0:
            raise BizException("明细数量必须大于 0")
        avail = _warehouse_stock(db, it.material_id, order.from_warehouse_id, it.from_location_id, it.color_batch_id)
        if avail < it.qty:
            raise BizException(_short_msg(mats.get(it.material_id, it.material_id), it.qty, avail))
    try:
        for it in items:
            post_outbound(db, material_id=it.material_id, warehouse_id=order.from_warehouse_id,
                          location_id=it.from_location_id, color_batch_id=it.color_batch_id,
                          qty=it.qty, txn_type=TXN_OUT, ref_type=TXN_REF,
                          ref_id=order.id, operator=operator)
            post_inbound(db, material_id=it.material_id, warehouse_id=order.to_warehouse_id,
                         location_id=it.to_location_id, color_batch_id=it.color_batch_id,
                         qty=it.qty, txn_type=TXN_IN, ref_type=TXN_REF,
                         ref_id=order.id, operator=operator)
        order.status = "已审核"
        order.executed = True
        order.approve_time = datetime.now()
    except Exception:
        # stock_service._move 是先改内存对象再判负，异常时 qty 已被就地修改：
        # rollback 回退事务，expire_all 让会话中已被改脏的对象立即失效，杜绝脏读与脏写回库。
        db.rollback()
        db.expire_all()
        raise


def _do_void(db: Session, tid: int, operator: str) -> bool:
    """作废一张调拨单：仅草稿或已审核可作废。
    已执行过库存动作的先反向回滚——调入仓库出库、调出仓库入库，保证台账可逆。
    返回是否执行了库存反冲（供调用方拼提示语）；一张单 = 一个事务（不 commit）。"""
    order = db.get(TransferOrder, tid)
    if not order:
        raise BizException("调拨单不存在")
    if order.status == "已作废":
        raise BizException("单据已作废")
    if order.status not in ("草稿", "已审核"):
        raise BizException("仅草稿或已审核单据可作废")
    items = db.query(TransferItem).filter(TransferItem.transfer_id == tid).all()
    mats, _, _ = load_maps(db)
    if order.executed:
        # 先整体校验调入仓库是否还有足够库存可供反冲，不足则整单拒绝，不动任何库存
        for it in items:
            avail = _warehouse_stock(db, it.material_id, order.to_warehouse_id, it.to_location_id, it.color_batch_id)
            if avail < it.qty:
                raise BizException(
                    f"调入仓库的物料 {mats.get(it.material_id, it.material_id)} 库存不足，当前可用 {avail}，"
                    f"无法反冲本次调拨数量 {it.qty}，请先调整后再作废")
        try:
            for it in items:
                # 反向：调入仓库出库
                post_outbound(db, material_id=it.material_id, warehouse_id=order.to_warehouse_id,
                              location_id=it.to_location_id, color_batch_id=it.color_batch_id,
                              qty=it.qty, txn_type=TXN_OUT, ref_type=TXN_REF,
                              ref_id=order.id, operator=operator)
                # 反向：调出仓库入库
                post_inbound(db, material_id=it.material_id, warehouse_id=order.from_warehouse_id,
                             location_id=it.from_location_id, color_batch_id=it.color_batch_id,
                             qty=it.qty, txn_type=TXN_IN, ref_type=TXN_REF,
                             ref_id=order.id, operator=operator)
            order.executed = False
            order.status = "已作废"
            order.void_time = datetime.now()
        except Exception:
            db.rollback()
            db.expire_all()
            raise
        return True
    # 草稿且未执行过任何库存动作，直接置作废，无需回滚
    order.status = "已作废"
    order.void_time = datetime.now()
    return False


# ---------------- 批量操作 ----------------
# 动作 → 所需权限：审核沿用审核权限，作废沿用删除权限（与单条端点一致）
BATCH_PERMS = {
    "approve": "inventory:transfer:approve",
    "void": "inventory:transfer:delete",
}


def _one_transfer(db: Session, tid: int, action: str, operator: str) -> None:
    """单条批量动作：一张调拨单一个事务（不 commit，由 run_batch 统一提交）。"""
    if action == "approve":
        _do_approve(db, tid, operator)
    elif action == "void":
        _do_void(db, tid, operator)
    else:
        raise BizException(f"不支持的批量动作：{action}")


# ---------------- 接口 ----------------
@router.post("/batch")
def batch_transfers(payload: BatchIn, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """批量审核/作废调拨单（一张单一个事务，逐单返回失败明细）。

    必须声明在 /{tid} 系列动态路由之前，否则 "batch" 会被当成 tid 匹配（int 转换失败报 422）。
    """
    operator = user.username
    return run_batch_guarded(db, user, payload, BATCH_PERMS,
                             lambda d, i, a: _one_transfer(d, i, a, operator))


@router.get("")
def list_transfers(page: int = 1, page_size: int = 20, keyword: str | None = None,
                   status: str | None = None, start_date: str | None = None, end_date: str | None = None,
                   from_warehouse_id: int | None = None, to_warehouse_id: int | None = None,
                   sort_by: str | None = None, sort_order: str | None = None,
                   db: Session = Depends(get_db), _=Depends(require_permissions("inventory:view"))):
    """调拨单分页列表：支持单号/状态/创建日期范围筛选，并返回每条单据的明细行数。"""
    _, whs, _ = load_maps(db)
    q = db.query(TransferOrder)
    if keyword:
        q = q.filter(TransferOrder.transfer_no.like(f"%{keyword}%"))
    if status:
        q = q.filter(TransferOrder.status == status)
    if start_date:
        q = q.filter(func.date(TransferOrder.created_at) >= start_date)
    if end_date:
        q = q.filter(func.date(TransferOrder.created_at) <= end_date)
    if from_warehouse_id:
        q = q.filter(TransferOrder.from_warehouse_id == from_warehouse_id)
    if to_warehouse_id:
        q = q.filter(TransferOrder.to_warehouse_id == to_warehouse_id)
    total = q.count()
    rows = apply_ordering(q, TransferOrder, sort_by, sort_order).offset((page - 1) * page_size).limit(page_size).all()
    # 明细行数一次性聚合，避免逐单查询
    ids = [r.id for r in rows]
    counts = {}
    if ids:
        for tid_, cnt in db.query(TransferItem.transfer_id, func.count(TransferItem.id))\
                .filter(TransferItem.transfer_id.in_(ids)).group_by(TransferItem.transfer_id).all():
            counts[tid_] = int(cnt)
    data = []
    for r in rows:
        d = _row_dict(r, whs)
        d["item_count"] = counts.get(r.id, 0)
        data.append(d)
    return success(page_result(data, total))


@router.get("/{tid}")
def detail_transfer(tid: int, db: Session = Depends(get_db), _=Depends(require_permissions("inventory:view"))):
    """调拨单详情：含明细，并补全物料名称/规格/单位与库位、色号缸号等展示字段。"""
    order = db.get(TransferOrder, tid)
    if not order:
        raise BizException("调拨单不存在")
    mats, whs, _ = load_maps(db)
    meta = material_meta(db)
    batches = _batch_map(db)
    locs = _location_map(db)
    items = db.query(TransferItem).filter(TransferItem.transfer_id == tid).all()
    data = _row_dict(order, whs)
    data["item_count"] = len(items)
    data["items"] = [
        {"id": i.id, "material_id": i.material_id, "material_name": mats.get(i.material_id, ""),
         "spec": meta.get(i.material_id, {}).get("spec", ""),
         "qty": i.qty, "unit": i.unit or meta.get(i.material_id, {}).get("unit", ""),
         "color_batch_id": i.color_batch_id, "color_batch_no": batches.get(i.color_batch_id, ""),
         "from_location_id": i.from_location_id, "from_location_name": locs.get(i.from_location_id, ""),
         "to_location_id": i.to_location_id, "to_location_name": locs.get(i.to_location_id, ""),
         "remark": i.remark}
        for i in items
    ]
    return success(data)


@router.post("")
def create_transfer(data: TransferCreate, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user),
                    _=Depends(require_permissions("inventory:transfer:add"))):
    """新建调拨单（草稿）：校验调出/调入仓库不同且都存在、明细非空、数量大于 0。"""
    from_id = _check_warehouse(db, data.from_warehouse_id, "调出仓库")
    to_id = _check_warehouse(db, data.to_warehouse_id, "调入仓库")
    if from_id == to_id:
        raise BizException("调出仓库与调入仓库不能相同")
    items = _norm_items(data.items)
    order = TransferOrder(transfer_no=gen_no("TR"), from_warehouse_id=from_id, to_warehouse_id=to_id,
                          operator=data.operator or user.username, remark=_s(data.remark),
                          status="草稿", executed=False)
    db.add(order)
    db.flush()
    for it in items:
        db.add(TransferItem(transfer_id=order.id, **it))
    db.commit()
    db.refresh(order)
    _, whs, _ = load_maps(db)
    return success(_row_dict(order, whs), message="新增成功")


@router.put("/{tid}")
def update_transfer(tid: int, data: TransferUpdate, db: Session = Depends(get_db),
                    _=Depends(require_permissions("inventory:transfer:edit"))):
    """修改调拨单：仅草稿状态可编辑，明细整体覆盖。"""
    order = db.get(TransferOrder, tid)
    if not order:
        raise BizException("调拨单不存在")
    if order.status != "草稿":
        raise BizException("仅草稿状态可编辑")
    from_id = order.from_warehouse_id
    to_id = order.to_warehouse_id
    if data.from_warehouse_id is not None:
        from_id = _check_warehouse(db, data.from_warehouse_id, "调出仓库")
    if data.to_warehouse_id is not None:
        to_id = _check_warehouse(db, data.to_warehouse_id, "调入仓库")
    if from_id == to_id:
        raise BizException("调出仓库与调入仓库不能相同")
    order.from_warehouse_id = from_id
    order.to_warehouse_id = to_id
    if data.operator is not None:
        order.operator = data.operator
    if data.remark is not None:
        order.remark = _s(data.remark)
    if data.items is not None:
        db.query(TransferItem).filter(TransferItem.transfer_id == tid).delete()
        for it in _norm_items(data.items):
            db.add(TransferItem(transfer_id=tid, **it))
    db.commit()
    return success(message="修改成功")


@router.post("/{tid}/approve")
def approve_transfer(tid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                     _=Depends(require_permissions("inventory:transfer:approve"))):
    """审核并执行调拨：先对全部明细整体校验库存，再逐条「调出仓库出库 → 调入仓库入库」。
    任一明细库存不足或中途异常即整体回滚，单据状态与库存均保持原样。"""
    _do_approve(db, tid, user.username)
    db.commit()
    return success(message="审核成功，调拨已完成，库存已更新")


@router.post("/{tid}/void")
def void_transfer(tid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                  _=Depends(require_permissions("inventory:transfer:delete"))):
    """作废调拨单：仅草稿或已审核可作废。
    已执行过库存动作的必须先反向回滚——调入仓库出库、调出仓库入库，保证台账可逆。"""
    reversed_flag = _do_void(db, tid, user.username)
    db.commit()
    return success(message="已作废，库存已反向回滚" if reversed_flag else "已作废")
