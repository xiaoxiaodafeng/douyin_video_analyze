from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response

from app.core.config import settings
from app.db.session import Base, engine, migrate_legacy_sqlite_schema
from app.routers.api import router as api_router

migrate_legacy_sqlite_schema()
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/api/")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)
