# Football Analyzer

A local football analysis app that uses machine learning to estimate the probabilities of a home win, draw, or away win. Compare teams, inspect season statistics and recent form, and switch between five European leagues.

Originally created as a student project at HVL by **Steffen Ulvestad and August Mareno Hansen**.

## Supported leagues

| League | Country | API-Football ID |
| --- | --- | --- |
| Premier League | England | 39 |
| La Liga | Spain | 140 |
| Serie A | Italy | 135 |
| Bundesliga | Germany | 78 |
| Ligue 1 | France | 61 |

The match model uses regular-season fixtures. Relegation play-offs are excluded from training and team statistics.

## Run locally

From this repository's root directory, start the configured application:

```sh
sh start.sh
```

Open [localhost:8000](http://localhost:8000). The website and API run on the same server. Stop the server with `Ctrl+C`.

Interactive API documentation is available at [localhost:8000/docs](http://localhost:8000/docs).

### First-time setup

The commands below are for macOS/Linux. Use Python **3.10–3.13** and create a separate environment:

```sh
cd Footballanalyzer-master
python3.10 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cd ..
sh start.sh
```

Replace `python3.10` with your installed compatible Python version if necessary. Dependencies use scikit-learn 1.7.2 for model training and loading.

On first league selection, the application downloads current and previous-season results and trains the model. Network access is required on league selection and before each prediction. The first load can take a few seconds.

## Current-season predictions

The default source is [Football-Data.co.uk](https://football-data.co.uk/downloadm.php). It provides published results for all five leagues without consuming API-Football quota or requiring a key. Selecting a league refreshes its current-season results and team list; pressing **Predict** makes another request before calculating. Previous-season results are retained locally. Unchanged results reuse the trained model. Changed results trigger chronological training and atomic publication of a consistent model and team snapshot.

The two-season window means **current season plus previous season**: currently 2026/27 and 2025/26. Each team's current-season per-match statistics and last-five form contribute **70%**, with **30%** from the previous season. These are initial policy weights, not optimized or proven to improve accuracy. Training examples use the same blend from information available before each match. Model fitting gives each eligible match equal sample weight; the 70/30 blend applies to team features.

Current-division membership comes from the current-season results file, with an expected 20 clubs in England, Spain and Italy and 18 in Germany and France. Relegated clubs are excluded from selection. Promoted clubs without previous top-division history use current-season data only and need five completed games. Returning clubs need five games in total across the two seasons. Before the first current-season results establish the full roster, the application reports unavailable data rather than showing last year's division.

Season rollover is July 1 for these five leagues. The interface separately shows **last checked** and **latest result date**. The source publishes batches, not a live feed: a successful check today does not mean every match played today is already included. Since the source's time zone is not guaranteed, results become usable at 04:00 UTC on the day after the match date. This conservative rule applies to training and serving.

If the current download or validation fails, prediction stops with a visible error; the previous snapshot is retained but is not silently used to make a new prediction. The active model is `models/current_bundle.joblib`; the earlier API-Football model remains preserved separately. To preload all leagues, run from `Footballanalyzer-master/`:

```sh
.venv/bin/python current_data.py
```

## Optional historical import from API-Football

1. Find your API key under **Account → My Access** in the [API-Football dashboard](https://dashboard.api-football.com/).
2. Create or edit `Footballanalyzer-master/.env` and add:

   ```dotenv
   API_FOOTBALL_KEY=your_api_key
   ```

3. Run the importer from the repository root:

   ```sh
   cd Footballanalyzer-master
   .venv/bin/python update_football.py
   ```

Keep the key in `.env`, which is excluded from Git. It is used only by the Python importer and is never sent to the frontend.

The default import checks seasons **2022–2026** for all five leagues. API-Football identifies seasons by their starting year: `2024` means **2024/2025**.

### Available seasons

The account used for the import on **16 October 2026** allowed seasons **2022/2023, 2023/2024, and 2024/2025**. The free plan rejected 2025/2026 and 2026/2027. Availability depends on the account and provider; current-season access is not guaranteed.

This optional importer writes the separate historical bundle. It does not replace the current-season model used by the website.

### Request limits and caching

The integration is designed around the account's **100 requests per day** allowance:

- A full initial import makes up to **30 requests**: five league lookups and 25 season lookups.
- Responses, including season-access errors, are cached locally for **24 hours**.
- Requests are spaced at least **6.1 seconds** apart, with no automatic retries after network or HTTP errors.
- The default per-run limit is **35 requests**. The local daily limit is **80**, with a reserve of 20 requests based on the last known remaining quota.
- The importer reads the provider's remaining-quota header. Requests made through the dashboard or other applications between imports cannot be tracked locally.
- Browsing teams and generating predictions use **zero API-Football requests**.

API-Football imports run manually; no scheduled background import is enabled. Current results refresh on demand through Football-Data.

To import only the seasons confirmed accessible during the initial setup:

```sh
# Run inside Footballanalyzer-master
.venv/bin/python update_football.py --seasons 2022 2023 2024
```

For a fresh setup limited to selected leagues:

```sh
.venv/bin/python update_football.py --leagues 135 39 --seasons 2023 2024 --max-requests 10
```

Once a model is active, subsequent imports must include all its leagues and at least their latest imported season. The importer refuses to remove leagues or downgrade seasons. Include the historical seasons as well to retain the same training coverage.

A successful historical import publishes its model and team data together in `match_bundle.joblib`. The website uses the separate `current_bundle.joblib`. If an import fails, the existing bundle is preserved.

## How the model works

The new model is a logistic regression classifier trained on actual **home win / draw / away win** outcomes. Features include league identity, games played, goals scored and conceded, goal difference, points, win/draw rates, and form over the last five matches.

For each training match, team statistics come from earlier available results and, where present, the previous season. The current source uses the conservative next-day availability rule described above. Final season tables are never used as inputs for earlier matches.

Evaluation uses a chronological split: approximately the earliest 80% of eligible matches for training and the latest 20% for validation, with a time buffer at the split. Accuracy and log loss are compared against a baseline using training-set outcome frequencies. The published model is then refitted on all eligible matches.

### Preserved historical baseline

The import on **16 October 2026** downloaded **5,341 fixture records** across 15 league-seasons. After excluding play-offs and applying the feature-history requirements:

| Metric | Match model | Outcome-frequency baseline |
| --- | --- | --- |
| Validation accuracy | 51.2% | 40.9% |
| Validation log loss (lower is better) | 1.001 | 1.082 |

The evaluation used **3,672 training matches** and **921 validation matches**. These are historical validation results, not a guarantee of future prediction accuracy. The active two-season model metrics are available at `/api/catalog`. Its current validation uses a different match set and cannot establish an improvement over this historical baseline.

Top-scorer and goalkeeper information is not fetched by the new importer, so these fields display a dash. This avoids extra API requests.

## Optional odds comparison

Select two teams, choose home win/draw/away win under **Compare odds**, enter decimal
odds greater than 1 (for example `2.20`), then press **Predict**. Leave odds blank for
an ordinary match prediction.

The comparison shows model probability, break-even probability, model-implied fair
odds, percentage-point edge, and expected net return per unit. Prices do not affect
the match model. This uses manual input and consumes no API-Football requests.

The odds comparison is a **simulation**, using the displayed two-season
team statistics. It does not select an actual dated fixture or validate a
bookmaker quote. Current-bet assessment therefore always says **insufficient
evidence**, even if the mathematical estimate is positive. Current-fixture
assessment requires fresh data and validated calibration/uncertainty handling.

Only the 90-minute three-way outcome market is supported (including stoppage time,
excluding extra time and penalties). Calculations assume a standard win/lose bet
with no fees or taxes. A single price does not reveal the bookmaker's full margin.
Expected return is an estimate, not guaranteed profit or a personal affordability
assessment. No stake sizing or bet placement is provided.

## Tests

Run from the repository root:

```sh
cd Footballanalyzer-master
.venv/bin/python -m unittest discover -s tests -v
```

Tests run without network access or API quota usage. They cover feature timing, play-off exclusion, model serialization, prediction probabilities, league isolation, caching, and request-budget protection.

## Project structure

```text
.
├── README.md
├── start.sh                       # Start the local server
├── docs/original-project/         # Original report and demo archive
└── Footballanalyzer-master/
    ├── api/                       # FastAPI routes and local model serving
    ├── frontend/                  # HTML, CSS, and JavaScript interface
    ├── ml/                        # Feature generation and match-model training
    ├── data/                      # Cached API responses and quota tracking
    ├── models/                    # Generated match-model bundle
    ├── tests/                     # Offline tests
    ├── football_config.py         # Supported leagues and local paths
    ├── current_data.py            # Refresh current results and publish the two-season model
    ├── update_football.py         # Fetch, validate, train, and publish
    ├── requirements.txt
    └── .env.example               # API key configuration template
```

The original school-project report and demo archive are preserved under `docs/original-project/`. They are not used by the application.

## Premier League rounds and learning history

Open [Premier League round tracker](http://localhost:8000/rounds.html) or follow the link on the home page. The application checks the official Fantasy Premier League schedule and results on startup and every hour while the server is running. **Check now** triggers the same workflow manually. The computer must be awake and the server running; this is an application feature, not an operating-system or Codex scheduled task. It uses no API-Football quota.

Each round with a scheduled match in the next seven days receives forecasts for its future, unstarted fixtures. Forecasts are stored once, before kickoff, including home/draw/away probabilities, input features, prediction time, original kickoff and round, source freshness, baseline probabilities, and archived model identity. A postponed fixture retains its original forecast; if its revised kickoff predates forecast creation, it is excluded from evaluation. Fixtures with no confirmed kickoff or insufficient team history remain pending. Games already started when the tracker first runs never receive retrospective forecasts.

After final results arrive and at least four hours have passed since kickoff, the tracker scores the saved probabilities. It shows correct/missed outcomes, probability assigned to the actual outcome, accuracy, log loss, and multiclass Brier score (sum over the three classes), both overall and by round. The outcome-frequency baseline uses only results available when the forecast was saved. Provider result corrections update evaluation without changing original forecasts.

The existing two-season model is refreshed using newly published Football-Data results and retrained when those results change. Both correct and incorrect examples are used, with unchanged 70/30 seasonal features. FPL result feedback may arrive before Football-Data includes the result; the table distinguishes these states. This is periodic supervised retraining, not automatic discovery of new features or guaranteed improvement. Calibration and controlled model-promotion comparisons remain future work. Existing manual odds behavior is unchanged.

History is stored atomically in `Footballanalyzer-master/data/pl_rounds/history.json`; model snapshots are under `data/pl_rounds/models/`. Preserve this directory and back it up to retain genuine prospective evaluation. It is excluded from Git. A file lock prevents concurrent writers. Failed checks preserve existing history and show an error. Endpoints: `GET /api/pl-rounds` (local report), `POST /api/pl-rounds/sync` (network refresh, evaluation, retraining and prospective prediction).
