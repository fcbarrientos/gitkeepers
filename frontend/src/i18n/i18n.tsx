import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import en from "./en.json";
import fil from "./fil.json";

export type Lang = "en" | "fil";
export type Vars = Record<string, string | number>;
export type Translate = (key: string, vars?: Vars) => string;
type Dict = Record<string, string>;

const DICTS: Record<Lang, Dict> = { en, fil };
const STORAGE_KEY = "gk.lang";

/** Look `key` up in `primary`, then `fallback`, then show the key itself; fill {name} variables. */
export function format(primary: Dict, fallback: Dict, key: string, vars: Vars = {}): string {
  let text = primary[key] ?? fallback[key] ?? key;
  for (const [name, value] of Object.entries(vars)) text = text.split(`{${name}}`).join(String(value));
  return text;
}

/** Pick a label from a form definition's {en, fil} map. */
export function pick(labels: Record<string, string>, lang: Lang): string {
  return labels[lang] ?? labels.en ?? Object.values(labels)[0] ?? "";
}

function storedLang(): Lang {
  try {
    return localStorage.getItem(STORAGE_KEY) === "fil" ? "fil" : "en";
  } catch {
    return "en";
  }
}

type I18n = { lang: Lang; setLang: (lang: Lang) => void; t: Translate };
const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(storedLang);
  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // The choice just isn't remembered in this browser.
    }
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const value = useMemo<I18n>(
    () => ({ lang, setLang, t: (key, vars) => format(DICTS[lang], DICTS.en, key, vars) }),
    [lang, setLang],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n must be used inside I18nProvider");
  return context;
}
