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

Replace `python3.10` with your installed compatible Python version if necessary. Dependencies use scikit-learn 1.7.2 to match the bundled legacy model.

The original Serie A dataset and model work without an API key. To enable the new match model and the other leagues on a fresh checkout, import data as described below. Downloaded API data and the generated match model are excluded from Git.

## Import data from API-Football

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

The website displays the actual season and download timestamp. Predictions use historical team statistics, not live data or current line-ups. A recent download date does not mean the underlying season is current.

### Request limits and caching

The integration is designed around the account's **100 requests per day** allowance:

- A full initial import makes up to **30 requests**: five league lookups and 25 season lookups.
- Responses, including season-access errors, are cached locally for **24 hours**.
- Requests are spaced at least **6.1 seconds** apart, with no automatic retries after network or HTTP errors.
- The default per-run limit is **35 requests**. The local daily limit is **80**, with a reserve of 20 requests based on the last known remaining quota.
- The importer reads the provider's remaining-quota header. Requests made through the dashboard or other applications between imports cannot be tracked locally.
- Browsing teams and generating predictions use **zero API-Football requests**.

Updates run manually; no scheduled background import is enabled.

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

A successful import publishes the model and team data together. The running server picks up the new snapshot automatically; refresh the webpage to update its league list and status. If an import fails, the existing model remains active.

## How the model works

The new model is a logistic regression classifier trained on actual **home win / draw / away win** outcomes. Features include league identity, games played, goals scored and conceded, goal difference, points, win/draw rates, and form over the last five matches.

For each training match, team statistics are calculated from earlier matches in the same season. Results become available to subsequent examples only after a conservative four-hour interval from kickoff. At least five completed matches per team are required. Final season tables are not used as inputs for earlier matches.

Evaluation uses a chronological split: approximately the earliest 80% of eligible matches for training and the latest 20% for validation, with a time buffer at the split. Accuracy and log loss are compared against a baseline using training-set outcome frequencies. The published model is then refitted on all eligible matches.

### Latest local validation

The import on **16 October 2026** downloaded **5,341 fixture records** across 15 league-seasons. After excluding play-offs and applying the feature-history requirements:

| Metric | Match model | Outcome-frequency baseline |
| --- | --- | --- |
| Validation accuracy | 51.2% | 40.9% |
| Validation log loss (lower is better) | 1.001 | 1.082 |

The evaluation used **3,672 training matches** and **921 validation matches**. These are historical validation results, not a guarantee of future prediction accuracy. The current metrics are available in the import output and at `/api/catalog`.

Top-scorer and goalkeeper information is not fetched by the new importer, so these fields display a dash. This avoids extra API requests.

### Legacy Serie A data

The original season-strength model remains available as a fallback before match data is imported. Its reversed season labels were corrected to match the source order in the scraping notebook: 2025, 2024, 2023, 2022, and 2021.

The original CSV is preserved as `data/serie_a_full_data.original.csv`. These season tables are not mixed into the new match model's training data.

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
└── Footballanalyzer-master/
    ├── api/                       # FastAPI routes and local model serving
    ├── frontend/                  # HTML, CSS, and JavaScript interface
    ├── ml/                        # Feature generation and match-model training
    ├── data/                      # Legacy data and cached API responses
    ├── models/                    # Legacy model and generated match-model bundle
    ├── tests/                     # Offline tests
    ├── football_config.py         # Supported leagues and local paths
    ├── update_football.py         # Fetch, validate, train, and publish
    ├── train_strength_model.py    # Legacy season-strength training
    ├── requirements.txt
    └── .env.example               # API key configuration template
```
