# Agent instructions — Football Analyzer

## Scope and working conventions

These instructions apply to the entire repository. Follow the user's current request and preserve unrelated changes. Keep documentation and code identifiers in English; respond in the user's language.

Read `README.md` for setup and `PLAN_FORWARD.md` before proposing model improvements. The roadmap contains proposed experiments, not implemented features or permission to execute every idea. For planning-only requests, edit documentation only: do not retrain, import data, install dependencies, or modify application code.

Prefer small, reviewable changes that solve the requested problem. Do not introduce a frontend framework, database, external service, or new dependency without a concrete need. Do not restore the removed legacy Serie A model or scraping pipeline.

## Application structure

The repository root and application directory are different:

- `start.sh`: starts the application from the repository root.
- `Footballanalyzer-master/api/main.py`: FastAPI application; serves API routes before mounting the static website.
- `Footballanalyzer-master/api/matches.py`: league catalog, team statistics, predictions, and model-bundle loading.
- `Footballanalyzer-master/frontend/`: plain HTML, CSS, and JavaScript.
- `Footballanalyzer-master/ml/matches.py`: chronological feature generation, training, and evaluation.
- `Footballanalyzer-master/update_football.py`: API-Football import, response caching, quota accounting, and bundle publication.
- `Footballanalyzer-master/football_config.py`: central paths and supported league IDs.
- `Footballanalyzer-master/tests/`: offline unit tests.
- `docs/original-project/`: historical report and demo archive; not application dependencies.

Supported leagues: Premier League (39), La Liga (140), Serie A (135), Bundesliga (78), and Ligue 1 (61). Use the configuration as the source of truth rather than duplicating IDs.

## Local commands

Use the project's existing environment, not the global Python installation. Python 3.10–3.13 is documented as supported.

From the repository root:

```sh
sh start.sh
```

Website: `http://localhost:8000`. Interactive API documentation: `http://localhost:8000/docs`.

From `Footballanalyzer-master/`:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Only if initial setup is needed, from `Footballanalyzer-master/`:

