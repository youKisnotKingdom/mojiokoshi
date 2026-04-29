"""Shared Jinja2 templates instance with global helpers."""
from pathlib import Path
from datetime import timezone
import re

from fastapi.templating import Jinja2Templates

from app.dependencies import generate_csrf_token
from app.time_utils import to_tokyo, utc_now

BASE_DIR = Path(__file__).resolve().parent.parent


class AppJinja2Templates(Jinja2Templates):
    def TemplateResponse(self, *args, **kwargs):
        if args and isinstance(args[0], str):
            name = args[0]
            context = args[1] if len(args) > 1 else kwargs.get("context", {})
            status_code = args[2] if len(args) > 2 else kwargs.get("status_code", 200)
            headers = args[3] if len(args) > 3 else kwargs.get("headers")
            media_type = args[4] if len(args) > 4 else kwargs.get("media_type")
            background = args[5] if len(args) > 5 else kwargs.get("background")
            request = context.get("request")
            if request is None:
                raise ValueError('context must include a "request" key')
            return super().TemplateResponse(
                request,
                name,
                context,
                status_code,
                headers,
                media_type,
                background,
            )
        return super().TemplateResponse(*args, **kwargs)


templates = AppJinja2Templates(directory=BASE_DIR / "app" / "templates")
templates.env.globals["generate_csrf_token"] = generate_csrf_token


def format_jst_datetime(value, fmt: str = "%Y/%m/%d %H:%M:%S"):
    dt = to_tokyo(value)
    if dt is None:
        return ""
    return dt.strftime(fmt)


def format_duration_seconds(value) -> str:
    if value is None:
        return "-"
    try:
        seconds = max(0.0, float(value))
    except (TypeError, ValueError):
        return "-"

    if seconds < 60:
        return f"{seconds:.1f}秒"
    minutes, secs = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}分{secs:02d}秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}時間{minutes:02d}分{secs:02d}秒"


def format_timecode(value) -> str:
    try:
        total_seconds = int(round(max(0.0, float(value or 0.0))))
    except (TypeError, ValueError):
        total_seconds = 0
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_elapsed_between(start, end=None) -> str:
    if start is None:
        return "-"
    effective_end = end or utc_now()
    try:
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if effective_end.tzinfo is None:
            effective_end = effective_end.replace(tzinfo=timezone.utc)
        return format_duration_seconds((effective_end - start).total_seconds())
    except (TypeError, ValueError):
        return "-"


_TIME_PREFIX_PATTERN = re.compile(
    r"^\s*(?:\[\s*)?\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\s*[-–]\s*"
    r"\d{1,2}:\d{2}:\d{2}(?:\.\d+)?(?:\s*\])?\s*"
)


def strip_timecode_prefixes(value) -> str:
    if value is None:
        return ""

    lines = []
    for line in str(value).splitlines():
        stripped = _TIME_PREFIX_PATTERN.sub("", line).strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines)


templates.env.filters["jst_datetime"] = format_jst_datetime
templates.env.filters["duration_seconds"] = format_duration_seconds
templates.env.filters["elapsed_between"] = format_elapsed_between
templates.env.filters["timecode"] = format_timecode
templates.env.filters["strip_timecode_prefixes"] = strip_timecode_prefixes
