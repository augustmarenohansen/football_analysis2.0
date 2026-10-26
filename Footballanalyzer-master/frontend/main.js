
const API_BASE_URL = '/api/football';
let league = 135;
let selectionVersion = 0;
const leagueSelect = document.getElementById('league-select');
const dataStatus = document.getElementById('data-status');
let catalog;
const apiUrl = path => `${API_BASE_URL}${path}?league=${league}`;

async function initialize() {
  try {
    const response = await fetch('/api/catalog');
    if (!response.ok) throw new Error('Cannot load league status');
    catalog = await response.json();
    leagueSelect.replaceChildren();
    for (const entry of catalog.leagues) {
      const option = document.createElement('option');
      option.value = entry.id;
      option.textContent = entry.name + (entry.ready ? '' : ' — load current data');
      option.disabled = !entry.available;
      leagueSelect.append(option);
    }
    const available = catalog.leagues.filter(entry => entry.available);
    if (!available.length) {
      leagueSelect.disabled = true;
      dataStatus.textContent = 'No match data yet. Import data using the setup instructions in README.md, then refresh this page.';
      return;
    }
    leagueSelect.value = String(available.find(entry => entry.id === 135)?.id ?? available[0].id);
    await changeLeague();
  } catch (error) {
    dataStatus.textContent = error.message;
  }
}


function showDataStatus(data) {
  dataStatus.textContent = `${data.season}/${data.season + 1} (70%) + ${data.previous_season}/${data.previous_season + 1} (30%) · Checked ${new Date(data.checked_at * 1000).toLocaleString()} · Latest result: ${data.last_result} · ${data.provider}. Published results may lag behind today's matches. Teams without previous-season data use current-season history only.`;
  if (data.metrics.log_loss >= data.metrics.baseline_log_loss) {
    dataStatus.textContent += ' Validation: this model did not outperform the simple baseline.';
  }
}

async function changeLeague() {
  invalidatePrediction();
  league = Number(leagueSelect.value);
  const entry = catalog.leagues.find(item => item.id === league);
  for (const controller of Object.values(controllers)) controller?.abort();
  teamStatsCache.clear();
  homeTeamSelect.replaceChildren();
  awayTeamSelect.replaceChildren();
  clearStatsDisplay('home');
  clearStatsDisplay('away');
  predictBtn.disabled = true;
  predictionResult.textContent = 'Select both teams to see prediction';
  dataStatus.textContent = 'Checking current division teams and published results…';
  await loadTeams();
}
leagueSelect.addEventListener('change', changeLeague);


const homeTeamSelect = document.getElementById('home-team');
const awayTeamSelect = document.getElementById('away-team');
const predictionResult = document.getElementById('prediction-result');
const predictBtn = document.getElementById('predict-btn');
const oddsInput = document.getElementById('decimal-odds');
const oddsOutcome = document.getElementById('odds-outcome');
const oddsResult = document.getElementById('odds-result');
let predicting = false;

function invalidatePrediction() {
  oddsInput.setCustomValidity('');
  selectionVersion++;
  predicting = false;
  predictBtn.textContent = 'Predict';
  predictionResult.textContent = 'Select both teams and press Predict';
  oddsResult.replaceChildren();
  oddsResult.hidden = true;
  updatePredictBtnState();
}

function renderOdds(assessment) {
  oddsResult.replaceChildren();
  oddsResult.hidden = false;
  const title = document.createElement('h3');
  title.textContent = 'Odds comparison · Simulation';
  oddsResult.append(title);
  const pct = value => `${(value * 100).toFixed(2)}%`;
  const selected = assessment.outcome === 'home' ? `${homeTeamSelect.value} to win` :
    assessment.outcome === 'away' ? `${awayTeamSelect.value} to win` : 'Draw';
  const rows = [
    ['Outcome', selected],
    ['Data season', `${assessment.season}/${assessment.season + 1}`],
    ['Offered decimal odds', String(assessment.decimal_odds)],
    ['Model probability', pct(assessment.model_probability)],
    ['Break-even probability', pct(assessment.break_even_probability)],
    ['Model fair odds', assessment.fair_odds === null ? 'Infinite (zero model probability)' : assessment.fair_odds.toFixed(2)],
    ['Estimated edge', `${assessment.edge_percentage_points.toFixed(2)} percentage points`],
    ['Expected net return per 1 unit', assessment.expected_net_return_per_unit.toFixed(3)],
    ['Estimated return', pct(assessment.expected_net_return_per_unit)],
  ];
  const list = document.createElement('dl');
  for (const [label, value] of rows) {
    const term = document.createElement('dt');
    const detail = document.createElement('dd');
    term.textContent = label;
    detail.textContent = value;
    list.append(term, detail);
  }
  oddsResult.append(list);
  for (const message of [
    `Simulation: ${{positive: 'positive estimated value', negative: 'no positive estimated value', break_even: 'break-even'}[assessment.simulation_result]}.`,
    'Current bet assessment: insufficient evidence.',
    assessment.reason,
    assessment.assumptions,
    'Estimated value is not guaranteed profit or a judgment of personal affordability. A losing bet loses the full stake.',
  ]) {
    const paragraph = document.createElement('p');
    paragraph.textContent = message;
    oddsResult.append(paragraph);
  }
}

