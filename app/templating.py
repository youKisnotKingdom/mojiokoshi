"""Shared Jinja2 templates instance with global helpers."""
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.dependencies import generate_csrf_token

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")
templates.env.globals["generate_csrf_token"] = generate_csrf_token
