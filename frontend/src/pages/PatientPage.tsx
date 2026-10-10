import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { FlagBanner } from "../components/FlagBanner";
import { LoadError, Loading } from "../components/Status";
import { pick, useI18n } from "../i18n/i18n";

export function PatientPage() {
  const { patientId = "" } = useParams();
  const { t, lang } = useI18n();
  const navigate = useNavigate();
  const patient = useApi(() => api.getPatient(patientId), [patientId]);
  const forms = useApi(api.listForms, []);
  const [formFilter, setFormFilter] = useState("");
  const [chosen, setChosen] = useState("");
  const visits = useApi(() => api.listPatientVisits(patientId, { form_type: formFilter, limit: 100 }), [patientId, formFilter]);
  const followUps = useApi(() => api.listFollowUps({ patient_id: patientId, limit: 100 }), [patientId]);

  if (patient.error) return <LoadError error={patient.error} onRetry={patient.reload} />;
  if (!patient.data) return <Loading />;
  const p = patient.data;
  const formList = forms.data ?? [];
  const titleOf = (type: string) => {
    const form = formList.find((f) => f.form_type === type);
    return form ? pick(form.title, lang) : type;
  };
  const start = chosen || formList[0]?.form_type || "";
  const details = [
    [p.sitio, p.barangay].filter(Boolean).join(", "),
    p.birth_date && t("patients.born", { date: p.birth_date }),
    p.contact_number,
  ].filter(Boolean).join(" · ");

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{p.full_name}</h1>
          <p className="muted">{details}</p>
          <Link to={`/households/${p.household_id}`}>{t("patients.household")}</Link>
          {" · "}<Link to={`/referrals/new?patient=${encodeURIComponent(p.id)}`}>{t("referrals.refer")}</Link>
        </div>
        <form className="inline-form" style={{ width: "auto" }}
          onSubmit={(e) => { e.preventDefault(); navigate(`/patients/${p.id}/visits/new?form=${encodeURIComponent(start)}`); }}>
          <label className="stack">{t("patients.chooseForm")}
            <select value={start} onChange={(e) => setChosen(e.target.value)}>
              {formList.map((f) => <option key={f.form_type} value={f.form_type}>{pick(f.title, lang)}</option>)}
            </select>
          </label>
          <button type="submit" className="btn btn-primary" disabled={!start}>{t("patients.startCheckup")}</button>
        </form>
      </div>
      <FlagBanner patientId={p.id} />
      <div className="two-col">
        <section className="card">
          <div className="card-head">
            <h2>{t("patients.timeline")}</h2>
            <select aria-label={t("patients.allForms")} value={formFilter} onChange={(e) => setFormFilter(e.target.value)}>
              <option value="">{t("patients.allForms")}</option>
              {formList.map((f) => <option key={f.form_type} value={f.form_type}>{pick(f.title, lang)}</option>)}
            </select>
          </div>
          {visits.error ? <LoadError error={visits.error} onRetry={visits.reload} /> : !visits.data ? <Loading /> :
            visits.data.items.length === 0 ? <p className="empty">{t("patients.noVisits")}</p> : (
              <ol className="timeline">
                {visits.data.items.map((v) => (
                  <li key={v.id}>
                    <Link to={`/visits/${v.id}`} className="list-row">
                      <span>{v.visit_date}</span>
                      <strong>{titleOf(v.form_type)}</strong>
                      <span className={`badge badge-${v.status}`}>{t(`visit.${v.status}`)}</span>
                    </Link>
                  </li>
                ))}
              </ol>
            )}
        </section>
        <section className="card">
          <h2>{t("patients.followUps")}</h2>
          {followUps.data && followUps.data.items.length === 0 && <p className="empty">{t("patients.noFollowUps")}</p>}
          <ul className="list">
            {followUps.data?.items.map((f) => (
              <li key={f.id} className="list-row">
                <span>{t("followUps.dueOn", { date: f.due_date })}</span>
                {f.reason && <span>{f.reason}</span>}
                <span className={`badge badge-${f.state}`}>{t(`followUps.${f.state}`)}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </>
  );
}
