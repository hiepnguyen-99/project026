from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .api.v1 import access_requests, admin, auth, documents, search
from .core.config import settings
from .db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    yield
    await engine.dispose()


app = FastAPI(
    title="EduVault API",
    description="AI Knowledge Vault for Faculty",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(access_requests.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    """Kiểm tra DB và trả về trạng thái hệ thống."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}
