const statusText = document.getElementById('round-status');
const selector = document.getElementById('round-select');
const button = document.getElementById('sync-rounds');
let report;
let busy = false;
let ntQuotes = new Map();
let ntRound = '';
let roundSkips = new Map();
const pct = n => `${(n * 100).toFixed(1)}%`;
const date = value => value ? new Date(value).toLocaleString() : 'Not yet';
const label = value => ({ home: 'Home win', draw: 'Draw', away: 'Away win' }[value]);

function summary(metrics) {
  if (!metrics.count) return 'No completed matches with saved pre-match forecasts yet.';
  return `${metrics.count} evaluated · Accuracy ${pct(metrics.accuracy)} · Log loss ${metrics.log_loss.toFixed(3)} · Brier ${metrics.brier.toFixed(3)} · Baseline log loss ${metrics.baseline_log_loss.toFixed(3)}`;
}

function moneySummary(s) {
  return `${s.settled} settled, ${s.pending} pending · Settled stake ${s.stake.toFixed(2)} kr · Payout ${s.payout.toFixed(2)} kr · Net ${s.net.toFixed(2)} kr · Pending stake ${s.pending_stake.toFixed(2)} kr${s.invalid ? ` · ${s.invalid} invalid` : ''}`;
}

function updateOverview() {
  document.getElementById('overview-count').textContent = report.metrics.count;
  document.getElementById('overview-accuracy').textContent = report.metrics.count ? pct(report.metrics.accuracy) : '—';
  const simulation = report.simulation;
  document.getElementById('overview-net').textContent = simulation.settled
    ? `${simulation.net > 0 ? '+' : ''}${simulation.net.toFixed(2)} kr` : '—';
}

async function submitSimulation(event, match) {
  event.preventDefault();
  if (busy) return;
  busy = true;
  const form = event.currentTarget;
  const submit = form.querySelector('button');
  const message = form.querySelector('[role=status]');
  submit.disabled = true;
  message.textContent = 'Checking current fixtures and data…';
  try {
    const body = {fixture_id: match.id};
    for (const outcome of ['home', 'draw', 'away']) body[outcome] = Number(form.elements[outcome].value);
    const response = await fetch('/api/pl-rounds/simulate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Check all three odds.');
    report = data;
    updateOverview();
    document.getElementById('simulation-total').textContent = moneySummary(report.simulation);
    renderRound();
  } catch (error) {
    message.textContent = error.message;
    submit.disabled = false;
  } finally {
    busy = false;
  }
}

