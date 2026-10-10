import { useI18n } from "./i18n";

export function LanguageToggle() {
  const { lang, setLang, t } = useI18n();
  return (
    <div className="lang-toggle" role="group" aria-label={t("lang.label")}>
      {(["en", "fil"] as const).map((code) => (
        <button key={code} type="button" aria-pressed={lang === code} onClick={() => setLang(code)}>
          {t(`lang.${code}`)}
        </button>
      ))}
    </div>
  );
}
