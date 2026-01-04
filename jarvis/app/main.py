"""FastAPI entrypoint for Jarvis MVP."""
from fastapi import FastAPI

from .core.app import create_app

app: FastAPI = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("jarvis.app.main:app", host="0.0.0.0", port=8000, reload=True)
