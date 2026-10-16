
let API_BASE_URL = '/api';
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
      option.textContent = entry.name + (entry.ready ? '' : entry.id === 135 ? ' — original dataset' : ' — awaiting import');
      option.disabled = !entry.ready && entry.id !== 135;
      leagueSelect.append(option);
    }
    leagueSelect.value = '135';
    await changeLeague();
  } catch (error) {
    dataStatus.textContent = error.message;
  }
}

async function changeLeague() {
  selectionVersion++;
  league = Number(leagueSelect.value);
  const entry = catalog.leagues.find(item => item.id === league);
  API_BASE_URL = entry.ready ? '/api/football' : '/api';
  for (const controller of Object.values(controllers)) controller?.abort();
  teamStatsCache.clear();
  homeTeamSelect.replaceChildren();
  awayTeamSelect.replaceChildren();
  clearStatsDisplay('home');
  clearStatsDisplay('away');
  predictBtn.disabled = true;
  predictionResult.textContent = 'Select both teams to see prediction';
  if (entry.ready) {
    const source = catalog.sources.find(s => s.league === league && s.season === entry.season);
    dataStatus.textContent = `${entry.season}/${entry.season + 1} · Downloaded ${new Date(source.fetched_at * 1000).toLocaleString()} · Historical estimate, not live data.`;
    if (catalog.metrics.log_loss >= catalog.metrics.baseline_log_loss) {
      dataStatus.textContent += ' Validation: this model did not outperform the simple baseline.';
    }
  } else {
    dataStatus.textContent = 'Original Serie A data, season 2025/2026. API-Football import and new match model are not active yet.';
  }
  await loadTeams();
}
leagueSelect.addEventListener('change', changeLeague);


const homeTeamSelect = document.getElementById('home-team');
const awayTeamSelect = document.getElementById('away-team');
const predictionResult = document.getElementById('prediction-result');
const predictBtn = document.getElementById('predict-btn');


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
  const version = selectionVersion;
  try {
    const res = await fetch(apiUrl('/teams'));
    if (!res.ok) throw new Error(`Failed to load teams (${res.status})`);
    const data = await res.json();
    if (version !== selectionVersion) return;
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
    alert('Failed to load teams.');
  }
}

//  LOAD STATS 
async function loadTeamStats(team, prefix) {
  const version = selectionVersion;
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
      throw new Error(body?.detail || `HTTP ${res.status}`);
    }
    const stats = await res.json();
    if (version !== selectionVersion || (prefix === 'home' ? homeTeamSelect : awayTeamSelect).value !== team) return;
    teamStatsCache.set(team, stats);
    updateStatsDisplay(stats, prefix);
    return stats;
  } catch (err) {
    if (version === selectionVersion && err.name !== 'AbortError') {
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

    predictBtn.disabled = true;
    predictBtn.textContent = 'Predicting...';

    const res = await fetch(apiUrl('/compare'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ home_team: homeTeam, away_team: awayTeam, league })
    });

    if (!res.ok) {
      const body = await safeJson(res);
      throw new Error(body?.detail || `HTTP ${res.status}`);
    }

    const result = await res.json();
    if (version !== selectionVersion) return;
    const homeProb = (result.home_win * 100).toFixed(1);
    const drawProb = (result.draw * 100).toFixed(1);
    const awayProb = (result.away_win * 100).toFixed(1);

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
    updatePredictBtnState();
    predictBtn.textContent = 'Predict';
  }
}

//  ENABLE/DISABLE BUTTON 
function updatePredictBtnState() {
  const home = homeTeamSelect.value;
  const away = awayTeamSelect.value;
  predictBtn.disabled = !(home && away && home !== away);
}

//  EVENT
homeTeamSelect.addEventListener('change', async (e) => {
  const t = e.target.value;
  if (t) await loadTeamStats(t, 'home'); else clearStatsDisplay('home');
  updatePredictBtnState();
});

awayTeamSelect.addEventListener('change', async (e) => {
  const t = e.target.value;
  if (t) await loadTeamStats(t, 'away'); else clearStatsDisplay('away');
  updatePredictBtnState();
});

predictBtn.addEventListener('click', compareTeams);

//  INIT 
initialize();
