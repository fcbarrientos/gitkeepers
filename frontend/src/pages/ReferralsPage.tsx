import { useState } from "react";
import { Link } from "react-router-dom";
import { referralsApi } from "../api/modules";
import type { ReferralFlag } from "../api/types";
import { useApi } from "../api/useApi";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { LoadError, Loading } from "../components/Status";
import { errorText, useToast } from "../components/Toast";
import { useI18n } from "../i18n/i18n";
import { useListParams } from "../lib/useListParams";

export function ReferralsPage() {
  const { t, lang } = useI18n();
  const toast = useToast();
  const { params, update } = useListParams();
  const tab = params.get("tab") === "referrals" ? "referrals" : "flags";
  const flags = useApi(() => referralsApi.listFlags({ status: "open" }), []);
  const referrals = useApi(() => referralsApi.list({ limit: 100 }), []);
  const [dismissing, setDismissing] = useState<ReferralFlag | null>(null);

  async function dismiss() {
    if (!dismissing) return;
    const flag = dismissing;
    setDismissing(null);
    try {
      await referralsApi.dismissFlag(flag.id, null);
      toast(t("referrals.dismissed"));
      flags.reload();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  return (
    <>
      <div className="page-head"><h1>{t("referrals.title")}</h1></div>
      <p className="muted">{t("referrals.rulesNote")}</p>
      <div className="tabs" role="tablist" aria-label={t("referrals.title")}>
        <button type="button" role="tab" className="tab" aria-selected={tab === "flags"} onClick={() => update({ tab: undefined })}>
          {t("referrals.openFlags")}{flags.data ? ` (${flags.data.length})` : ""}
        </button>
        <button type="button" role="tab" className="tab" aria-selected={tab === "referrals"} onClick={() => update({ tab: "referrals" })}>
          {t("referrals.list")}
        </button>
      </div>
      {tab === "flags" ? (
        flags.error ? <LoadError error={flags.error} onRetry={flags.reload} /> : !flags.data ? <Loading /> :
          flags.data.length === 0 ? <p className="empty">{t("referrals.noFlags")}</p> : (
            <ul className="list">
              {flags.data.map((flag) => (
                <li key={flag.id} className="list-row">
                  <Link to={`/patients/${flag.patient_id}`}><strong>{flag.patient_name}</strong></Link>
                  <span>{lang === "fil" ? flag.reason_fil : flag.reason_en}</span>
                  <span className={`badge badge-${flag.urgency}`}>{t(`referrals.urgency.${flag.urgency}`)}</span>
                  <span className="muted">{t("referrals.visitOn", { date: flag.visit_date })}</span>
                  <div className="row-actions">
                    <Link className="btn btn-small btn-primary" to={`/referrals/new?flag=${encodeURIComponent(flag.id)}`}>
                      {t("referrals.createReferral")}
                    </Link>
                    <button type="button" className="btn btn-small" onClick={() => setDismissing(flag)}>{t("referrals.dismiss")}</button>
                  </div>
                </li>
              ))}
            </ul>
          )
      ) : (
        referrals.error ? <LoadError error={referrals.error} onRetry={referrals.reload} /> : !referrals.data ? <Loading /> :
          referrals.data.items.length === 0 ? <p className="empty">{t("referrals.noReferrals")}</p> : (
            <ul className="list">
              {referrals.data.items.map((r) => (
                <li key={r.id}>
                  <Link to={`/referrals/${r.id}/slip`} className="list-row">
                    <span>{r.created_at.slice(0, 10)}</span>
                    <strong>{r.patient_name}</strong>
                    <span>{r.facility}</span>
                    <span className="muted">{r.reason}</span>
                    <span className={`badge badge-${r.status}`}>{t(`referrals.status.${r.status}`)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )
      )}
      <ConfirmDialog open={dismissing !== null} title={t("referrals.dismissTitle")} body={t("referrals.dismissBody")}
        confirmLabel={t("referrals.dismiss")} onConfirm={() => void dismiss()} onCancel={() => setDismissing(null)} />
    </>
  );
}
