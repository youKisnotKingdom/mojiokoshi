"""Shared Jinja2 templates instance with global helpers."""
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.dependencies import generate_csrf_token
from app.time_utils import to_tokyo

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")
templates.env.globals["generate_csrf_token"] = generate_csrf_token


def format_jst_datetime(value, fmt: str = "%Y/%m/%d %H:%M:%S"):
    dt = to_tokyo(value)
    if dt is None:
        return ""
    return dt.strftime(fmt)


templates.env.filters["jst_datetime"] = format_jst_datetime