oddsInput.addEventListener('input', invalidatePrediction);
oddsOutcome.addEventListener('change', invalidatePrediction);


const teamStatsCache = new Map();
const controllers = { home: null, away: null };
async function safeJson(res) {
  try { return await res.json(); } catch { return null; }
}
function prettyLabel(v) {
  return String(v).replace(/\u00a0/g, ' ').trim();
}

// LOAD TEAMS
async function loadTeams() {
  const requestedLeague = league;
  const requestedSelection = selectionVersion;
  try {
    const res = await fetch(apiUrl('/teams'));
    if (!res.ok) {
      const body = await safeJson(res);
      throw new Error(body?.detail || `Failed to load teams (${res.status})`);
    }
    const data = await res.json();
    if (requestedLeague !== league || requestedSelection !== selectionVersion) return;
    showDataStatus(data.data);
    const teams = Array.isArray(data) ? data : data?.teams;
    if (!Array.isArray(teams)) throw new Error('Invalid teams data format');

    homeTeamSelect.innerHTML = '<option value="">Select home team...</option>';
    awayTeamSelect.innerHTML = '<option value="">Select away team...</option>';

    teams.forEach(team => {
      const optionHome = document.createElement('option');
      optionHome.value = team;
      optionHome.textContent = prettyLabel(team);
      homeTeamSelect.appendChild(optionHome);

      const optionAway = document.createElement('option');
      optionAway.value = team;
      optionAway.textContent = prettyLabel(team);
      awayTeamSelect.appendChild(optionAway);
    });
  } catch (error) {
    console.error('Error loading teams:', error);
    if (requestedLeague === league && requestedSelection === selectionVersion) dataStatus.textContent = error.message;
  }
}

//  LOAD STATS 
async function loadTeamStats(team, prefix) {
  const statsLeague = league;
  try {
    if (teamStatsCache.has(team)) {
      updateStatsDisplay(teamStatsCache.get(team), prefix);
      return teamStatsCache.get(team);
    }
    if (controllers[prefix]) controllers[prefix].abort();
    controllers[prefix] = new AbortController();

    const res = await fetch(apiUrl(`/team/${encodeURIComponent(team)}`), {
      signal: controllers[prefix].signal
    });
    if (!res.ok) {
      const body = await safeJson(res);
      throw new Error(typeof body?.detail === 'string' ? body.detail : `Invalid request (${res.status})`);
    }
    const stats = await res.json();
    if (statsLeague !== league || (prefix === 'home' ? homeTeamSelect : awayTeamSelect).value !== team) return;
    teamStatsCache.set(team, stats);
    updateStatsDisplay(stats, prefix);
    return stats;
  } catch (err) {
    if (statsLeague === league && err.name !== 'AbortError') {
      console.error(`Failed to load ${team} stats:`, err);
      clearStatsDisplay(prefix);
    }
  } finally {
    controllers[prefix] = null;
  }
}

//  UPDATE DISPLAY
function updateStatsDisplay(stats, prefix) {
  ['mp', 'w', 'd', 'l', 'gf', 'ga', 'gd'].forEach(k => {
    const el = document.getElementById(`${prefix}_${k}`);
    if (el) el.textContent = stats[k] ?? '-';
  });
  document.getElementById(`${prefix}_last_5`).textContent = stats.last_5 ?? '-';
  document.getElementById(`${prefix}_top_scorer`).textContent = stats.top_scorer ?? '-';
  document.getElementById(`${prefix}_goalkeeper`).textContent = stats.goalkeeper ?? '-';
}
function clearStatsDisplay(prefix) {
  ['mp','w','d','l','gf','ga','gd','last_5','top_scorer','goalkeeper']
    .forEach(k => {
      const el = document.getElementById(`${prefix}_${k}`);
      if (el) el.textContent = '-';
    });
}

