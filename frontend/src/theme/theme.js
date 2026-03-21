const STORAGE_KEY = "hexe_theme";
const LEGACY_STORAGE_KEY = "synthia_theme";

export function getTheme() {
  return localStorage.getItem(STORAGE_KEY) || localStorage.getItem(LEGACY_STORAGE_KEY) || "dark";
}

export function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(STORAGE_KEY, theme);
  localStorage.removeItem(LEGACY_STORAGE_KEY);
}

export function initTheme() {
  setTheme(getTheme());
}
