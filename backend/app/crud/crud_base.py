"""通用 CRUD 基类：分页、关键字搜索、增删改查。"""
from typing import Any, Generic, Type, TypeVar

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import Base

ModelType = TypeVar("ModelType", bound=Base)


def apply_ordering(query, model, sort_by: str | None = None, sort_order: str | None = None):
    """多级排序：sort_by / sort_order 可为逗号分隔的多列（如 "category,qty" + "asc,desc"）。
    sort_by 必须是模型真实列名（防注入）；全部无效时回退默认 id 倒序，并以 id 作为最终稳定排序键。"""
    valid = {c.name for c in model.__table__.columns}
    cols = [s.strip() for s in (sort_by or "").split(",") if s.strip()]
    orders = [s.strip().lower() for s in (sort_order or "").split(",")]
    applied = False
    for i, fld in enumerate(cols):
        if fld in valid:
            col = getattr(model, fld)
            asc = (orders[i] if i < len(orders) else "asc") == "asc"
            query = query.order_by(col.asc() if asc else col.desc())
            applied = True
    # 以主键作为最终 tiebreaker，保证分页稳定（除非用户本身就在按 id 排）
    if applied and "id" not in cols:
        query = query.order_by(model.id.desc())
    if not applied:
        query = query.order_by(model.id.desc())
    return query


class CRUDBase(Generic[ModelType]):
    def __init__(self, model: Type[ModelType]):
        self.model = model

    def get(self, db: Session, obj_id: int) -> ModelType | None:
        return db.get(self.model, obj_id)

    def get_multi(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
        search_fields: list[str] | None = None,
        filters: dict | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> tuple[list[ModelType], int]:
        stmt = select(self.model)
        count_stmt = select(func.count()).select_from(self.model)

        if keyword and search_fields:
            like = f"%{keyword}%"
            conds = [getattr(self.model, f).like(like) for f in search_fields if hasattr(self.model, f)]
            if conds:
                stmt = stmt.where(or_(*conds))
                count_stmt = count_stmt.where(or_(*conds))

        if filters:
            for k, v in filters.items():
                if v is not None and hasattr(self.model, k):
                    stmt = stmt.where(getattr(self.model, k) == v)
                    count_stmt = count_stmt.where(getattr(self.model, k) == v)

        total = db.execute(count_stmt).scalar() or 0
        stmt = apply_ordering(stmt, self.model, sort_by, sort_order).offset((page - 1) * page_size).limit(page_size)
        rows = db.execute(stmt).scalars().all()
        return list(rows), total

    def create(self, db: Session, obj_in: dict) -> ModelType:
        obj = self.model(**obj_in)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def update(self, db: Session, db_obj: ModelType, obj_in: dict) -> ModelType:
        for k, v in obj_in.items():
            if v is not None and hasattr(db_obj, k):
                setattr(db_obj, k, v)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def remove(self, db: Session, obj_id: int) -> bool:
        obj = db.get(self.model, obj_id)
        if not obj:
            return False
        db.delete(obj)
        db.commit()
        return True
