"""数据模型汇总导入，便于 Base.metadata 统一建表。"""
from app.models.rbac import Permission, Role, RolePermission, User, UserPermission, UserRole
from app.models.master_data import Material, MaterialColorBatch, Supplier, Warehouse, Location
from app.models.bom import BomHeader, BomItem
from app.models.procurement import (
    PurchaseRequisition, PurchaseRequisitionItem,
    PurchaseOrder, PurchaseOrderItem,
    PurchaseArrival, PurchaseArrivalItem,
    PurchaseReturn, PurchaseReturnItem,
)
from app.models.inventory import (
    Inventory, InventoryTransaction, Stocktake, StocktakeItem,
    TransferOrder, TransferItem,
)
from app.models.outsource import OutsourceOrder, OutsourceOrderItem
from app.models.quality import FqcOrder, IqcItem, IqcOrder, OperationLog
from app.models.ai_ocr import AiModelConfig, AiOcrItem, AiOcrRecord
from app.models.reimburse import (
    RmbAccountSubject,
    RmbCityLevel,
    RmbComplianceCheck,
    RmbComplianceIssue,
    RmbDepartment,
    RmbEmployee,
    RmbExpenseType,
    RmbHoliday,
    RmbInvoice,
    RmbPolicy,
    RmbPolicyRule,
    RmbReimbursement,
    RmbSettlementMethod,
    RmbSysParam,
    RmbVoucher,
    RmbVoucherEntry,
)

__all__ = [
    "User", "Role", "Permission", "RolePermission", "UserRole", "UserPermission",
    "Material", "MaterialColorBatch", "Supplier", "Warehouse", "Location",
    "BomHeader", "BomItem",
    "PurchaseRequisition", "PurchaseRequisitionItem",
    "PurchaseOrder", "PurchaseOrderItem",
    "PurchaseArrival", "PurchaseArrivalItem",
    "PurchaseReturn", "PurchaseReturnItem",
    "Inventory", "InventoryTransaction", "Stocktake", "StocktakeItem",
    "TransferOrder", "TransferItem",
    "OutsourceOrder", "OutsourceOrderItem",
    "IqcOrder", "IqcItem", "FqcOrder", "OperationLog",
    "AiOcrRecord", "AiOcrItem", "AiModelConfig",
    "RmbDepartment", "RmbEmployee", "RmbAccountSubject", "RmbExpenseType",
    "RmbSettlementMethod", "RmbCityLevel", "RmbHoliday", "RmbSysParam",
    "RmbPolicy", "RmbPolicyRule",
    "RmbReimbursement", "RmbInvoice", "RmbComplianceCheck", "RmbComplianceIssue",
    "RmbVoucher", "RmbVoucherEntry",
]
