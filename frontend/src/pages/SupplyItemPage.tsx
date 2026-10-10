import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { suppliesApi } from "../api/modules";
import type { MovementKind } from "../api/types";
import { useApi } from "../api/useApi";
import { LoadError, Loading } from "../components/Status";
import { errorText, useToast } from "../components/Toast";
import { useI18n } from "../i18n/i18n";
import { todayIso } from "../lib/dates";

const KINDS: MovementKind[] = ["received", "distributed", "adjusted"];

export function SupplyItemPage() {
  const { itemId = "" } = useParams();
  const { t } = useI18n();
  const toast = useToast();
  const item = useApi(() => suppliesApi.get(itemId), [itemId]);
  const movements = useApi(() => suppliesApi.movements(itemId, { limit: 100 }), [itemId]);
  const [kind, setKind] = useState<MovementKind>("received");
  const [quantity, setQuantity] = useState("");
  const [movementDate, setMovementDate] = useState(todayIso());
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [levels, setLevels] = useState<{ low: string; target: string } | null>(null);

  async function record(event: FormEvent) {
    event.preventDefault();
    setErrors([]);
    try {
      await suppliesApi.addMovement(itemId, { kind, quantity: Number(quantity), movement_date: movementDate,
        note: note.trim() || null });
      toast(t("supplies.recorded"));
      setQuantity("");
      setNote("");
      item.reload();
      movements.reload();
    } catch (failure) {
      setErrors(failure instanceof ApiError ? failure.messages : [errorText(failure, t)]);
    }
  }

  async function saveLevels(event: FormEvent) {
    event.preventDefault();
    if (!levels) return;
    try {
      await suppliesApi.update(itemId, { low_stock_threshold: Number(levels.low), target_level: Number(levels.target) });
      toast(t("supplies.saved"));
      setLevels(null);
      item.reload();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  if (item.error) return <LoadError error={item.error} onRetry={item.reload} />;
  if (!item.data) return <Loading />;
  const it = item.data;
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow"><Link to="/supplies">{t("supplies.title")}</Link></p>
          <h1>{it.name}</h1>
          <p>{t("supplies.onHand", { count: it.on_hand, unit: it.unit })}
            {it.low && <> <span className="badge badge-overdue">{t("supplies.low")}</span></>}</p>
        </div>
      </div>
      <form className="card" onSubmit={record}>
        <h2>{t("supplies.recordMovement")}</h2>
        <div className="inline-fields">
          <label className="stack">{t("supplies.kind")}
            <select value={kind} onChange={(e) => setKind(e.target.value as MovementKind)}>
              {KINDS.map((k) => <option key={k} value={k}>{t(`supplies.kind.${k}`)}</option>)}
            </select>
          </label>
          <label className="stack">{t("supplies.quantity")}
            <input type="number" required step={1} min={kind === "adjusted" ? undefined : 1} value={quantity}
              onChange={(e) => setQuantity(e.target.value)} />
          </label>
          <label className="stack">{t("supplies.date")}
            <input type="date" required max={todayIso()} value={movementDate} onChange={(e) => setMovementDate(e.target.value)} />
          </label>
          <label className="stack">{t("supplies.note")}
            <input maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
        </div>
        {kind === "adjusted" && <p className="hint">{t("supplies.adjustHint")}</p>}
        {errors.length > 0 && <div className="notice notice-error" role="alert">{errors.map((m) => <p key={m}>{m}</p>)}</div>}
        <div className="actions"><button type="submit" className="btn btn-primary">{t("supplies.recordMovement")}</button></div>
      </form>
      <section className="card">
        <div className="card-head">
          <h2>{t("supplies.settings")}</h2>
          {!levels && (
            <button type="button" className="btn btn-small"
              onClick={() => setLevels({ low: String(it.low_stock_threshold), target: String(it.target_level) })}>
              {t("common.save")}
            </button>
          )}
        </div>
        {levels ? (
          <form className="inline-form" onSubmit={saveLevels}>
            <label className="stack">{t("supplies.threshold")}
              <input type="number" min={0} step={1} required value={levels.low} onChange={(e) => setLevels({ ...levels, low: e.target.value })} />
            </label>
            <label className="stack">{t("supplies.target")}
              <input type="number" min={0} step={1} required value={levels.target} onChange={(e) => setLevels({ ...levels, target: e.target.value })} />
            </label>
            <button type="submit" className="btn btn-primary btn-small">{t("common.save")}</button>
            <button type="button" className="btn btn-small" onClick={() => setLevels(null)}>{t("common.cancel")}</button>
          </form>
        ) : (
          <p className="muted">{t("supplies.threshold")}: {it.low_stock_threshold} · {t("supplies.target")}: {it.target_level}</p>
        )}
      </section>
      <section className="card">
        <h2>{t("supplies.history")}</h2>
        {movements.data && movements.data.items.length === 0 && <p className="empty">{t("supplies.noHistory")}</p>}
        {movements.data && movements.data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr>
                <th scope="col">{t("supplies.date")}</th><th scope="col">{t("supplies.kind")}</th>
                <th scope="col">{t("supplies.quantity")}</th><th scope="col">{t("supplies.by")}</th>
                <th scope="col">{t("supplies.note")}</th>
              </tr></thead>
              <tbody>
                {movements.data.items.map((m) => (
                  <tr key={m.id}>
                    <td>{m.movement_date}</td><td>{t(`supplies.kind.${m.kind}`)}</td>
                    <td>{m.quantity > 0 ? `+${m.quantity}` : m.quantity}</td><td>{m.recorded_by_name}</td><td>{m.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
