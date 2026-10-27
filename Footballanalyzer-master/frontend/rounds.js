const statusText = document.getElementById('round-status');
const selector = document.getElementById('round-select');
const button = document.getElementById('sync-rounds');
let report;
let busy = false;
const pct = n => `${(n * 100).toFixed(1)}%`;
const date = value => value ? new Date(value).toLocaleString() : 'Not yet';
const label = value => ({ home: 'Home win', draw: 'Draw', away: 'Away win' }[value]);

function summary(metrics) {
  if (!metrics.count) return 'No completed matches with saved pre-match forecasts yet.';
  return `${metrics.count} evaluated · Accuracy ${pct(metrics.accuracy)} · Log loss ${metrics.log_loss.toFixed(3)} · Brier ${metrics.brier.toFixed(3)} · Baseline log loss ${metrics.baseline_log_loss.toFixed(3)}`;
}

function renderRound() {
  const rows = document.getElementById('round-matches');
  rows.replaceChildren();
  const chosen = report.rounds.find(r => `${r.season}:${r.round}` === selector.value);
  document.getElementById('selected-metrics').textContent = chosen ? summary(chosen) : '';
  for (const match of report.records.filter(r => `${r.season}:${r.round}` === selector.value)) {
    const f = match.forecast;
    let feedback = match.reason || 'Waiting for final result';
    if (f && match.result && match.eligible) {
      feedback = `${f.pick === match.result ? 'Correct' : 'Miss'} · Model assigned ${pct(f.probabilities[match.result])} to the actual result. ${match.included_in_training ? 'Included in latest training data.' : 'Waiting for training results source.'}`;
    }
    const values = [
      `${match.home} – ${match.away}\n${date(match.kickoff)}`,
      f ? ['home', 'draw', 'away'].map(k => pct(f.probabilities[k])).join(' / ') : 'No saved forecast',
      f ? `${label(f.pick)}\nSaved ${date(f.created_at)}\nModel ${f.model_id}\nResults through ${f.last_result}` : '—',
      match.result ? `${match.score[0]}–${match.score[1]} (${label(match.result)})` : 'Pending',
      feedback,
    ];
    const row = document.createElement('tr');
    for (const value of values) {
      const cell = document.createElement('td');
      cell.textContent = value;
      cell.style.whiteSpace = 'pre-line';
      row.append(cell);
    }
    rows.append(row);
  }
}

async function load(sync = false) {
  if (busy) return;
  busy = true;
  button.disabled = true;
  if (sync) statusText.textContent = 'Checking fixtures and results, then updating training data…';
  try {
    const response = await fetch(sync ? '/api/pl-rounds/sync' : '/api/pl-rounds', {method: sync ? 'POST' : 'GET'});
    if (!response.ok) throw new Error('Unable to load round history. Try again later.');
    report = await response.json();
    statusText.textContent = `Last successful check: ${date(report.last_success)} · Model trained: ${date(report.trained_at)}\n${report.error || 'Automatic checks run hourly while the server is running.'}`;
    document.getElementById('round-metrics').textContent = summary(report.metrics);
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
selector.addEventListener('change', renderRound);
button.addEventListener('click', () => load(true));
load();
setInterval(() => load(), 60000);
