import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { referralsApi } from "../api/modules";
import type { PatientSummary, ReferralFlag, Urgency } from "../api/types";
import { useApi } from "../api/useApi";
import { LoadError, Loading } from "../components/Status";
import { errorText } from "../components/Toast";
import { useI18n } from "../i18n/i18n";

export function ReferralNewPage() {
  const [params] = useSearchParams();
  const flagId = params.get("flag");
  const patientParam = params.get("patient");
  const loader = useApi(async () => {
    const flag = flagId ? await referralsApi.getFlag(flagId) : null;
    const patient = await api.getPatient(flag?.patient_id ?? patientParam ?? "");
    return { flag, patient };
  }, [flagId, patientParam]);
  if (loader.error) return <LoadError error={loader.error} onRetry={loader.reload} />;
  if (!loader.data) return <Loading />;
  return <ReferralForm key={loader.data.flag?.id ?? loader.data.patient.id} {...loader.data} />;
}

function ReferralForm({ flag, patient }: { flag: ReferralFlag | null; patient: PatientSummary }) {
  const { t, lang } = useI18n();
  const navigate = useNavigate();
  const [facility, setFacility] = useState("");
  const [reason, setReason] = useState(flag ? (lang === "fil" ? flag.reason_fil : flag.reason_en) : "");
  const [urgency, setUrgency] = useState<Urgency>(flag?.urgency ?? "routine");
  const [notes, setNotes] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setErrors([]);
    try {
      const created = await referralsApi.create({
        patient_id: patient.id, flag_id: flag?.id ?? null, facility: facility.trim(), reason: reason.trim(),
        urgency, notes: notes.trim() || null,
      });
      navigate(`/referrals/${created.id}/slip`, { replace: true });
    } catch (failure) {
      setErrors(failure instanceof ApiError ? failure.messages : [errorText(failure, t)]);
      setBusy(false);
    }
  }

  return (
    <form className="card stack" onSubmit={submit}>
      <div>
        <h1>{t("referrals.newTitle")}</h1>
        <p className="eyebrow"><Link to={`/patients/${patient.id}`}>{patient.full_name}</Link></p>
        {flag && (
          <p className="notice">
            {t("referrals.fromFlag", { reason: lang === "fil" ? flag.reason_fil : flag.reason_en })} ·{" "}
            {t("referrals.visitOn", { date: flag.visit_date })}
          </p>
        )}
      </div>
      <label className="stack">{t("referrals.facility")}
        <input required maxLength={200} value={facility} onChange={(e) => setFacility(e.target.value)} />
      </label>
      <label className="stack">{t("referrals.reason")}
        <textarea required rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <label className="stack">{t("referrals.urgency")}
        <select value={urgency} onChange={(e) => setUrgency(e.target.value as Urgency)}>
          <option value="urgent">{t("referrals.urgency.urgent")}</option>
          <option value="routine">{t("referrals.urgency.routine")}</option>
        </select>
      </label>
      <label className="stack">{t("referrals.notes")}
        <textarea rows={3} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      {errors.length > 0 && <div className="notice notice-error" role="alert">{errors.map((m) => <p key={m}>{m}</p>)}</div>}
      <div className="actions">
        <Link className="btn" to="/referrals">{t("common.cancel")}</Link>
        <button type="submit" className="btn btn-primary" disabled={busy}>{t("referrals.save")}</button>
      </div>
    </form>
  );
}
