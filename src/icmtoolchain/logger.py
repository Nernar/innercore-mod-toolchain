from io import StringIO
from typing import Any, Optional

from .shell import (UNICODE_BALLOT_X, UNICODE_CHECK_MARK, UNICODE_POINTED_STAR,
                    UNICODE_SNOWFLAKE)
from .shell import pretty_print as print


def debug(*values: object, sep: Optional[str] = " ", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False) -> None:
	print(*values, sep=sep, end=end, file=file, flush=flush, style="class:print.debug", include_default_pygments_style=include_default_pygments_style)

def info(*values: object, sep: Optional[str] = " ", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False) -> None:
	print(*values, sep=sep, end=end, file=file, flush=flush, style="class:print.info", include_default_pygments_style=include_default_pygments_style)

def warn(*values: object, sep: Optional[str] = " ", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False) -> None:
	print(*values, sep=sep, end=end, file=file, flush=flush, style="class:print.warn", include_default_pygments_style=include_default_pygments_style)

def error(*values: object, sep: Optional[str] = " ", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False) -> None:
	print(*values, sep=sep, end=end, file=file, flush=flush, style="class:print.error", include_default_pygments_style=include_default_pygments_style)

def trace(cause: BaseException, is_error: bool = True, sep: Optional[str] = "\n", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False) -> None:
	from traceback import print_exception
	buffer = StringIO()
	print_exception(cause.__class__, cause, cause.__traceback__, file=buffer)
	lines = buffer.getvalue().rsplit("\n", 13)[1:-1]
	if is_error:
		error(*lines, sep=sep, end=end, file=file, flush=flush, include_default_pygments_style=include_default_pygments_style)
	else:
		warn(*lines, sep=sep, end=end, file=file, flush=flush, include_default_pygments_style=include_default_pygments_style)

def success(*values: object, sep: str = " ", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False):
	print(UNICODE_CHECK_MARK, style="class:print.success", end=" ")
	print(*values, style="class:print.success", sep=sep, end=end, file=file, flush=flush, include_default_pygments_style=include_default_pygments_style)

def attention(*values: object, sep: str = " ", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False):
	print(UNICODE_POINTED_STAR, style="class:print.attention", end=" ")
	print(*values, style="class:print.attention", sep=sep, end=end, file=file, flush=flush, include_default_pygments_style=include_default_pygments_style)

def failure(*values: object, sep: str = " ", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False):
	print(UNICODE_BALLOT_X, style="class:print.failure", end=" ")
	print(*values, style="class:print.failure", sep=sep, end=end, file=file, flush=flush, include_default_pygments_style=include_default_pygments_style)

def frozen(*values: object, sep: str = " ", end: Optional[str] = "\n", file: Optional[Any] = None, flush: bool = False, include_default_pygments_style: bool = False):
	print(UNICODE_SNOWFLAKE, style="class:print.frozen", end=" ")
	print(*values, style="class:print.frozen", sep=sep, end=end, file=file, flush=flush, include_default_pygments_style=include_default_pygments_style)

__all__ = [
	"print",
	"debug",
	"info",
	"warn",
	"error",
	"trace",
	"success",
	"attention",
	"failure",
	"frozen"
]
