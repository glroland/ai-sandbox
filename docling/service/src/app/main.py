from app.logging_config import configure_logging

configure_logging()

from fastapi import FastAPI  # noqa: E402 — must come after logging is configured

from app.config import settings
from app.routers import convert, health

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Convert PDFs and other document types to Markdown or JSON.",
)

app.include_router(health.router)
app.include_router(convert.router)
