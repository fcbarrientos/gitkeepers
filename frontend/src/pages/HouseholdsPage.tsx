import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Pager } from "../components/Pager";
import { SearchBox } from "../components/SearchBox";
import { LoadError, Loading } from "../components/Status";
import { useI18n } from "../i18n/i18n";
import { useListParams } from "../lib/useListParams";

const LIMIT = 25;

export function HouseholdsPage() {
  const { t } = useI18n();
  const { q, offset, setQuery, setOffset } = useListParams();
  const list = useApi(() => api.listHouseholds({ q, limit: LIMIT, offset }), [q, offset]);
  return (
    <>
      <div className="page-head">
        <h1>{t("households.title")}</h1>
        <Link className="btn btn-primary" to="/households/new">{t("households.register")}</Link>
      </div>
      <SearchBox value={q} label={t("households.search")} onSearch={setQuery} />
      {list.error ? <LoadError error={list.error} onRetry={list.reload} /> : !list.data ? <Loading /> :
        list.data.items.length === 0 ? <p className="empty">{t("common.noResults")}</p> : (
          <ul className="list">
            {list.data.items.map((h) => (
              <li key={h.id}>
                <Link to={`/households/${h.id}`} className="list-row">
                  <strong>{h.head_name ?? t("households.noHead")}</strong>
                  <span>{[h.sitio, h.barangay].filter(Boolean).join(", ")}</span>
                  <span className="muted">{t("households.members", { count: h.member_count })}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      {list.data && <Pager total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />}
    </>
  );
}
