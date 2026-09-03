import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react";

type ThemeMode = "day" | "night";

interface ThemeContextType {
  mode: ThemeMode;
  toggle: () => void;
  isTransitioning: boolean;
}

const ThemeContext = createContext<ThemeContextType>({
  mode: "day",
  toggle: () => {},
  isTransitioning: false,
});

export function useTheme() {
  return useContext(ThemeContext);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Initialize from localStorage if available, otherwise default to "day"
  const [mode, setMode] = useState<ThemeMode>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("novara_theme");
      if (saved === "day" || saved === "night") {
        return saved;
      }
    }
    return "night";
  });
  const [isTransitioning, setIsTransitioning] = useState(false);

  const toggle = useCallback(() => {
    setIsTransitioning(true);
    // Small delay so transition class is applied before mode changes
    setTimeout(() => {
      setMode((m) => {
        const nextMode = m === "day" ? "night" : "day";
        localStorage.setItem("novara_theme", nextMode);
        return nextMode;
      });
    }, 50);
    // Transition lasts 1.5s
    setTimeout(() => {
      setIsTransitioning(false);
    }, 1600);
  }, []);

  // Apply class to document
  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove("theme-day", "theme-night");
    root.classList.add(`theme-${mode}`);
    if (isTransitioning) {
      root.classList.add("theme-transitioning");
    } else {
      root.classList.remove("theme-transitioning");
    }
  }, [mode, isTransitioning]);

  return (
    <ThemeContext.Provider value={{ mode, toggle, isTransitioning }}>
      {children}
    </ThemeContext.Provider>
  );
}