function renderRound() {
  const rows = document.getElementById('round-matches');
  const drafts = new Map(Array.from(rows.querySelectorAll('form[data-fixture]'), form =>
    [form.dataset.fixture, Object.fromEntries(['home', 'draw', 'away'].map(outcome =>
      [outcome, {value: form.elements[outcome].value, prefilled: form.elements[outcome].dataset.prefilled}]))]));
  rows.replaceChildren();
  const chosen = report.rounds.find(r => `${r.season}:${r.round}` === selector.value);
  document.getElementById('selected-metrics').textContent = chosen ? summary(chosen) : '';
  const totals = chosen?.simulation;
  document.getElementById('round-stake').textContent = totals ? `${totals.stake.toFixed(2)} kr` : '—';
  document.getElementById('round-payout').textContent = totals?.settled ? `${totals.payout.toFixed(2)} kr` : '—';
  document.getElementById('round-net').textContent = totals?.settled ? `${totals.net > 0 ? '+' : ''}${totals.net.toFixed(2)} kr` : '—';
  document.getElementById('selected-simulation').textContent = totals
    ? `${totals.settled} settled · ${totals.pending} pending (${totals.pending_stake.toFixed(2)} kr)${totals.invalid ? ` · ${totals.invalid} invalid` : ''}`
    : 'Select a round to see its simulations.';
  for (const match of report.records.filter(r => `${r.season}:${r.round}` === selector.value)) {
    const f = match.forecast;
    const nt = ntRound === selector.value ? ntQuotes.get(match.id) : null;
    let feedback = match.reason || 'Waiting for final result';
    let outcomeStatus = null;
    if (f && match.result && match.eligible) {
      outcomeStatus = f.pick === match.result ? 'Correct' : 'Missed';
      feedback = `Actual outcome: ${label(match.result)} (${pct(f.probabilities[match.result])} predicted). ${match.included_in_training ? 'Included in latest training data.' : 'Waiting for training results source.'}`;
    }
    const values = [
      `${nt?.home || match.simulation?.source_home || match.home} – ${nt?.away || match.simulation?.source_away || match.away}\n${date(match.kickoff)}`,
      f ? ['home', 'draw', 'away'].map(k => pct(f.probabilities[k])).join(' / ') : 'No saved forecast',
      f ? `${label(f.pick)}\nSaved ${date(f.created_at)}\nModel ${f.model_id}\nResults through ${f.last_result}` : '—',
      match.result ? `${match.score[0]}–${match.score[1]} (${label(match.result)})` : 'Pending',
    ];
    const row = document.createElement('tr');
    for (const value of values) {
      const cell = document.createElement('td');
      cell.textContent = value;
      cell.style.whiteSpace = 'pre-line';
      row.append(cell);
    }
    const feedbackCell = document.createElement('td');
    if (outcomeStatus) {
      const badge = document.createElement('span');
      badge.className = `result-badge ${outcomeStatus === 'Correct' ? 'result-correct' : 'result-missed'}`;
      badge.textContent = outcomeStatus;
      feedbackCell.append(badge);
    }
    const feedbackText = document.createElement('p');
    feedbackText.className = 'feedback-text';
    feedbackText.textContent = feedback;
    feedbackCell.append(feedbackText);
    row.append(feedbackCell);
    const simulationCell = document.createElement('td');
    const simulation = match.simulation;
    if (simulation) {
      const result = match.simulation_result;
      simulationCell.textContent = `${label(simulation.pick)} @ ${simulation.odds[simulation.pick]} · 10 kr\nModel: ${['home', 'draw', 'away'].map(k => pct(simulation.probabilities[k])).join(' / ')}\nOdds: ${simulation.quote_source} · Checked ${date(simulation.quoted_at)}\nPrediction ${date(simulation.created_at)}\n${result.status === 'settled' ? `${result.payout > 0 ? 'Won' : 'Lost'} · Payout ${result.payout.toFixed(2)} kr · Net ${result.net > 0 ? '+' : ''}${result.net.toFixed(2)} kr` : result.status === 'pending' ? 'Pending' : 'Invalid after kickoff change'}`;
      simulationCell.style.whiteSpace = 'pre-line';
    } else if (match.kickoff && new Date(match.kickoff) > new Date() && !match.started) {
      const form = document.createElement('form');
      form.dataset.fixture = match.id;
      for (const outcome of ['home', 'draw', 'away']) {
        const fieldLabel = document.createElement('label');
        fieldLabel.textContent = `${label(outcome)} odds `;
        const field = document.createElement('input');
        field.type = 'number'; field.name = outcome; field.min = '1.01'; field.max = '10000';
        field.step = 'any'; field.required = true; field.style.width = '5em';
        const draft = drafts.get(match.id)?.[outcome];
        if (draft?.value && draft.value !== draft.prefilled) field.value = draft.value;
        else if (nt) { field.value = nt.odds[outcome]; field.dataset.prefilled = field.value; }
        fieldLabel.append(field); form.append(fieldLabel, document.createElement('br'));
      }
      const submit = document.createElement('button');
      submit.type = 'submit'; submit.textContent = 'Simulate 10 kr';
      const message = document.createElement('p'); message.setAttribute('role', 'status');
      if (roundSkips.has(match.id)) message.textContent = roundSkips.get(match.id);
      form.append(submit, message);
      form.addEventListener('submit', event => submitSimulation(event, match));
      simulationCell.append(form);
    } else simulationCell.textContent = roundSkips.get(match.id) || 'No pre-match simulation';
    row.append(simulationCell);
    rows.append(row);
  }
}

