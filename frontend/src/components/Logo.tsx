import { useI18n } from "../i18n/i18n";

/**
 * The official RuPort AI mark (public/brand/ruport-mark.png: the supplied logo with only its
 * transparent padding trimmed) beside the product name. `compact` shows the mark alone.
 */
export function Logo({ compact = false, tone = "dark", size = 36 }: { compact?: boolean; tone?: "dark" | "light"; size?: number }) {
  const { t } = useI18n();
  return (
    <span className={`logo logo-${tone}`}>
      <img className="logo-mark" src="/brand/ruport-mark.png" width={size} height={Math.round(size * 207 / 213)}
        alt={compact ? t("app.name") : ""} />
      {!compact && <span className="logo-word">RuPort <em>AI</em></span>}
    </span>
  );
}
