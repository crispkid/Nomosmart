/**
 * CHG-495 UIRD-001: colour theme preference. "system" follows prefers-color-scheme; "light" and
 * "dark" are stored in the browser only (no API). Storage can throw (private mode, blocked site
 * data), so every read and write falls back to "system".
 */
export type ThemePreference = "system" | "light" | "dark";

export const themePreferenceKey = "nomosmart-theme";
export const themePreferences: readonly ThemePreference[] = ["system", "light", "dark"];

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

export function readThemePreference(storage: Pick<Storage, "getItem"> | null | undefined): ThemePreference {
  try {
    const value = storage?.getItem(themePreferenceKey);
    return isThemePreference(value) ? value : "system";
  } catch {
    return "system";
  }
}

/** Stores the choice; returns false when the browser refused it (the page still switches). */
export function writeThemePreference(storage: Pick<Storage, "setItem" | "removeItem"> | null | undefined, preference: ThemePreference): boolean {
  try {
    if (!storage) return false;
    if (preference === "system") storage.removeItem(themePreferenceKey);
    else storage.setItem(themePreferenceKey, preference);
    return true;
  } catch {
    return false;
  }
}

/** "system" removes the attribute so the prefers-color-scheme rules in globals.css apply. */
export function applyThemePreference(root: HTMLElement, preference: ThemePreference): void {
  if (preference === "system") delete root.dataset.theme;
  else root.dataset.theme = preference;
}

/** Inline script run in <head> before first paint, so a stored dark theme never flashes light. */
export function themeBootScript(): string {
  const key = JSON.stringify(themePreferenceKey);
  return `(function(){try{var t=window.localStorage.getItem(${key});if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}})();`;
}
