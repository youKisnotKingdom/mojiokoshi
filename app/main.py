import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import get_settings
from app.database import SessionLocal
from app.dependencies import get_current_user_optional, limiter
from app.models.user import User
from app.routers import auth, history, recording_ws, summary, transcription, users
from app.templating import templates

logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: run startup checks, then yield, then cleanup."""
    if not os.environ.get("SKIP_STARTUP_CHECKS"):
        async with httpx.AsyncClient(timeout=5.0) as http_client:
            try:
                await http_client.get(f"{settings.llm_api_base_url}/models")
                logger.info("LLM API is reachable at %s", settings.llm_api_base_url)
            except Exception:
                logger.warning(
                    "LLM API は %s に到達できません — LLMサーバーが起動するまで要約機能は利用できません。",
                    settings.llm_api_base_url,
                )
    yield


app = FastAPI(
    title=settings.app_name,
    description="音声文字起こし＆要約Webアプリケーション",
    version="0.1.0",
    lifespan=lifespan,
)

# nginx リバースプロキシ経由のスキーム情報を信頼する
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
allowed_hosts = [host.strip() for host in settings.allowed_hosts.split(",") if host.strip()]
if allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Static files
BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Include routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(transcription.router)
app.include_router(recording_ws.router)
app.include_router(history.router)
app.include_router(summary.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/health/ready")
async def readiness_check():
    """Readiness probe: verifies DB and storage are accessible."""
    errors = []

    # Check database
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
    except Exception as e:
        errors.append(f"database: {e}")

    # Check upload directory
    upload_dir = Path(settings.upload_dir)
    if not upload_dir.exists():
        errors.append(f"storage: upload directory {upload_dir} does not exist")

    if errors:
        return JSONResponse(status_code=503, content={"status": "not ready", "errors": errors})

    return {"status": "ok", "db": "ok", "storage": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": settings.app_name,
            "current_user": current_user,
        },
    )
