# Football Analyzer — Plan Forward

Updated: **18 October 2026**  
Status: **Current two-season data refresh and 70/30 seasonal features implemented; calibration and fixture matching pending**

This is our working roadmap for improving predictions across Premier League, La Liga, Serie A, Bundesliga, and Ligue 1. Add ideas, record experiments, and keep unsuccessful results here too. This document does not authorize purchases or scheduled API jobs.

## Recommended direction

First make comparisons reproducible and obtain a route to newer data. Then test **pre-match Elo ratings and recent form** using the data we already have. Compare those improvements with a football score model and a small boosted-tree model. Calibrate and combine models only if chronological evaluation shows a benefit.

Aim for more reliable probabilities, not an arbitrary headline accuracy. No percentage improvement is promised by this plan.

## 1. Starting point

Historical baseline recorded before the current-season update (preserved for reference):

| Item | Current state |
| --- | --- |
| Model | Multiclass logistic regression, standardized inputs, fixed regularization `C=0.1` |
| Target | Home win, draw, away win |
| Coverage | Five leagues; imported seasons 2022/23–2024/25 |
| Latest match in the bundle | 25 May 2025 |
| Data imported | 5,341 fixture records before filtering |
| Evaluation | 3,672 training matches and 921 later validation matches |
| Validation begins | 4 January 2025 |
| Accuracy | 51.25%, versus 40.93% for the outcome-frequency baseline |
| Log loss | 1.0013, versus 1.0817 for the baseline; lower is better |
| Deployment | After evaluation, the model is refitted on all eligible matches |
| API budget | 100 requests/day; importer reserves 20 and caches responses for 24 hours |

### Gaps found in the original implementation

- Team state resets each season. We discard useful previous-season information and cannot predict until both teams have played five games.
- Inputs describe season averages and last-five points, but do not explicitly measure opponent strength, venue-specific form, or rest.
- We use one chronological validation period. Its score has already been inspected, so it is a development benchmark rather than an untouched final test.
- We do not yet report class-by-class performance, calibration curves, uncertainty intervals, or separate league results.
- The website compares teams using their latest stored state. It does not reconstruct statistics for an arbitrary historical kickoff or link a prediction to a scheduled fixture.
- The importer publishes a trained candidate even when it fails to beat the baseline; it only displays a warning. Model promotion needs a separate acceptance step.
- Current-season data remains the main practical limitation. On 16 October 2026, our account explicitly rejected 2025/26 and 2026/27. Repeated requests cannot remove that subscription restriction.

These observations are based on `ml/matches.py`, `api/matches.py`, and `update_football.py` under `Footballanalyzer-master/`. They are reasons to experiment, not evidence that any proposed change will improve results.

## 2. What we can take from the reference video

