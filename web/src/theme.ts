import { createContext, useContext } from "react";

/** Light or dark. A saved choice wins; without one the system setting decides. */
export type Theme = "light" | "dark";

const STORAGE_KEY = "found-theme";
export const DARK_QUERY = "(prefers-color-scheme: dark)";

/** The saved choice, or null. Storage can be blocked, which counts as no choice. */
export function savedTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

export function saveTheme(theme: Theme) {
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // The choice still applies for this visit.
  }
}

export function systemTheme(): Theme {
  return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches
    ? "dark"
    : "light";
}

export function initialTheme(): Theme {
  return savedTheme() ?? systemTheme();
}

/** Every color token switches on this attribute (see styles.css). */
export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}

export interface ThemeState {
  theme: Theme;
  toggle: () => void;
}

export const ThemeContext = createContext<ThemeState>({ theme: "light", toggle: () => {} });

export function useTheme(): ThemeState {
  return useContext(ThemeContext);
}
