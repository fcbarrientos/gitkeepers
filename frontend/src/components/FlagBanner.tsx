import { Link } from "react-router-dom";
import { referralsApi } from "../api/modules";
import { useApi } from "../api/useApi";
import { useI18n } from "../i18n/i18n";

/** Open referral flags for a visit or a patient, each with a link to refer. */
export function FlagBanner({ visitId, patientId }: { visitId?: string; patientId?: string }) {
  const { t, lang } = useI18n();
  const flags = useApi(() => referralsApi.listFlags({ visit_id: visitId, patient_id: patientId, status: "open" }),
    [visitId, patientId]);
  const items = flags.data ?? [];
  if (items.length === 0) return null;
  return (
    <div className="notice notice-error flag-banner" role="alert">
      <strong>{t("referrals.flagBannerTitle")}</strong>
      <ul>
        {items.map((flag) => (
          <li key={flag.id}>
            {lang === "fil" ? flag.reason_fil : flag.reason_en}{" "}
            <Link to={`/referrals/new?flag=${encodeURIComponent(flag.id)}`}>{t("referrals.createReferral")}</Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
