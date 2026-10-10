import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Icon } from "../components/Icon";
import { Pager } from "../components/Pager";
import { LoadError, Loading } from "../components/Status";
import { pick, useI18n } from "../i18n/i18n";
import { todayIso } from "../lib/dates";
import { useListParams } from "../lib/useListParams";

const LIMIT = 25;
const STATUSES = ["", "draft", "final"] as const;

/** Every recorded checkup, newest first, filterable by status and visit date. */
export function CheckupsPage() {
  const { t, lang } = useI18n();
  const { params, offset, update, setOffset } = useListParams();
  const status = params.get("status") ?? "";
  const date = params.get("date") ?? "";
  const list = useApi(() => api.listVisits({ status, date, limit: LIMIT, offset }), [status, date, offset]);
  const forms = useApi(api.listForms, []);
  const formTitle = (type: string) => {
    const form = forms.data?.find((f) => f.form_type === type);
    return form ? pick(form.title, lang) : type;
  };
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("checkups.title")}</h1>
          <p className="muted">{t("checkups.intro")}</p>
        </div>
        <Link className="btn btn-primary" to="/patients?pick=checkup"><Icon name="plus" size={18} />{t("dashboard.newCheckup")}</Link>
      </div>
      <div className="toolbar">
        <div className="tabs" role="tablist" aria-label={t("checkups.status")}>
          {STATUSES.map((value) => (
            <button key={value || "all"} type="button" role="tab" className="tab" aria-selected={status === value}
              onClick={() => update({ status: value || undefined, offset: undefined })}>
              {value ? t(`visit.${value}`) : t("checkups.all")}
            </button>
          ))}
        </div>
        <label className="stack toolbar-field">{t("checkup.visitDate")}
          <input type="date" value={date} max={todayIso()} onChange={(e) => update({ date: e.target.value || undefined, offset: undefined })} />
        </label>
        {date && <button type="button" className="btn btn-ghost" onClick={() => update({ date: undefined, offset: undefined })}>{t("checkups.clearDate")}</button>}
      </div>
      {list.error ? <LoadError error={list.error} onRetry={list.reload} /> : !list.data ? <Loading /> :
        list.data.items.length === 0 ? (
          <div className="empty-state">
            <p>{t("checkups.none")}</p>
            <Link className="btn btn-primary" to="/patients?pick=checkup">{t("dashboard.newCheckup")}</Link>
          </div>
        ) : (
          <div className="table-wrap table-card">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{t("checkup.visitDate")}</th>
                  <th scope="col">{t("slip.patient")}</th>
                  <th scope="col">{t("patients.chooseForm")}</th>
                  <th scope="col">{t("slip.status")}</th>
                  <th scope="col"><span className="sr-only">{t("common.actions")}</span></th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((v) => (
                  <tr key={v.id}>
                    <td className="nowrap">{v.visit_date}</td>
                    <td><Link to={`/patients/${v.patient_id}`} className="cell-strong">{v.patient_name}</Link></td>
                    <td>{formTitle(v.form_type)}</td>
                    <td><span className={`badge badge-${v.status}`}>{t(`visit.${v.status}`)}</span></td>
                    <td className="cell-action">
                      <Link className="btn btn-small" to={`/visits/${v.id}`}>{t(v.status === "draft" ? "checkups.continue" : "checkups.view")}</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      {list.data && <Pager total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />}
    </>
  );
}
