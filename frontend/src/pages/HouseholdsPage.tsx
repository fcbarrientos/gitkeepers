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

export function HouseholdsPage() {
  const { t } = useI18n();
  const { params, q, offset, setQuery, setOffset } = useListParams();
  const picking = params.get("pick") === "member";
  const list = useApi(() => api.listHouseholds({ q, limit: LIMIT, offset }), [q, offset]);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("households.title")}</h1>
          {list.data && <p className="muted">{t("households.count", { count: list.data.total })}</p>}
        </div>
        <Link className="btn btn-primary" to="/households/new"><Icon name="plus" size={18} />{t("households.register")}</Link>
      </div>
      {picking && <p className="notice notice-info" role="status">{t("households.pickForMember")}</p>}
      <SearchBox value={q} label={t("households.search")} onSearch={setQuery} />
      {list.error ? <LoadError error={list.error} onRetry={list.reload} /> : !list.data ? <Loading /> :
        list.data.items.length === 0 ? (
          <div className="empty-state">
            <p>{q ? t("common.noResults") : t("households.none")}</p>
            {!q && <Link className="btn btn-primary" to="/households/new">{t("households.register")}</Link>}
          </div>
        ) : (
          <div className="table-wrap table-card">
            <table className="table table-stack">
              <thead>
                <tr>
                  <th scope="col">{t("member.head")}</th>
                  <th scope="col">{t("households.place")}</th>
                  <th scope="col">{t("households.membersTitle")}</th>
                  <th scope="col">{t("households.contact")}</th>
                  <th scope="col"><span className="sr-only">{t("common.actions")}</span></th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((h) => (
                  <tr key={h.id}>
                    <td data-label={t("member.head")}>
                      <Link to={`/households/${h.id}`} className="cell-strong">{h.head_name ?? t("households.noHead")}</Link>
                    </td>
                    <td data-label={t("households.place")}>{[h.address_line, h.sitio, h.barangay].filter(Boolean).join(", ")}</td>
                    <td data-label={t("households.membersTitle")}>{t("households.members", { count: h.member_count })}</td>
                    <td data-label={t("households.contact")}>{h.contact_number ?? <span className="muted">—</span>}</td>
                    <td className="cell-action">
                      <Link className={`btn btn-small${picking ? " btn-primary" : ""}`} to={`/households/${h.id}`}>
                        {t(picking ? "households.addMember" : "patients.open")}
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
