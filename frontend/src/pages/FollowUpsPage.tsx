import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { FollowUp, FollowUpState } from "../api/types";
import { useApi } from "../api/useApi";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Pager } from "../components/Pager";
import { SearchBox } from "../components/SearchBox";
import { LoadError, Loading } from "../components/Status";
import { errorText, useToast } from "../components/Toast";
import { useI18n } from "../i18n/i18n";
import { todayIso } from "../lib/dates";
import { useListParams } from "../lib/useListParams";

const STATES: FollowUpState[] = ["overdue", "due", "upcoming", "completed", "cancelled"];
const LIMIT = 25;

export function FollowUpsPage() {
  const { t } = useI18n();
  const { params, q, offset, update, setQuery, setOffset } = useListParams();
  const requested = params.get("state") as FollowUpState | null;
  const state: FollowUpState = requested && STATES.includes(requested) ? requested : "overdue";
  const list = useApi(() => api.listFollowUps({ state, q, limit: LIMIT, offset }), [state, q, offset]);
  return (
    <>
      <div className="page-head"><h1>{t("followUps.title")}</h1></div>
      <div className="tabs" role="tablist" aria-label={t("followUps.title")}>
        {STATES.map((s) => (
          <button key={s} type="button" role="tab" className="tab" aria-selected={s === state}
            onClick={() => update({ state: s, offset: undefined })}>
            {t(`followUps.${s}`)}
          </button>
        ))}
      </div>
      <SearchBox value={q} label={t("followUps.search")} onSearch={setQuery} />
      {list.error ? <LoadError error={list.error} onRetry={list.reload} /> : !list.data ? <Loading /> :
        list.data.items.length === 0 ? <p className="empty">{t("followUps.none")}</p> : (
          <ul className="list">
            {list.data.items.map((item) => <FollowUpRow key={item.id} item={item} onChanged={list.reload} />)}
          </ul>
        )}
      {list.data && <Pager total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />}
    </>
  );
}

function FollowUpRow({ item, onChanged }: { item: FollowUp; onChanged: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const [rescheduling, setRescheduling] = useState(false);
  const [date, setDate] = useState(item.due_date);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>, doneKey: string) {
    setBusy(true);
    try {
      await action();
      toast(t(doneKey));
      onChanged();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    } finally {
      setBusy(false);
    }
  }

  function reschedule(event: FormEvent) {
    event.preventDefault();
    setRescheduling(false);
    void run(() => api.updateFollowUp(item.id, { due_date: date }), "followUps.rescheduledToast");
  }

  return (
    <li className="list-row">
      <Link to={`/patients/${item.patient_id}`}><strong>{item.patient_name}</strong></Link>
      <span className="muted">{item.barangay}</span>
      <span>{t("followUps.dueOn", { date: item.due_date })}</span>
      {item.reason && <span>{item.reason}</span>}
      <span className={`badge badge-${item.state}`}>{t(`followUps.${item.state}`)}</span>
      {item.status === "scheduled" && (
        <div className="row-actions">
          {item.form_type && (
            <Link className="btn btn-small btn-primary" to={`/patients/${item.patient_id}/visits/new?form=${encodeURIComponent(item.form_type)}`}>
              {t("followUps.recordVisit")}
            </Link>
          )}
          <button type="button" className="btn btn-small" disabled={busy}
            onClick={() => void run(() => api.completeFollowUp(item.id), "followUps.completedToast")}>
            {t("followUps.complete")}
          </button>
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => setRescheduling((v) => !v)}>
            {t("followUps.reschedule")}
          </button>
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => setConfirmCancel(true)}>
            {t("followUps.cancel")}
          </button>
        </div>
      )}
      {rescheduling && (
        <form className="inline-form" onSubmit={reschedule}>
          <label className="stack">{t("followUps.newDate")}
            <input type="date" required value={date} min={todayIso()} onChange={(e) => setDate(e.target.value)} />
          </label>
          <button type="submit" className="btn btn-small btn-primary">{t("common.save")}</button>
        </form>
      )}
      <ConfirmDialog open={confirmCancel} title={t("followUps.cancelTitle")} confirmLabel={t("followUps.cancel")}
        onCancel={() => setConfirmCancel(false)}
        onConfirm={() => {
          setConfirmCancel(false);
          void run(() => api.updateFollowUp(item.id, { status: "cancelled" }), "followUps.cancelledToast");
        }} />
    </li>
  );
}