async function predictRound() {
  if (busy || !selector.value) return;
  const requestedRound = selector.value;
  const [season, round] = requestedRound.split(':').map(Number);
  const btn = document.getElementById('predict-round');
  const status = document.getElementById('predict-round-status');
  busy = true; btn.disabled = true;
  status.textContent = 'Refreshing fixtures, results and odds before predicting…';
  try {
    const response = await fetch('/api/pl-rounds/predict-round', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({season, round})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not predict this round.');
    report = result.report;
    updateOverview();
    document.getElementById('simulation-total').textContent = moneySummary(report.simulation);
    if (selector.value === requestedRound) {
      roundSkips = new Map(result.skipped.map(item => [item.fixture_id, item.reason]));
      ntRound = requestedRound;
      ntQuotes = new Map(result.quotes.map(quote => [quote.fixture_id, quote]));
      status.textContent = `${result.created} new simulations saved · ${result.skipped.length} fixtures skipped or already saved. No real bets placed.`;
    }
    renderRound();
  } catch (error) {
    if (selector.value === requestedRound) status.textContent = error.message;
  } finally {
    busy = false; btn.disabled = false;
  }
}

async function loadNorskTipping() {
  if (busy || !selector.value) return;
  const requestedRound = selector.value;
  const [season, round] = requestedRound.split(':');
  const btn = document.getElementById('load-nt-odds');
  const status = document.getElementById('nt-status');
  busy = true; btn.disabled = true;
  status.textContent = 'Loading Norsk Tipping odds…';
  try {
    const response = await fetch(`/api/pl-rounds/norsk-tipping?season=${encodeURIComponent(season)}&round=${encodeURIComponent(round)}`);
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not load odds');
    if (selector.value !== requestedRound) return;
    ntRound = requestedRound;
    ntQuotes = new Map(result.quotes.map(quote => [quote.fixture_id, quote]));
    status.textContent = `${result.quotes.length} matched · Checked ${result.fetched_at ? date(result.fetched_at * 1000) : 'no upcoming games'}. Prices can change; verify them before simulating. Unmatched fixtures retain their existing names.`;
    renderRound();
  } catch (error) {
    if (selector.value === requestedRound) status.textContent = error.message;
  } finally {
    busy = false; btn.disabled = false;
  }
}

async function load(sync = false) {
  if (busy) return;
  // Do not clear a partially entered quote during the periodic page refresh.
  if (!sync && Array.from(document.querySelectorAll('#round-matches form input')).some(input => input.value !== '')) return;
  busy = true;
  button.disabled = true;
  if (sync) statusText.textContent = 'Checking fixtures and results, then updating training data…';
  try {
    const response = await fetch(sync ? '/api/pl-rounds/sync' : '/api/pl-rounds', {method: sync ? 'POST' : 'GET'});
    if (!response.ok) throw new Error('Unable to load round history. Try again later.');
    report = await response.json();
    updateOverview();
    statusText.textContent = `Last successful check: ${date(report.last_success)} · Model trained: ${date(report.trained_at)}\n${report.error || 'Automatic checks run hourly while the server is running.'}`;
    document.getElementById('round-metrics').textContent = summary(report.metrics);
    document.getElementById('simulation-total').textContent = moneySummary(report.simulation);
    const previous = selector.value;
    selector.replaceChildren();
    for (const round of report.rounds) {
      const option = document.createElement('option');
      option.value = `${round.season}:${round.round}`;
      option.textContent = `${round.season}/${round.season + 1} · Round ${round.round}`;
      selector.append(option);
    }
    const next = report.records.find(r => r.kickoff && new Date(r.kickoff) > new Date() && r.round);
    if (Array.from(selector.options).some(o => o.value === previous)) selector.value = previous;
    else if (next) selector.value = `${next.season}:${next.round}`;
    renderRound();
  } catch (error) {
    statusText.textContent = error.message;
  } finally {
    busy = false;
    button.disabled = false;
  }
}
selector.addEventListener('change', () => {
  ntQuotes.clear();
  ntRound = '';
  roundSkips.clear();
  document.getElementById('predict-round-status').textContent = 'Select a round, then predict all eligible matches.';
  document.getElementById('nt-status').textContent = 'Load odds for this round to see Norsk Tipping names and prefill the forms.';
  renderRound();
});
document.getElementById('predict-round').addEventListener('click', predictRound);
document.getElementById('load-nt-odds').addEventListener('click', loadNorskTipping);
button.addEventListener('click', () => load(true));
load();
setInterval(() => load(), 60000);
