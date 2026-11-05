"""Serve the football API and website from one local server."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager, suppress
import asyncio
import pl_rounds
import norsk_tipping
from datetime import datetime, timezone, timedelta

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


@app.get('/api/pl-rounds/norsk-tipping')
def rounds_norsk_tipping(season: int, round: int):
    if not 1 <= round <= 38:
        raise HTTPException(422, 'Invalid round')
    now = datetime.now(timezone.utc)
    fixtures = [r for r in pl_rounds.report()['records'] if r['season'] == season and r['round'] == round
                and r.get('kickoff') and not r.get('started') and pl_rounds.timestamp(r['kickoff']) > now]
    if not fixtures:
        return {'quotes': [], 'fetched_at': None}
    starts = [pl_rounds.timestamp(r['kickoff']).astimezone(timezone.utc).date() for r in fixtures]
    try:
        # Pad UTC dates for matches near midnight in Norwegian time.
        events, fetched = norsk_tipping.fetch_events(min(starts)-timedelta(days=1), max(starts)+timedelta(days=1))
        return {'quotes': norsk_tipping.match_quotes(events, fixtures, now), 'fetched_at': fetched}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except norsk_tipping.SourceError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post('/api/pl-rounds/sync')
def rounds_sync():
    return pl_rounds.sync()


class RoundPredictionInput(BaseModel):
    season: int
    round: int = Field(ge=1, le=38)


@app.post('/api/pl-rounds/predict-round')
def rounds_predict_round(request: RoundPredictionInput):
    try:
        return pl_rounds.predict_round(request.season, request.round)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (norsk_tipping.SourceError, OSError) as exc:
        raise HTTPException(503, 'Could not refresh fixtures, results or odds. No new simulations were saved.') from exc


class SimulationInput(BaseModel):
    fixture_id: str
    home: float = Field(gt=1, le=10000, allow_inf_nan=False)
    draw: float = Field(gt=1, le=10000, allow_inf_nan=False)
    away: float = Field(gt=1, le=10000, allow_inf_nan=False)


@app.post('/api/pl-rounds/simulate')
def rounds_simulate(quote: SimulationInput):
    try:
        return pl_rounds.simulate_fixture(quote.fixture_id, {'home': quote.home, 'draw': quote.draw, 'away': quote.away})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, 'Could not refresh fixtures or results; no simulation was saved') from exc


app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
