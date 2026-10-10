import { useI18n } from "../i18n/i18n";

export function ComingSoonPage({ titleKey }: { titleKey: string }) {
  const { t } = useI18n();
  return (
    <>
      <div className="page-head"><h1>{t(titleKey)}</h1></div>
      <p className="notice">{t("common.comingSoonBody")}</p>
    </>
  );
}
