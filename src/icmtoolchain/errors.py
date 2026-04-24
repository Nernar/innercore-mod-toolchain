from typing import NoReturn, Optional


class ToolchainError(Exception):
    def __init__(self, message: str, code: int = 255, cause: Optional[BaseException] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.cause = cause

def abort(*values: object, sep: Optional[str] = " ", code: int = 255, cause: Optional[BaseException] = None) -> NoReturn:
    message = sep.join(str(v) for v in values) if sep is not None else " ".join(str(v) for v in values)
    if not message and not cause:
        message = "Abort."
    raise ToolchainError(message, code, cause)