```sh
python3.10 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Do not reinstall packages for routine changes. Inspect existing listeners before starting a server. Restart only the process identified as this project's server; do not terminate unrelated processes or switch ports without explaining why.

## Data, secrets, and request budget

`Footballanalyzer-master/.env` contains `API_FOOTBALL_KEY`. Never print, paste, commit, log, or expose its value to the frontend. Use `.env.example` for configuration documentation. Do not read the secret just to inspect project structure.

Preserve the active `models/match_bundle.joblib`, downloaded `data/api_football/` files, quota ledger, and `.venv/` during cleanup. These are generated/local resources, but the running app or offline work depends on them. They are excluded from Git.

The account has a 100-request daily allowance. Existing safeguards include a 35-request per-run default, an 80-request local daily cap, a 20-request reserve, 24-hour response caching, spaced requests, and a single-update lock. Preserve these safeguards. Never reset the quota ledger or bypass caching to make a request succeed.

The user explicitly requested a current-data query before prediction. `current_data.py` refreshes Football-Data results on league selection and before every prediction without API-Football quota. Preserve that behavior; fail visibly if refresh fails. Tests must remain offline. Do not add API-Football web calls.

Run imports when the user's task requires data updates, not as a routine test. From the application directory, the importer is:

```sh
.venv/bin/python update_football.py
```

This can spend quota and replace the active bundle. It is not an offline training command. Prefer cached data for experiments and use separate candidate artifacts. Never assume a cached response will still be fresh after 24 hours.

On 16 October 2026, the account allowed seasons 2022–2024 and rejected 2025–2026. This is a dated observation, not a permanent provider guarantee. Display actual season coverage and freshness; do not describe historical estimates as current predictions. Do not repeatedly probe rejected seasons, enable schedules, or change subscriptions unless that work is requested.

## Modeling rules

- Predict three outcomes: home win, draw, and away win. Keep class-to-probability mapping explicit; probabilities must be finite, nonnegative, and sum to one.
- Build each example only from information available before its prediction time. Never use the target match's result, final season standings, post-match ratings, or today's injury data as historical inputs.
- The API importer retains four-hour availability after kickoff; Football-Data uses 04:00 UTC the next day because source time zones are not guaranteed. Simultaneous or overlapping matches must not leak results into one another.
- Exclude relegation play-offs before accumulating regular-season statistics or collecting league teams. Preserve fixture-ID duplicate checks and score validation.
- The current two-season model requires five completed games across current and previous seasons. Promoted teams without previous top-division history require five current-season games. Blend season rates 70/30 when both exist; otherwise use the available season. Keep this behavior tested.
- Keep training, preprocessing, hyperparameter selection, early stopping, and calibration chronological. Do not randomly split fixtures across time.
- Compare candidate models on the same fixtures and coverage. Report log loss, accuracy, baseline results, and sample counts; include league/class breakdowns when relevant.
- The existing validation period has already been inspected. Do not present it as an untouched final test. Record experiments and decisions in `PLAN_FORWARD.md`.
- Preserve model and team-data consistency through atomic bundle publication. Check serialization compatibility before changing dependency versions or bundle structure.

The current importer refits on all eligible data and publishes even when validation underperforms the baseline. That is existing behavior, not a model-selection standard. Model experiments should retain the active bundle and report candidate results separately unless replacing it is part of the task.

## API and frontend behavior

Keep the frontend and API on the same origin, using relative API URLs. Existing routes are `/api/catalog`, `/api/football/teams`, `/api/football/team/{team}`, and `/api/football/compare`.

Keep league boundaries explicit: a selected team must belong to the selected league. Preserve validation for identical teams and insufficient match history. A fresh checkout without a model should show setup guidance, not crash or invent predictions.

When changing asynchronous UI behavior, ensure a delayed response cannot overwrite a newer league/team selection. Keep visible explanations focused on season, freshness, and prediction limitations. Do not invent values for unavailable statistics.

## Odds-assessment feature

The user has requested a future feature that accepts bookmaker odds for a selected team/outcome and assesses potential betting value against the model's independent match probabilities. The detailed requirements are E16 in `PLAN_FORWARD.md`. Manual odds and simulation calculations are implemented in `api/odds.py` and the prediction form. Current-fixture assessment, quote-time validation, and calibrated decision thresholds remain planned. Do not describe the simulation as a current-bet recommendation or implement extensions during documentation-only tasks.

When implementing it:

- Start with manually entered decimal odds for a specified fixture and 90-minute home/draw/away market. Validate finite odds greater than 1, the selected outcome, kickoff, and quote time. Do not silently interpret qualification, extra-time, handicap, or other markets as match-winner odds.
- Keep model probabilities independent of entered odds. Changing a price must not change the underlying match forecast.
- Show break-even probability `1 / odds`, model-implied fair odds `1 / probability`, edge in percentage points, and expected net return per unit `probability * odds - 1`. Handle zero probability explicitly. State the standard win/lose, no-fees assumption.
- Do not infer the bookmaker's full margin from one price. If all three matching prices are available, any proportional margin removal must be labeled an approximation; expected return still uses the actual offered odds.
- Use potential-value/no-positive-value/insufficient-evidence states. Validate the uncertainty buffer on development data rather than treating every positive point estimate as a favorable assessment.
- Require fresh, fixture-appropriate data and calibration evidence before assessing current bets. Historical data may support a labeled simulation, not an endorsement of a current-season bet.
- Explain that this assesses estimated value, not personal affordability or guaranteed profit. Do not call a bet safe or risk-free. Stake sizing and automated betting are outside the requested scope.
- Add focused tests for calculations, outcome mapping, unchanged probabilities when prices change, invalid input, and stale/mismatched data. Any backtest must align odds and features with the same prediction time and report uncertainty as well as returns.
- Manual input must not consume external API quota. Automatic odds feeds are a separate feature decision.

## Verification and completion

For application changes, run the relevant offline tests; run the full existing suite for shared API, feature-generation, or training changes. Add focused regression tests for changed behavior, especially leakage prevention, quotas, and league isolation. Documentation-only changes do not require model training or network tests.

For API/frontend changes, verify the affected user flow locally. For shared prediction changes, check all five leagues. Use synthetic fixtures only in isolated tests, never as replacement production data.

Before finishing, review the diff for unrelated edits, secrets, generated artifacts, and outdated documentation. Explain what changed, which checks passed, and any unverified limitations. Do not claim improved model quality without an evaluated comparison.

## Premier League round tracker

`pl_rounds.py` implements the user-authorized startup/hourly worker while the app runs, plus manual synchronization. It uses official FPL fixtures and final results for scheduling/evaluation, and the existing Football-Data refresh for training. Never backfill predictions for started matches. Preserve original forecast probabilities, features, timestamps, original kickoff/round and archived model IDs when retraining, rescheduling or correcting results. Keep feedback separate from inclusion in training when source publication differs. No automatic accuracy improvement is promised.

Preserve `data/pl_rounds/history.json` and archived models in `data/pl_rounds/models/`; these hold prospective evidence and are excluded from Git. Tests must mock source access and isolate history/model artifacts in temporary directories. The schedule runs only while the server is up; do not imply the computer wakes itself. The UI is `frontend/rounds.html`, with local report and explicit sync endpoints in `api/main.py`.
