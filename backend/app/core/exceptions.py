"""业务异常定义与统一错误码。"""

# 错误码约定：0 成功；401xx 未认证；403xx 无权限；其他为业务错误
CODE_SUCCESS = 0
CODE_UNAUTHORIZED = 40100
CODE_FORBIDDEN = 40300
CODE_BIZ_ERROR = 50000


class BizException(Exception):
    def __init__(self, message: str, code: int = CODE_BIZ_ERROR):
        self.message = message
        self.code = code
        super().__init__(message)


class AuthException(BizException):
    def __init__(self, message: str = "未登录或登录已过期"):
        super().__init__(message, CODE_UNAUTHORIZED)


class PermissionException(BizException):
    def __init__(self, message: str = "无操作权限"):
        super().__init__(message, CODE_FORBIDDEN)
