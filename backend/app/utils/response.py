"""统一响应结构：{code, message, data}。"""
from typing import Any, Optional

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.exceptions import CODE_SUCCESS


def success(data: Any = None, message: str = "success") -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content=jsonable_encoder({"code": CODE_SUCCESS, "message": message, "data": data}),
    )


def error(message: str, code: int = 50000, status_code: int = 200) -> JSONResponse:
    """业务错误也返回 200，由 code 区分，便于前端统一拦截。"""
    return JSONResponse(status_code=status_code, content={"code": code, "message": message, "data": None})


def page_result(rows: list, total: int) -> dict:
    return {"list": rows, "total": total}
