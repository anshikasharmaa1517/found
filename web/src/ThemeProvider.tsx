import { useCallback, useEffect, useState, type ReactNode } from "react";

import {
  applyTheme,
  DARK_QUERY,
  initialTheme,
  savedTheme,
  saveTheme,
  systemTheme,
  ThemeContext,
  type Theme,
} from "./theme";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => applyTheme(theme), [theme]);

  // Follow the system until the person picks a theme here.
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(DARK_QUERY);
    function onChange() {
      if (savedTheme() === null) setTheme(systemTheme());
    }
    query.addEventListener?.("change", onChange);
    return () => query.removeEventListener?.("change", onChange);
  }, []);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next = current === "dark" ? "light" : "dark";
      saveTheme(next);
      return next;
    });
  }, []);

  return <ThemeContext.Provider value={{ theme, toggle }}>{children}</ThemeContext.Provider>;
}
