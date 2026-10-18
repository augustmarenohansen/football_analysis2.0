"""Serve the football API and website from one local server."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.matches import router
from football_config import ROOT

app = FastAPI(title="Football Analyzer")
app.include_router(router)
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
