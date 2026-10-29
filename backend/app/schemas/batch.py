"""批量操作通用入参。

所有 `POST /xxx/batch` 接口共用这套结构，避免每个模块各写一份 schema。
"""
from typing import Optional

from pydantic import BaseModel, Field


class BatchIn(BaseModel):
    """批量操作入参。

    ids:    勾选行的主键列表（后端会去重，保持传入顺序）
    action: 动作名，取值由各模块自行约定（如 approve / void / delete / enable / disable）
    reason: 需要填写原因的动作使用（驳回等），其余动作为空
    """

    ids: list[int] = Field(default_factory=list)
    action: str = ""
    reason: Optional[str] = None
