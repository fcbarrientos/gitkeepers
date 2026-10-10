import { useState, type ChangeEvent, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { suppliesApi } from "../api/modules";
import { useApi } from "../api/useApi";
import { LoadError, Loading } from "../components/Status";
import { errorText, useToast } from "../components/Toast";
import { useI18n } from "../i18n/i18n";

const EMPTY = { name: "", unit: "", low: "", target: "" };

export function SuppliesPage() {
  const { t } = useI18n();
  const toast = useToast();
  const items = useApi(suppliesApi.list, []);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState(EMPTY);

  async function add(event: FormEvent) {
    event.preventDefault();
    try {
      await suppliesApi.create({ name: draft.name.trim(), unit: draft.unit.trim(),
        low_stock_threshold: Number(draft.low), target_level: Number(draft.target) });
      toast(t("supplies.itemAdded"));
      setDraft(EMPTY);
      setAdding(false);
      items.reload();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  const field = (key: keyof typeof EMPTY) => ({
    value: draft[key], onChange: (e: ChangeEvent<HTMLInputElement>) => setDraft({ ...draft, [key]: e.target.value }),
  });

  return (
    <>
      <div className="page-head">
        <h1>{t("supplies.title")}</h1>
        <div className="row-actions">
          <Link className="btn" to="/supplies/request-list">{t("supplies.requestList")}</Link>
          <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>{t("supplies.addItem")}</button>
        </div>
      </div>
      {adding && (
        <form className="card" onSubmit={add}>
          <div className="inline-fields">
            <label className="stack">{t("supplies.name")}<input required maxLength={120} {...field("name")} /></label>
            <label className="stack">{t("supplies.unit")}<input required maxLength={40} {...field("unit")} /></label>
            <label className="stack">{t("supplies.threshold")}<input type="number" required min={0} step={1} {...field("low")} /></label>
            <label className="stack">{t("supplies.target")}<input type="number" required min={0} step={1} {...field("target")} /></label>
          </div>
          <div className="actions">
            <button type="button" className="btn" onClick={() => setAdding(false)}>{t("common.cancel")}</button>
            <button type="submit" className="btn btn-primary">{t("common.save")}</button>
          </div>
        </form>
      )}
      {items.error ? <LoadError error={items.error} onRetry={items.reload} /> : !items.data ? <Loading /> :
        items.data.length === 0 ? <p className="empty">{t("supplies.none")}</p> : (
          <div className="table-wrap table-card">
            <table className="table table-stack">
              <thead>
                <tr>
                  <th scope="col">{t("supplies.name")}</th>
                  <th scope="col">{t("supplies.stockLevel")}</th>
                  <th scope="col">{t("supplies.threshold")}</th>
                  <th scope="col">{t("slip.status")}</th>
                </tr>
              </thead>
              <tbody>
                {items.data.map((item) => (
                  <tr key={item.id}>
                    <td data-label={t("supplies.name")}><Link to={`/supplies/${item.id}`} className="cell-strong">{item.name}</Link></td>
                    <td data-label={t("supplies.stockLevel")}>
                      <span className="stock-cell">
                        {t("supplies.onHand", { count: item.on_hand, unit: item.unit })}
                        <span className={`meter${item.low ? " meter-low" : ""}`} aria-hidden="true">
                          <span style={{ width: `${Math.min(100, (item.on_hand / Math.max(1, item.target_level)) * 100)}%` }} />
                        </span>
                      </span>
                    </td>
                    <td data-label={t("supplies.threshold")}>{item.low_stock_threshold}</td>
                    <td data-label={t("slip.status")}>
                      {item.low ? <span className="badge badge-overdue">{t("supplies.low")}</span>
                        : <span className="badge badge-active">{t("supplies.ok")}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
    </>
  );
}
