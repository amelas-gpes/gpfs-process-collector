(() => {
  "use strict";

  const storageKey = "process-collector.theme";
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
  const themeColor = document.querySelector('meta[name="theme-color"]');
  const colorScheme = document.querySelector('meta[name="color-scheme"]');
  let select;
  let preference = "system";

  function readPreference() {
    try {
      const saved = window.localStorage.getItem(storageKey);
      preference = saved === "dark" || saved === "light" ? saved : "system";
    } catch {
      // Storage may be unavailable. Keep the current choice for this tab.
    }
  }

  function applyTheme() {
    const dark = preference === "dark" || (preference === "system" && systemDark.matches);
    const theme = dark ? "dark" : "light";
    document.documentElement.dataset.theme = theme;
    colorScheme.content = theme;
    themeColor.content = dark ? "#202429" : "#ffffff";
    if (select) select.value = preference;
  }

  // This script runs before stylesheets so a saved override applies on first paint.
  readPreference();
  applyTheme();
  systemDark.addEventListener("change", applyTheme);
  window.addEventListener("storage", event => {
    if (event.key !== storageKey && event.key !== null) return;
    readPreference();
    applyTheme();
  });

  document.addEventListener("DOMContentLoaded", () => {
    select = document.getElementById("theme-select");
    select.value = preference;
    select.addEventListener("change", () => {
      preference = select.value;
      applyTheme();
      try {
        if (preference === "system") window.localStorage.removeItem(storageKey);
        else window.localStorage.setItem(storageKey, preference);
      } catch {
        // The selected theme still applies when the browser blocks persistence.
      }
    });
  });
})();
