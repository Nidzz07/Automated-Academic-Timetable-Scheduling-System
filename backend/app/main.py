"""FastAPI application entrypoint.

Run locally with:  uvicorn backend.app.main:app --reload
"""

from fastapi import FastAPI

app = FastAPI(title="Chronos API")
