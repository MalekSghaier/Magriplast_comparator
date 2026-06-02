from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import init_db
from app.core.logging import setup_logging
from app.core.dependencies import get_current_user
from app.api import upload, jobs, results, admin, suppliers
from app.api.auth import router as auth_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # fil prod sta3ml Alembic — init_db only fil local dev
    if settings.debug:
        await init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    openapi_url=f"{settings.api_prefix}/openapi.json",
    docs_url=f"{settings.api_prefix}/docs",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)
app.include_router(upload.router, prefix=settings.api_prefix, dependencies=[Depends(get_current_user)])
app.include_router(jobs.router, prefix=settings.api_prefix, dependencies=[Depends(get_current_user)])
app.include_router(results.router, prefix=settings.api_prefix, dependencies=[Depends(get_current_user)])
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(suppliers.router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)


@app.get("/health")
async def health_check():
    return {"status": "ok"}