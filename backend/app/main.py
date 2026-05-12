"""FastAPI application entry point."""
from fastapi import FastAPI

app = FastAPI(title="Bridge", version="0.1.0")


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "Bridge API - Under Construction"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
