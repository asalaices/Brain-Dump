// SPDX-License-Identifier: AGPL-3.0-only
export const THEMES = Object.freeze(['dark', 'light', 'ocean', 'midnight', 'plum', 'sand']);
const STORAGE_KEY = 'cortex.theme';

export function bindTheme({root, select, notice, getStorage}) {
  function warn(message) {
    notice.hidden = false;
    notice.textContent = message;
  }
  function apply(theme) {
    if (!THEMES.includes(theme)) throw new TypeError('Unknown Cortex theme.');
    root.dataset.theme = theme;
    select.value = theme;
  }
  let saved;
  try {
    saved = getStorage().getItem(STORAGE_KEY);
  } catch {
    warn('Theme storage is unavailable. Your selection applies only to this page.');
  }
  if (saved && !THEMES.includes(saved)) {
    warn('The saved theme is not supported. Using Dark until you choose another theme.');
  }
  apply(THEMES.includes(saved) ? saved : 'dark');
  const change = () => {
    apply(select.value);
    try {
      getStorage().setItem(STORAGE_KEY, select.value);
      notice.hidden = true;
      notice.textContent = '';
    } catch {
      warn('Theme storage is unavailable. Your selection applies only to this page.');
    }
  };
  select.addEventListener('change', change);
  return () => select.removeEventListener('change', change);
}
