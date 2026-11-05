/* Optional browser notifications; no match or odds data is modified. */
(() => {
  const key = 'football-round-notifications-v1';
  const button = document.getElementById('round-notifications');
  const status = document.getElementById('notifications-status');
  let checking = false;

  function readSettings() {
    try {
      const settings = JSON.parse(localStorage.getItem(key));
      if (settings && typeof settings.enabled === 'boolean' && Array.isArray(settings.completed)) return settings;
    } catch { /* Local browser storage is unavailable or invalid. */ }
    return {enabled: false, completed: []};
  }

  function saveSettings(settings) {
    try { localStorage.setItem(key, JSON.stringify(settings)); return true; }
    catch { status.textContent = 'Browser storage is unavailable; notifications cannot be enabled.'; return false; }
  }

  function updateStatus() {
    if (!('Notification' in window)) {
      button.disabled = true;
      status.textContent = 'This browser does not support desktop notifications.';
      return;
    }
    const enabled = readSettings().enabled && Notification.permission === 'granted';
    button.textContent = enabled ? 'Disable round notifications' : 'Enable round notifications';
    status.textContent = enabled
      ? 'Notifications enabled. Keep this page open and the server running; results may take several hours to be confirmed.'
      : Notification.permission === 'denied'
        ? 'Notifications are blocked in your browser settings.'
        : 'Enable browser notifications to be notified when a round finishes. Keep this page open and the server running.';
  }

  async function getRounds() {
    const response = await fetch('/api/pl-rounds');
    if (!response.ok) throw new Error('Tracker is unavailable');
    const data = await response.json();
    if (!Array.isArray(data.rounds)) throw new Error('Invalid tracker response');
    return data.rounds;
  }

  const roundKey = round => `${round.season}:${round.round}`;

  async function checkNotifications() {
    if (checking || !('Notification' in window) || Notification.permission !== 'granted' || !readSettings().enabled) return;
    checking = true;
    try {
      const rounds = await getRounds();
      // Re-read settings after the request so disabling notifications takes effect immediately.
      const settings = readSettings();
      if (!settings.enabled || Notification.permission !== 'granted') return;
      const known = new Set(settings.completed);
      for (const round of rounds) {
        const id = roundKey(round);
        if (!round.finished || known.has(id)) continue;
        const message = new Notification(`Premier League round ${round.round} finished`, {
          body: 'All currently assigned matches have confirmed results. Open the round tracker to see your predictions.',
          tag: `football-round-${id}`,
        });
        message.onclick = () => { window.focus(); message.close(); };
        known.add(id);
        // Save after each notification; don't mark a round notified if construction fails.
        if (!saveSettings({enabled: true, completed: [...known]})) break;
      }
    } catch {
      status.textContent = 'Could not check round results. Notifications will resume when the tracker is available.';
    } finally { checking = false; }
  }

  button.addEventListener('click', async () => {
    const settings = readSettings();
    if (settings.enabled && Notification.permission === 'granted') {
      if (saveSettings({...settings, enabled: false})) updateStatus();
      return;
    }
    try {
      // Request permission directly from the user's click, as required by browsers.
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') { updateStatus(); return; }
      const rounds = await getRounds();
      // Ignore rounds already finished when notifications are switched on.
      const completed = [...new Set([...settings.completed, ...rounds.filter(r => r.finished).map(roundKey)])];
      if (saveSettings({enabled: true, completed})) {
        updateStatus();
        await checkNotifications();
      }
    } catch {
      status.textContent = 'Could not enable notifications. Check that the server is running and try again.';
    }
  });

  updateStatus();
  checkNotifications();
  setInterval(checkNotifications, 60000);
  window.addEventListener('storage', event => { if (event.key === key) updateStatus(); });
})();
