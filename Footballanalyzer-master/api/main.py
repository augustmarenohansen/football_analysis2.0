"""Serve the football API and website from one local server."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager, suppress
import asyncio
import pl_rounds

from api.matches import router
from football_config import ROOT

@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(pl_rounds.monitor())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Football Analyzer", lifespan=lifespan)
app.include_router(router)


@app.get('/api/pl-rounds')
def rounds_report():
    return pl_rounds.report()


@app.post('/api/pl-rounds/sync')
def rounds_sync():
    return pl_rounds.sync()


app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
