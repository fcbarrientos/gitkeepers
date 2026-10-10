import { Link } from "react-router-dom";
import { suppliesApi } from "../api/modules";
import { useApi } from "../api/useApi";
import { LoadError, Loading } from "../components/Status";
import { useI18n } from "../i18n/i18n";
import { todayIso } from "../lib/dates";
import { downloadFile, toCsv } from "../lib/download";

export function SupplyRequestPage() {
  const { t } = useI18n();
  const list = useApi(suppliesApi.requestList, []);
  if (list.error) return <LoadError error={list.error} onRetry={list.reload} />;
  if (!list.data) return <Loading />;
  const rows = list.data;

  function exportCsv() {
    const csv = toCsv([
      [t("supplies.name"), t("supplies.unit"), t("supplies.quantity"), t("supplies.target"), t("supplies.request")],
      ...rows.map((r) => [r.name, r.unit, r.on_hand, r.target_level, r.request_quantity]),
    ]);
    downloadFile(`supply-request-${todayIso()}.csv`, csv, "text/csv");
  }

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow no-print"><Link to="/supplies">{t("supplies.title")}</Link></p>
          <h1>{t("supplies.requestTitle")}</h1>
          <p className="muted">{t("supplies.requestIntro")} {todayIso()}</p>
        </div>
        <div className="row-actions no-print">
          <button type="button" className="btn" onClick={() => window.print()}>{t("supplies.print")}</button>
          <button type="button" className="btn btn-primary" disabled={rows.length === 0} onClick={exportCsv}>
            {t("supplies.exportCsv")}
          </button>
        </div>
      </div>
      {rows.length === 0 ? <p className="empty">{t("supplies.requestNone")}</p> : (
        <div className="card table-wrap">
          <table className="table">
            <thead><tr>
              <th scope="col">{t("supplies.name")}</th><th scope="col">{t("supplies.quantity")}</th>
              <th scope="col">{t("supplies.target")}</th><th scope="col">{t("supplies.request")}</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.name} ({r.unit})</td><td>{r.on_hand}</td><td>{r.target_level}</td><td><strong>{r.request_quantity}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
