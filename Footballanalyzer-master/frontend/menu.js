(() => {
  const button = document.getElementById('menu-toggle');
  const sidebar = document.getElementById('sidebar');
  const shell = document.querySelector('.app-shell');
  let expanded = true;

  try {
    expanded = localStorage.getItem('football-analyzer-menu') !== 'closed';
  } catch (_) {
    // The menu remains usable when browser storage is unavailable.
  }

  function render() {
    sidebar.hidden = !expanded;
    shell.classList.toggle('menu-closed', !expanded);
    button.setAttribute('aria-expanded', String(expanded));
    button.setAttribute('aria-label', expanded ? 'Hide menu' : 'Show menu');
    button.title = expanded ? 'Hide menu' : 'Show menu';
  }

  button.addEventListener('click', () => {
    expanded = !expanded;
    render();
    try {
      localStorage.setItem('football-analyzer-menu', expanded ? 'open' : 'closed');
    } catch (_) {
      // Keep the current page interactive without persistent storage.
    }
  });
  render();
  button.hidden = false;
})();