Reference: [I Trained AI to Predict Sports — Green Code](https://www.youtube.com/watch?v=LkJpNLIaeVk), published 10 March 2025.

The creator's description contains a correction: **the reported 85% accuracy was caused by leaked Elo features**. That score is not a valid benchmark for our project. The page's chapter list covers decision trees, Elo/data collection, random forests, XGBoost, neural networks, and tournament prediction.

Useful experiments to take forward:

| Video topic | Adaptation for our football project |
| --- | --- |
| Elo ratings | Compute each rating using only results available before the predicted match; update it afterward |
| Comparing classifiers | Compare models on identical fixtures, features, and chronological splits |
| Trees and boosting | Test nonlinear interactions between team strengths and form |
| Tournament prediction | Later, simulate seasons from validated match probabilities; keep this separate from model accuracy |

Football also has a draw outcome, so a two-player winner model cannot simply be copied. An Elo expected score is not automatically a three-way home/draw/away probability distribution.

**Review scope:** the video page, chapter list, and creator's correction were inspected. This plan does not claim a full transcript review, code reproduction, or verification of the creator's corrected results.

## 3. Prioritized experiment backlog

Priority: **P0 = foundation**, **P1 = next experiments**, **P2 = later**, **P3 = exploratory**. Effort is a rough relative estimate, not a delivery commitment. API costs are incremental estimates assuming our existing cache remains available.

| ID | Priority | Idea and hypothesis | Data / API cost | Effort | Status |
| --- | --- | --- | --- | --- | --- |
| E01 | P0 | Reproducible, chronological evaluation: distinguish durable improvements from a lucky split | Existing fixtures; 0 calls | Medium | Proposed |
| E02 | P0 | Newer-data feasibility: evaluate on seasons not already used and support current teams | Source investigation; no purchase assumed | Medium | Proposed |
| E03 | P0 | Versioned snapshots and promotion rules: preserve the previous model and its evidence | Local storage; 0 calls | Small–medium | Proposed |
| E04 | P1 | Pre-match Elo: capture opponent-adjusted team strength across seasons | Existing results; 0 calls | Medium | Proposed |
| E05 | P1 | Rolling form and home/away splits: represent recent changes and venue effects | Existing results; 0 calls | Small–medium | Proposed |
| E06 | P1 | Previous-season priors: improve predictions early in a season | Existing history; 0 calls | Medium | Proposed |
| E07 | P1 | Tune the logistic baseline: test regularization and a simpler feature set | Existing features; 0 calls | Small | Proposed |
| E08 | P1 | Poisson, then Dixon–Coles: model scores and low-scoring draws directly | Existing scores; 0 calls | Medium | Proposed |
| E09 | P1 | Gradient boosting: test nonlinear interactions against logistic regression | Existing features; 0 calls | Medium | Proposed |
| E10 | P2 | Probability calibration: make displayed percentages more trustworthy | Held-out chronological predictions; 0 calls | Medium | Proposed |
| E11 | P2 | Ensemble: combine models with complementary errors | Out-of-time predictions; 0 calls | Medium | Proposed |
| E12 | P2 | Rest and congestion: test fatigue-related signals | League-only rest is free; other competitions need additional data | Medium | Proposed |
| E13 | P2 | Shots and expected goals: test whether chance quality adds predictive information | New coverage audit and potentially many requests | Large | Research needed |
| E14 | P3 | Injuries, line-ups and player strength: capture squad changes | Timestamped historical data and additional requests | Large | Deferred |
| E15 | P3 | Neural networks and season simulations | More evidence/data first | Large | Deferred |
| E16 | P1 | User-entered odds assessment: compare the offered price with our independent match probabilities | Manual odds entry; 0 API calls | Medium | Historical simulation implemented; current-fixture assessment pending |

## 4. Evaluation before model complexity

### E01 — Freeze a fair comparison procedure

- Save fixture IDs, source hashes, date filters, feature definitions, model settings, dependency versions, and prediction outputs for each run.
- Define the prediction time: initially a pre-match estimate from already completed games, without live information or confirmed line-ups.
- Use expanding training windows followed by calendar-based validation windows. Football fixtures are unevenly spaced; do not treat a fixed number of rows as a fixed time interval. Keep simultaneous fixtures together. Time-aware validation is supported by [scikit-learn's guidance](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html), but we should construct calendar boundaries explicitly.
- Fit preprocessing, feature selection, model parameters, early stopping, and calibration using only the permitted earlier blocks.
- Keep the existing 921-match block for development comparisons. Reserve a later, newly obtained season as the final test before inspecting its results. Never tune repeatedly against that final block.
- Preserve the current four-hour result-availability margin as a conservative approximation. Add explicit availability timestamps where possible; unusual delays or historical corrections can defeat a kickoff-only rule.

**Leakage checks to add:** changing a match result must not change that match's features; appending future fixtures must not change earlier predictions; Elo updates happen after feature creation; same-day/overlapping fixtures obey the availability cutoff. Historical serving must not use the latest season-end state.

**Report:** log loss as the primary metric; multiclass Brier score with a documented convention; accuracy; confusion matrix and recall for each outcome; classwise reliability diagrams; results by league, season stage, and promoted-team status. Compare against global and league-specific historical-frequency baselines and the unchanged logistic model.

Use paired uncertainty estimates over calendar-week blocks, keeping all leagues' fixtures in each block together. Report sample counts; do not interpret small league-level differences as certain improvements.

### Proposed promotion rule

Agree on the rule before running experiments. As a starting proposal, require lower average walk-forward log loss than the current model, improvement in a majority of windows, no major unexplained league-level regression, and acceptable calibration. Record uncertainty and latency. Treat a tiny or inconsistent gain as inconclusive.

Keep candidate models separate from the active bundle. Save the previous version and report before promotion. A successful training run alone is not an acceptance criterion.

## 5. Highest-value experiments using existing data

### E04 — Elo and seasonal carryover

Maintain a pre-match rating for each club, accounting for opponent strength and home advantage. Start with a simple update rule, then test a small grid for the update rate and partial offseason regression toward the league average. Initialize promoted or unseen clubs conservatively and record uncertainty.

Feed the **pre-match rating difference** into our three-class classifier alongside current features. Test Elo alone, current features alone, and their combination. Tune settings only inside earlier validation windows. Do not insert a rating calculated after the target match.

Football-specific research examines pre-match Elo differences and player ratings as forecasting inputs: [Arntzen and Hvattum, team versus player ratings](https://journals.sagepub.com/doi/abs/10.1177/1471082X20929881). This motivates the experiment; it does not establish a gain for our dataset.

### E05–E07 — Better form, priors, and a stronger baseline

Test one feature group at a time:

- Rolling 5- and 10-match goal difference, points, and goals conceded; compare simple windows with exponentially weighted history.
- Separate home and away performance, shrunk toward overall form when samples are small.
- Previous-season strength blended with current-season evidence. Evaluate early-season coverage separately before removing the five-match minimum.
- A small regularization search for logistic regression. Audit redundant inputs: points per match is determined by win and draw rates, while goal difference per match follows goals for and against.

Report coverage as well as quality. A model that predicts fewer difficult matches must not appear better merely because its test set became easier.

### E08 — Score-based baseline

Start with home/away Poisson goal models using team attack and defense strength plus home advantage. Then test time weighting and the Dixon–Coles adjustment for low-scoring outcomes. Convert score probabilities into home/draw/away probabilities and account for the truncated score-grid tail.

The original [Dixon–Coles paper](https://ajbuckeconbikesail.net/wkpapers/Airports/MVPoisson/soccer_betting.pdf) develops a dynamic football score model based on Poisson regression. It is a relevant statistical comparator, not a guarantee of superior accuracy.

### E09–E11 — Nonlinear models, calibration, and combinations

Try scikit-learn's histogram gradient boosting first because it is already available. Limit tree complexity and search size. Its installed-version documentation supports an explicit validation set; use a later training-era block for early stopping rather than a random internal split. [HistGradientBoostingClassifier 1.7](https://scikit-learn.org/1.7/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html)

If useful, compare a small random forest and XGBoost with three-class probability output. XGBoost's `multi:softprob` objective supplies those probabilities. [XGBoost parameters](https://xgboost.readthedocs.io/en/release_3.0.0/parameter.html)

Check calibration before changing it. Fit any calibrator on predictions from a disjoint, later calibration block, and evaluate on a still-later block. Start with a low-complexity method; data-hungry calibration can overfit. Reliability diagrams complement log loss and Brier score because those scores measure more than calibration alone. [Probability calibration](https://scikit-learn.org/stable/modules/calibration.html)

Only then test a simple weighted average of the best models. Choose weights using out-of-time development predictions, not the final test. Avoid stacking complexity unless the simpler combination fails and there is enough data.

## 6. Newer data and the API budget

### E02 — Investigate a second source before paying for more calls

[Football-Data's download catalog](https://football-data.co.uk/downloadm.php) lists historical CSV archives and 2025/26 and 2026/27 seasons. This is a promising candidate for filling our freshness gap without consuming API-Football calls. It is now integrated for the five leagues through `current_data.py`; API-Football records are not mixed into these snapshots. Cross-provider reconciliation remains future work.

Before importing: inspect actual coverage for all five leagues, permitted use, field definitions, missing timestamps, team-name mappings, and duplicate fixtures. Match overlapping seasons against API-Football and retain source provenance. The provider also notes a historical definition change in Serie A shots data; do not merge statistics blindly. [Italy data notes](https://football-data.co.uk/italym.php)

If exact kickoff times are absent, use conservative date-based feature cutoffs and do not claim minute-level historical availability. Keep odds optional and separate: closing odds are not valid inputs for a prediction made before they existed. An odds-derived probability benchmark, if added later, must use the same prediction horizon.

A paid API plan is another option, but only after checking season access and a concrete benefit. No subscription change is part of this plan.

### Spend quota on new information

| Proposed action | Approximate API-Football cost | Policy |
| --- | --- | --- |
| Elo/form/model experiments on cached fixtures | 0 | Do these first |
| Refresh one accessible season across five leagues | About 5 fixture calls, plus metadata if needed | Only when the season can contain changes |
| Refresh all three archived seasons across five leagues | About 15 fixture calls, plus metadata | Avoid daily repetition; retain archival snapshots |
| Retrieve per-fixture statistics for one 380-match season | Roughly 380 calls if one request per fixture | Pilot before attempting a full backfill |
| Repeat requests for a season the plan rejects | No new data | Remember the restriction; recheck infrequently |

API-Football documents full-season fixture retrieval and separate match-statistics endpoints in its [official guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide). Exact costs depend on endpoint responses and access.

Proposed next importer design: archive completed-season responses, refresh active seasons selectively, keep a small correction/reconciliation process, and separate offline training from network updates. Keep the existing 20-request reserve and manual update policy until we choose a schedule.

### E12–E14 — Richer features need coverage checks

League fixtures can give time since the previous **league** match, but that is not true rest when a club played in Europe or a cup. Label this limitation or obtain all relevant competitions.

For shots/xG, first audit a small, explicitly budgeted sample for availability, consistency, and season coverage. Use only earlier matches' values as predictors. Missing xG must remain missing, not become zero.

[StatsBomb Open Data](https://github.com/hudl/open-data) is another source to investigate for event-level experiments. Its selected competition/season coverage and attribution requirements must be checked; it is not assumed to cover all five leagues continuously.

Defer injuries and line-ups until historical availability at prediction time can be reconstructed. Today's injury information cannot be pasted into a historical backtest.

## Planned product feature — E16: Compare bookmaker odds with our prediction

**User requirement:** the application should accept odds for a selected team to win and assess whether the offered price represents potential betting value according to the model's own match prediction. A first version now supports manual decimal odds and historical simulation calculations. It does not provide current-bet recommendations. Fixture matching, quote timestamps, and calibrated decision thresholds remain pending.

### Input and workflow

1. Select the league, home team, away team, and a specific fixture/kickoff.
2. Select the outcome being priced: home win, draw, or away win. Initially support only the standard 90-minute three-way market, including stoppage time and excluding extra time and penalties.
3. Enter **decimal odds** for that outcome. Accept only finite numbers greater than 1. Optionally enter all three prices from the same bookmaker/market and record the quote time.
4. Generate the model's probabilities independently of the entered odds. Changing the price must change the value assessment, not the model's prediction of the match.
5. Show the offered odds, model probability, break-even probability, model-implied fair odds, estimated edge, estimated expected return, and a short assessment with reasons.

Manual input requires no API-Football requests. Automatic odds retrieval is a separate future decision.

### Calculations

For decimal odds `d` and the model probability `p` of the selected outcome:

- **Break-even probability:** `1 / d`.
- **Model-implied fair odds:** `1 / p`; show an explicit unavailable/infinite state when `p = 0`.
- **Probability edge:** `p - 1 / d`, displayed in percentage points.
- **Expected net return per unit staked:** `p * d - 1`, assuming a standard win/lose bet with no fees or taxes. This is a model estimate, not realized profit.

Synthetic illustration only: if `p = 0.50` and offered odds are `2.20`, break-even probability is about `45.45%`, fair odds are `2.00`, edge is about `4.55` percentage points, and estimated net return is `0.10` per unit staked. A positive estimate still allows the entire stake to be lost on that match.

A single price is sufficient to calculate break-even probability and expected return. It is **not** sufficient to estimate the bookmaker's total margin. If all three prices are supplied, show their implied-probability sum and optionally a proportional margin-adjusted comparison: `(1 / d_i) / sum(1 / d_j)`. Label this as an approximation. Use the actual offered price, not the normalized probability, for expected-return calculations.

### Assessment and limits

Use clear states such as **Potential value**, **No positive estimated value**, and **Insufficient evidence**. A positive point estimate alone should not automatically trigger a favorable assessment: define and validate an uncertainty/edge buffer using development data before release. Keep its value configurable and document how it was chosen; do not invent a universal threshold.

Require compatible fixture, market, quote time, adequate team history, and sufficiently fresh data. Until newer data and fixture-aware serving exist, offer only clearly marked historical/simulation comparisons; do not use 2024/25 team statistics to endorse a current-season bet. Where calibration or data quality is inadequate, return insufficient evidence and explain why.

The output assesses **estimated price value**, not whether gambling is personally affordable or responsible for a user. Do not label a bet safe, guaranteed, or risk-free. Stake sizing, deposits, bookmaker links, and automated bet placement are outside this feature's scope.

### Dependencies and acceptance checks

- E01: chronological evaluation and leakage checks.
- E02 and fixture-aware serving: current data for current fixtures.
- E10: calibration assessment; apply recalibration only if it improves held-out results.
- Test home/draw/away mapping, invalid odds, zero-probability handling, positive/zero/negative expected return, percentage-point formatting, and incomplete three-price input.
- Verify that editing odds never changes model probabilities and that stale, mismatched, or unsupported markets cannot receive a favorable assessment.
- Backtest using predictions and odds genuinely available at the same pre-match time. Evaluate probability quality and realized fixed-unit returns with sample sizes and uncertainty. Include all qualifying selections under a rule fixed before the test, rather than selecting profitable examples afterward.
- Record results as E16 in the experiment log. Historical returns are evidence to evaluate, not a promise of future profit.

## 7. Suggested delivery sequence

| Stage | Work | Reviewable output / exit condition |
| --- | --- | --- |
| A — Establish trust | E01, E03; investigate E02 | Reproducible baseline report, leakage checks, candidate/promotion separation, source feasibility decision |
| B — Improve the inputs | E04–E07 | Ablation table on identical fixtures; one preferred feature set or documented no-gain result |
| C — Compare model families | E08–E09 | Logistic, Elo-enhanced, score-based, and boosted-tree models evaluated on the same windows |
| D — Improve probabilities | E10–E11 | Reliability plots and ensemble comparison; approve only a measured gain |
| E — Make it current | Validated E02 source and fixture/date-aware serving | Predictions tied to an actual fixture, kickoff, source age, and model version |
| E2 — Assess offered odds | E16 after evaluation, freshness, and calibration checks | Manual odds comparison with transparent calculations, uncertainty, and insufficient-evidence handling |
| F — Expand selectively | E12–E15 | Small pilots with measured benefit per data/API cost |

Data-source investigation can proceed alongside Stage A. Do not postpone fixing the freshness gap until after every modeling experiment.

**Recommended first implementation request:** establish the frozen chronological benchmark and experiment log, then add pre-match Elo as one isolated experiment. This can be done using existing cached data and zero additional API calls.

## 8. Plots and review artifacts to produce later

No new performance plots have been generated for this planning task.

- Log loss by validation window and by league, with the current model as a reference.
- Classwise calibration curves and probability-bin sample counts.
- Confusion matrix, especially draw performance.
- Ablation chart: baseline → Elo → rolling form → venue splits → seasonal priors.
- Accuracy/log loss versus training-history length.
- Coverage and error by games played, including promoted clubs.
- Data freshness and missing-feature coverage by league/season.
- E16: model versus break-even probabilities, and estimated versus realized returns by predeclared edge band with sample counts.

## 9. Living experiment log

Keep the baseline row fixed. Add one row for every attempted experiment, including rejected ideas. Do not overwrite unsuccessful results.

| Run | Date | Idea | Dataset / cutoff | Model + features | Log loss | Accuracy | League/coverage notes | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B00 | 2026-10-16 | Current baseline | 2022–2024 starting years; validation from 2025-01-04 | Existing logistic model | 1.0013 | 51.25% | 921 validation matches; five leagues | Reference only |
| — | — | E04: pre-match Elo | To define in E01 | Not run | — | — | — | Proposed |
| — | — | E16: user-entered odds | Timestamp-matched fixtures and odds required | Not run | — | — | No current-season endorsement with stale data | Requested; planned |

### New idea template

- **ID / title:**
- **Status:** Proposed / Ready / Running / Accepted / Rejected / Deferred
- **Owner and date:**
- **Hypothesis:** What should improve, and why?
- **Source or observation:**
- **Data needed / availability at prediction time:**
- **API cost / storage / dependencies:**
- **Smallest useful experiment:**
- **Comparison model and fixed fixtures:**
- **Primary metric and acceptance rule:**
- **Leakage and missing-data checks:**
- **Results / uncertainty / artifact links:**
- **Decision and next step:**

### Open decisions

- Is the next milestone better historical predictions, or predictions for upcoming fixtures? Both matter, but current fixtures require newer data.
- Should the default prediction horizon be the day before kickoff or shortly before kickoff?
- Is a second data provider acceptable, with API-Football retained for identifiers and optional enrichment?
- After evidence accumulates, should we keep one pooled model or use league-specific calibration/models?
- When should a candidate replace the active model, and who reviews the report?

Model experiments remain proposals unless marked otherwise. E16 now has a historical-simulation implementation; current-fixture assessment and its validation remain pending. The odds feature does not retrain or replace the match model.


## Implemented: current two-season predictions

The user requested current division teams, current plus previous season, refreshed results before prediction, and more weight on current statistics. Football-Data now supplies the active model because API-Football again denied season 2026 on the free account. Current-season files refresh on league selection and before every prediction; completed previous-season files are retained. Failed refreshes block predictions. The old API bundle is preserved separately.

Features blend season rates and last-five form 70/30. This is a transparent initial policy, not a tuned optimum. Each eligible training match retains equal sample weight. Five total games are required; promoted teams without prior top-division history must accumulate five current-season games. Only the two requested seasons enter training. CSV results use a conservative next-day 04:00 UTC availability rule. Full current-season club counts are checked before publication; early-season incomplete membership is reported as unavailable.

Initial five-league validation: 1,393 training matches, 349 validation matches from 11 May 2026; accuracy 46.70%, log loss 1.0452 versus outcome-frequency baseline 43.84% and 1.0716. These are development metrics on a different fixture set from B00, not evidence of an improvement over B00. Same-fixture ablations of 70/30 versus current-only features, calibration and league breakdowns remain planned. Published-source freshness is shown separately from the time of the request; a same-day query cannot guarantee same-day results.
