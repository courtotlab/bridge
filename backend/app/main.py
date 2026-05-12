from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.config import router as config_router
from app.api.health import router as health_router
from app.api.mapping import router as mapping_router

app = FastAPI(title="Bridge API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(mapping_router, prefix="/api/map")
app.include_router(config_router, prefix="/api/config")
