import { useI18n } from "../i18n/i18n";

type Props = { total: number; limit: number; offset: number; onChange: (offset: number) => void };

export function Pager({ total, limit, offset, onChange }: Props) {
  const { t } = useI18n();
  if (total <= limit) return null;
  return (
    <nav className="pager" aria-label={t("common.pages")}>
      <button type="button" className="btn btn-small" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        {t("common.previous")}
      </button>
      <span>{t("common.pageRange", { from: offset + 1, to: Math.min(offset + limit, total), total })}</span>
      <button type="button" className="btn btn-small" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
        {t("common.next")}
      </button>
    </nav>
  );
}