//  PREDICT 
async function compareTeams() {
  const version = selectionVersion;
  try {
    const homeTeam = homeTeamSelect.value;
    const awayTeam = awayTeamSelect.value;

    if (!homeTeam || !awayTeam) {
      predictionResult.innerHTML = '<p>Select both teams first</p>';
      return;
    }
    if (homeTeam === awayTeam) {
      predictionResult.innerHTML = '<p>Pick two different teams.</p>';
      return;
    }

    let odds;
    if (oddsInput.value !== '' || oddsInput.validity.badInput) {
      if (!oddsInput.reportValidity()) return;
      const decimal = Number(oddsInput.value);
      if (!Number.isFinite(decimal) || decimal <= 1) {
        oddsInput.setCustomValidity('Enter valid decimal odds greater than 1.');
        oddsInput.reportValidity();
        return;
      }
      odds = { outcome: oddsOutcome.value, decimal };
    }
    predicting = true;
    predictBtn.disabled = true;
    predictBtn.textContent = 'Updating data and predicting…';
    predictionResult.textContent = 'Checking the latest published results…';
    oddsResult.hidden = true;

    const res = await fetch(apiUrl('/compare'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ home_team: homeTeam, away_team: awayTeam, league, odds })
    });

    if (!res.ok) {
      const body = await safeJson(res);
      throw new Error(typeof body?.detail === 'string' ? body.detail : `Invalid request (${res.status})`);
    }

    const result = await res.json();
    if (version !== selectionVersion) return;
    showDataStatus(result.data);
    teamStatsCache.clear();
    updateStatsDisplay(result.team_stats.home, 'home');
    updateStatsDisplay(result.team_stats.away, 'away');
    const homeProb = (result.home_win * 100).toFixed(1);
    const drawProb = (result.draw * 100).toFixed(1);
    const awayProb = (result.away_win * 100).toFixed(1);

    if (result.odds_assessment) renderOdds(result.odds_assessment);
    predictionResult.innerHTML = `
      <p><strong>Model:</strong> ${result.details.model}</p>
      <h3>${result.prediction}</h3>
      <p class="home-win">Home Win: ${homeProb}%</p>
      <p class="draw">Draw: ${drawProb}%</p>
      <p class="away-win">Away Win: ${awayProb}%</p>
      <hr>
      <div class="prediction-details">
        <h4>Home Team Form</h4>
        <p>Win Rate: ${result.details.home_team.form.win_ratio}%</p>
        <p>Goals/Game: ${result.details.home_team.form.goals_per_game}</p>
        <p>Defense Rating: ${result.details.home_team.form.defense_rating}</p>

        <h4>Away Team Form</h4>
        <p>Win Rate: ${result.details.away_team.form.win_ratio}%</p>
        <p>Goals/Game: ${result.details.away_team.form.goals_per_game}</p>
        <p>Defense Rating: ${result.details.away_team.form.defense_rating}</p>
      </div>
    `;
  } catch (err) {
    console.error('Prediction error:', err);
    if (version === selectionVersion) predictionResult.textContent = `Error: ${err.message}`;
  } finally {
    if (version === selectionVersion) {
      predicting = false;
      updatePredictBtnState();
      predictBtn.textContent = 'Predict';
    }
  }
}

//  ENABLE/DISABLE BUTTON 
function updatePredictBtnState() {
  const home = homeTeamSelect.value;
  const away = awayTeamSelect.value;
  predictBtn.disabled = predicting || !(home && away && home !== away);
}

//  EVENT
homeTeamSelect.addEventListener('change', async (e) => {
  invalidatePrediction();
  const t = e.target.value;
  if (t) await loadTeamStats(t, 'home'); else clearStatsDisplay('home');
  updatePredictBtnState();
});

awayTeamSelect.addEventListener('change', async (e) => {
  invalidatePrediction();
  const t = e.target.value;
  if (t) await loadTeamStats(t, 'away'); else clearStatsDisplay('away');
  updatePredictBtnState();
});

predictBtn.addEventListener('click', compareTeams);

//  INIT 
initialize();
