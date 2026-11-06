/* 1.8.0: the funky theme was retired (issue 15) — three calm themes remain. */
const THEMES = new Set(['dark', 'light', 'soft']);

export function normalizeTheme(value) {
  return THEMES.has(value) ? value : 'dark';
}

export function nextTheme(value) {
  const current = normalizeTheme(value);
  const cycle = ['dark', 'light', 'soft'];
  return cycle[(cycle.indexOf(current) + 1) % cycle.length];
}
