const STORAGE_KEY = "hexe_theme";

export function getTheme() {
  return localStorage.getItem(STORAGE_KEY) || "dark";
}

export function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(STORAGE_KEY, theme);
}

export function initTheme() {
  setTheme(getTheme());
}
