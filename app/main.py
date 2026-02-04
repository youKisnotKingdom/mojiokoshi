from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.dependencies import get_current_user_optional
from app.models.user import User
from app.routers import auth, history, recording_ws, summary, transcription, users

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Audio transcription and summarization web application",
    version="0.1.0",
)

# Static files
BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Templates
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")

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
