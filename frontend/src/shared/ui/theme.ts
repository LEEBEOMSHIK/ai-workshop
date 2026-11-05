export type Theme = "dark" | "light";
export const themeStorageKey = "ai-workshop.theme.v1";

// The head script runs before the first paint, including on public pages.
export const themeBootstrap = `(() => {
  const key = "${themeStorageKey}";
  function restore() {
    try {
      document.documentElement.dataset.theme = localStorage.getItem(key) === "light" ? "light" : "dark";
    } catch { /* The root CSS supplies the default when storage is unavailable. */ }
  }
  restore();
  window.addEventListener("storage", event => {
    if (event.key === key || event.key === null) restore();
  });
})();`;

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function chooseTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try { window.localStorage.setItem(themeStorageKey, theme); }
  catch { /* The selected appearance remains available for this page. */ }
}

export function subscribeTheme(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}
