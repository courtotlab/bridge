import os

import requests.exceptions
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.config import router as config_router
from app.api.health import router as health_router
from app.api.mapping import router as mapping_router

app = FastAPI(title="Bridge API", version="0.1.0")

_cors_raw = os.environ.get("CORS_ORIGINS", "http://localhost:5173")
_cors_origins = [o.strip() for o in _cors_raw.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RuntimeError)
async def _runtime_error(request: Request, exc: RuntimeError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def _value_error(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(ImportError)
async def _import_error(request: Request, exc: ImportError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.exception_handler(requests.exceptions.ConnectionError)
async def _connection_error(request: Request, exc: requests.exceptions.ConnectionError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


app.include_router(health_router, prefix="/api")
app.include_router(mapping_router, prefix="/api/map")
app.include_router(config_router, prefix="/api/config")
