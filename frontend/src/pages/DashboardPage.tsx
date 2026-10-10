import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { BentoCard } from "../components/BentoCard";
import { LoadError, Loading } from "../components/Status";
import { pick, useI18n } from "../i18n/i18n";

export function DashboardPage() {
  const { t, lang } = useI18n();
  const summary = useApi(api.dashboard, []);
  const recent = useApi(() => api.listVisits({ limit: 5 }), []);
  const forms = useApi(api.listForms, []);
  if (summary.error) return <LoadError error={summary.error} onRetry={summary.reload} />;
  if (!summary.data) return <Loading />;
  const data = summary.data;
  const formTitle = (type: string) => {
    const form = forms.data?.find((f) => f.form_type === type);
    return form ? pick(form.title, lang) : type;
  };
  return (
    <>
      <div className="page-head">
        <h1>{t("dashboard.title")}</h1>
        <Link className="btn btn-primary" to="/patients">{t("dashboard.newCheckup")}</Link>
      </div>
      <div className="bento">
        <BentoCard title={t("followUps.overdue")} value={data.follow_ups.overdue} to="/follow-ups?state=overdue" tone="alert" />
        <BentoCard title={t("followUps.due")} value={data.follow_ups.due} to="/follow-ups?state=due" tone="gold" />
        <BentoCard wide title={t("dashboard.recentVisits")}>
          {recent.data && recent.data.items.length === 0 && <p className="empty">{t("dashboard.noVisits")}</p>}
          <ul className="list">
            {recent.data?.items.map((v) => (
              <li key={v.id}>
                <Link to={`/visits/${v.id}`} className="list-row">
                  <span>{v.visit_date}</span>
                  <strong>{v.patient_name}</strong>
                  <span className="muted">{formTitle(v.form_type)}</span>
                  <span className={`badge badge-${v.status}`}>{t(`visit.${v.status}`)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </BentoCard>
        <BentoCard title={t("followUps.upcoming")} value={data.follow_ups.upcoming} to="/follow-ups?state=upcoming" />
        <BentoCard title={t("dashboard.visitsToday")} value={data.visits_today} />
        <BentoCard title={t("dashboard.drafts")} value={data.drafts} />
        <BentoCard title={t("dashboard.households")} value={data.households} to="/households" />
        <BentoCard title={t("dashboard.patients")} value={data.patients} to="/patients" />
        <BentoCard title={t("dashboard.ai")} value={t(data.ai.available ? "ai.ready" : "ai.off")}
          note={data.ai.model ?? t("ai.manualNote")} />
        <BentoCard title={t("nav.referrals")} soon />
        <BentoCard title={t("nav.supplies")} soon />
        <BentoCard title={t("nav.reports")} soon />
      </div>
    </>
  );
}
