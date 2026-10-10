import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Icon } from "../components/Icon";
import { Pager } from "../components/Pager";
import { SearchBox } from "../components/SearchBox";
import { LoadError, Loading } from "../components/Status";
import { useI18n } from "../i18n/i18n";
import { useListParams } from "../lib/useListParams";

const LIMIT = 25;

export function PatientsPage() {
  const { t } = useI18n();
  const { params, q, offset, setQuery, setOffset } = useListParams();
  const picking = params.get("pick") === "checkup";
  const list = useApi(() => api.listPatients({ q, limit: LIMIT, offset }), [q, offset]);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("patients.title")}</h1>
          {list.data && <p className="muted">{t("patients.count", { count: list.data.total })}</p>}
        </div>
        <Link className="btn" to="/households?pick=member"><Icon name="plus" size={18} />{t("dashboard.registerPatient")}</Link>
      </div>
      {picking && <p className="notice notice-info" role="status">{t("patients.pickForCheckup")}</p>}
      <SearchBox value={q} label={t("patients.search")} onSearch={setQuery} />
      {list.error ? <LoadError error={list.error} onRetry={list.reload} /> : !list.data ? <Loading /> :
        list.data.items.length === 0 ? (
          <div className="empty-state">
            <p>{q ? t("common.noResults") : t("patients.none")}</p>
            {!q && <Link className="btn btn-primary" to="/households/new">{t("households.register")}</Link>}
          </div>
        ) : (
          <div className="table-wrap table-card">
            <table className="table table-stack">
              <thead>
                <tr>
                  <th scope="col">{t("member.fullName")}</th>
                  <th scope="col">{t("households.place")}</th>
                  <th scope="col">{t("member.birthDate")}</th>
                  <th scope="col">{t("member.sex")}</th>
                  <th scope="col"><span className="sr-only">{t("common.actions")}</span></th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((p) => (
                  <tr key={p.id}>
                    <td data-label={t("member.fullName")}>
                      <Link to={`/patients/${p.id}`} className="cell-strong">{p.full_name}</Link>
                      {p.is_household_head && <span className="badge badge-soft">{t("member.head")}</span>}
                    </td>
                    <td data-label={t("households.place")}>{[p.sitio, p.barangay].filter(Boolean).join(", ")}</td>
                    <td data-label={t("member.birthDate")} className="nowrap">{p.birth_date ?? <span className="muted">—</span>}</td>
                    <td data-label={t("member.sex")}>{t(p.sex ? `member.sex.${p.sex}` : "member.sex.unset")}</td>
                    <td className="cell-action">
                      <Link className={`btn btn-small${picking ? " btn-primary" : ""}`} to={`/patients/${p.id}`}>
                        {t(picking ? "patients.startCheckup" : "patients.open")}
                      </Link>
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
