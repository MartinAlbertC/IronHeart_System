"""统一 API 响应格式"""
from typing import Any
from fastapi import HTTPException


def ok(data: Any = None, message: str = "success") -> dict:
    return {"code": 0, "data": data, "message": message}


def err(code: int, message: str) -> dict:
    return {"code": code, "data": None, "message": message}


class ApiError(HTTPException):
    def __init__(self, code: int, message: str, http_code: int = 400):
        detail = err(code, message)
        super().__init__(status_code=http_code, detail=detail)
