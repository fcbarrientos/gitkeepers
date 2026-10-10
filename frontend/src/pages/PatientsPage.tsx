import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Pager } from "../components/Pager";
import { SearchBox } from "../components/SearchBox";
import { LoadError, Loading } from "../components/Status";
import { useI18n } from "../i18n/i18n";
import { useListParams } from "../lib/useListParams";

const LIMIT = 25;

export function PatientsPage() {
  const { t } = useI18n();
  const { q, offset, setQuery, setOffset } = useListParams();
  const list = useApi(() => api.listPatients({ q, limit: LIMIT, offset }), [q, offset]);
  return (
    <>
      <div className="page-head"><h1>{t("patients.title")}</h1></div>
      <SearchBox value={q} label={t("patients.search")} onSearch={setQuery} />
      {list.error ? <LoadError error={list.error} onRetry={list.reload} /> : !list.data ? <Loading /> :
        list.data.items.length === 0 ? <p className="empty">{t("common.noResults")}</p> : (
          <ul className="list">
            {list.data.items.map((p) => (
              <li key={p.id}>
                <Link to={`/patients/${p.id}`} className="list-row">
                  <strong>{p.full_name}</strong>
                  <span>{[p.sitio, p.barangay].filter(Boolean).join(", ")}</span>
                  {p.birth_date && <span className="muted">{t("patients.born", { date: p.birth_date })}</span>}
                </Link>
              </li>
            ))}
          </ul>
        )}
      {list.data && <Pager total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />}
    </>
  );
}
