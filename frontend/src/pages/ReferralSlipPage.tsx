import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { referralsApi } from "../api/modules";
import { useApi } from "../api/useApi";
import { LoadError, Loading } from "../components/Status";
import { displayValue } from "../forms/FormRenderer";
import { pick, useI18n } from "../i18n/i18n";

export function ReferralSlipPage() {
  const { referralId = "" } = useParams();
  const { t, lang } = useI18n();
  const referral = useApi(() => referralsApi.get(referralId), [referralId]);
  const formType = referral.data?.visit?.form_type;
  const form = useApi(async () => (formType ? api.getForm(formType) : null), [formType]);
  if (referral.error) return <LoadError error={referral.error} onRetry={referral.reload} />;
  if (!referral.data) return <Loading />;
  const r = referral.data;
  const visit = r.visit;
  return (
    <>
      <div className="page-head no-print">
        <Link to="/referrals?tab=referrals">{t("slip.back")}</Link>
        <button type="button" className="btn btn-primary" onClick={() => window.print()}>{t("slip.print")}</button>
      </div>
      <article className="card slip">
        <h1>{t("slip.title")}</h1>
        <p className="muted">{t("slip.draftNote")}</p>
        <dl className="slip-grid">
          <dt>{t("slip.date")}</dt><dd>{r.created_at.slice(0, 10)}</dd>
          <dt>{t("slip.patient")}</dt><dd>{r.patient_name}</dd>
          <dt>{t("slip.birthDate")}</dt><dd>{r.birth_date ?? "—"}</dd>
          <dt>{t("slip.sex")}</dt><dd>{r.sex ? t(`member.sex.${r.sex}`) : "—"}</dd>
          <dt>{t("slip.address")}</dt><dd>{[r.sitio, r.barangay].filter(Boolean).join(", ")}</dd>
          <dt>{t("referrals.facility")}</dt><dd>{r.facility}</dd>
          <dt>{t("referrals.urgency")}</dt><dd>{t(`referrals.urgency.${r.urgency}`)}</dd>
          <dt>{t("referrals.reason")}</dt><dd>{r.reason}</dd>
          {r.notes && (<><dt>{t("referrals.notes")}</dt><dd>{r.notes}</dd></>)}
          <dt>{t("slip.referredBy")}</dt><dd>{r.created_by_name}</dd>
          <dt>{t("slip.status")}</dt><dd>{t(`referrals.status.${r.status}`)}</dd>
        </dl>
        {visit && form.data && (
          <section>
            <h2>{t("slip.findings", { date: visit.visit_date })}</h2>
            <div className="table-wrap">
              <table className="table">
                <tbody>
                  {form.data.fields.filter((f) => visit.values[f.name] != null).map((f) => (
                    <tr key={f.name}>
                      <th scope="row">{pick(f.label, lang)}</th>
                      <td>{displayValue(visit.values[f.name], t)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
        <p className="slip-sign">{t("slip.receivedBy")}: ______________________________</p>
      </article>
    </>
  );
}
