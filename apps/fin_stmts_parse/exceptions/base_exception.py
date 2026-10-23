
class ServiceError(Exception):
    """
    全服务统一异常类
    用于包装所有业务逻辑中可预见的错误
    """
    def __init__(self,code:str,message:str,detail:str=None):
        self.code = code #错误编码
        self.message = message #直接返回前端
        self.detail = detail #原始错误堆栈信息
        super().__init__(self.message)

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.detail if self.detail else ""
        }
