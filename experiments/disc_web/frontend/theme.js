/* Applied before CSS to avoid a light flash. Appearance never touches DISC. */
(function (root) {
  const key = 'disc-web.appearance';
  const normalize = value => ['system', 'light', 'dark'].includes(value) ? value : 'system';
  const resolve = (value, dark) => normalize(value) === 'system' ? (dark ? 'dark' : 'light') : value;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {normalize, resolve};
    return;
  }
  const media = root.matchMedia('(prefers-color-scheme: dark)');
  let preference = 'system';
  try { preference = normalize(root.localStorage.getItem(key)); } catch { /* Private storage may be unavailable. */ }
  function apply() {
    const theme = resolve(preference, media.matches);
    root.document.documentElement.dataset.theme = theme;
    root.document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#151815' : '#faf9f6');
    root.dispatchEvent(new CustomEvent('disc-theme-change'));
  }
  root.DiscTheme = {
    get: () => preference,
    set(value) {
      preference = normalize(value);
      try { root.localStorage.setItem(key, preference); } catch { /* Keep the session preference. */ }
      apply();
    }
  };
  media.addEventListener('change', apply);
  root.addEventListener('storage', event => {
    if (event.key === key || event.key === null) {preference = normalize(event.newValue); apply();}
  });
  apply();
})(typeof window === 'undefined' ? null : window);
