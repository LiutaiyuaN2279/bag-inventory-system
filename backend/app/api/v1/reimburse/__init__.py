"""差旅与业务招待费报销智能体：路由包。

拆 4 个模块，便于按业务域维护：
- bills.py       报销单（填写 / 识别 / 保存 / 列表 / 详情 / 作废 / 原件）
- compliance.py  合规判读（执行判读 / 结果详情 / 处理结论 / 判读记录）
- vouchers.py    凭证（待制证 / AI 制证 / 校验 / 保存 / 复核 / 详情 / 修改退回）
- policy.py      制度与参数管理（制度版本 / 规则 / 参数 / 城市等级 / 节假日）

main.py 挂载方式（4 行）：
    from app.api.v1.reimburse import bills as rmb_bills_router
    app.include_router(rmb_bills_router.router, prefix="/api/v1")
    ...
也可用下面的 ALL_ROUTERS 一次性挂载。
"""
from app.api.v1.reimburse.bills import router as bills_router
from app.api.v1.reimburse.compliance import router as compliance_router
from app.api.v1.reimburse.policy import router as policy_router
from app.api.v1.reimburse.vouchers import router as vouchers_router

#: 供 main.py 一次性挂载：for r in ALL_ROUTERS: app.include_router(r, prefix="/api/v1")
ALL_ROUTERS = (bills_router, compliance_router, vouchers_router, policy_router)

__all__ = [
    "bills_router",
    "compliance_router",
    "vouchers_router",
    "policy_router",
    "ALL_ROUTERS",
]
