import { Link } from "react-router-dom";
import { useI18n } from "../i18n/i18n";

export function NotFoundPage() {
  const { t } = useI18n();
  return (
    <>
      <h1>{t("common.notFound")}</h1>
      <Link to="/">{t("nav.dashboard")}</Link>
    </>
  );
}
