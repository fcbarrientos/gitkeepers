import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { reportsApi } from "../api/modules";
import type { Period, ReportDraft, ReportFigures } from "../api/types";
import { useApi } from "../api/useApi";
import { LoadError, Loading } from "../components/Status";
import { errorText, useToast } from "../components/Toast";
import { pick, useI18n } from "../i18n/i18n";
import { todayIso } from "../lib/dates";
import { downloadFile, toCsv } from "../lib/download";
import { useListParams } from "../lib/useListParams";

type Metric = { key: string; value: (f: ReportFigures) => number };
const METRICS: Metric[] = [
  { key: "reports.visits", value: (f) => f.visits.total },
  { key: "reports.finalVisits", value: (f) => f.visits.final },
  { key: "reports.newHouseholds", value: (f) => f.new_households },
  { key: "reports.newPatients", value: (f) => f.new_patients },
  { key: "reports.followUpsCompleted", value: (f) => f.follow_ups_completed },
  { key: "reports.followUpsOverdue", value: (f) => f.follow_ups_overdue },
  { key: "reports.referralFlags", value: (f) => f.referral_flags },
  { key: "reports.referralsIssued", value: (f) => f.referrals_issued },
];

export function ReportsPage() {
  const { t, lang } = useI18n();
  const { params, update } = useListParams();
  const period: Period = params.get("period") === "month" ? "month" : "week";
  const day = params.get("date") || todayIso();
  const summary = useApi(() => reportsApi.summary(period, day), [period, day]);
  const drafts = useApi(() => reportsApi.drafts(period, day), [period, day]);
  const ai = useApi(api.aiStatus, []);
  const forms = useApi(api.listForms, []);
  const formTitle = (type: string) => {
    const form = forms.data?.find((f) => f.form_type === type);
    return form ? pick(form.title, lang) : type;
  };

  function exportCsv() {
    if (!summary.data) return;
    const { current, previous } = summary.data;
    const csv = toCsv([
      [t("reports.metric"), t("reports.current"), t("reports.previousPeriod")],
      ...METRICS.map((m) => [t(m.key), m.value(current), m.value(previous)]),
      [],
      [t("reports.byForm"), t("reports.current"), t("reports.previousPeriod")],
      ...Object.keys({ ...current.visits.by_form, ...previous.visits.by_form }).map((type) =>
        [formTitle(type), current.visits.by_form[type] ?? 0, previous.visits.by_form[type] ?? 0]),
      [],
      [t("reports.suppliesMoved"), t("reports.received"), t("reports.distributed")],
      ...current.supplies.map((s) => [`${s.name} (${s.unit})`, s.received, s.distributed]),
    ]);
    downloadFile(`report-${period}-${current.start}.csv`, csv, "text/csv");
  }

  return (
    <>
      <div className="page-head">
        <h1>{t("reports.title")}</h1>
        <button type="button" className="btn no-print" disabled={!summary.data} onClick={exportCsv}>{t("reports.exportCsv")}</button>
      </div>
      <div className="controls no-print">
        <label className="stack">{t("reports.period")}
          <select value={period} onChange={(e) => update({ period: e.target.value })}>
            <option value="week">{t("reports.week")}</option>
            <option value="month">{t("reports.month")}</option>
          </select>
        </label>
        <label className="stack">{t("reports.date")}
          <input type="date" value={day} onChange={(e) => update({ date: e.target.value })} />
        </label>
      </div>
      {summary.error ? <LoadError error={summary.error} onRetry={summary.reload} /> : !summary.data ? <Loading /> : (
        <>
          <p className="muted">{t("reports.range", { start: summary.data.current.start, end: summary.data.current.end })}</p>
          {summary.data.unsynced_records > 0 && (
            <p className="notice">
              {t("reports.unsynced", { count: summary.data.unsynced_records })} <Link to="/sync">{t("nav.sync")}</Link>
            </p>
          )}
          <div className="bento">
            {METRICS.map((m) => (
              <section key={m.key} className="bento-card">
                <h2 className="bento-title">{t(m.key)}</h2>
                <p className="bento-value">{m.value(summary.data!.current)}</p>
                <p className="report-compare">{t("reports.previous", { value: m.value(summary.data!.previous) })}</p>
              </section>
            ))}
          </div>
          <div className="two-col" style={{ marginTop: 16 }}>
            <section className="card">
              <h2>{t("reports.byForm")}</h2>
              <Breakdown rows={Object.entries(summary.data.current.visits.by_form).map(([k, v]) => [formTitle(k), v])} />
              <h2>{t("reports.byReason")}</h2>
              <Breakdown rows={Object.entries(summary.data.current.referrals_by_reason)
                .map(([k, v]) => [k === "manual" ? t("reports.manualReferral") : k, v])} />
            </section>
            <section className="card">
              <h2>{t("reports.suppliesMoved")}</h2>
              {summary.data.current.supplies.length === 0 ? <p className="empty">{t("reports.nothing")}</p> : (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th scope="col">{t("supplies.name")}</th><th scope="col">{t("reports.received")}</th>
                      <th scope="col">{t("reports.distributed")}</th></tr></thead>
                    <tbody>
                      {summary.data.current.supplies.map((s) => (
                        <tr key={s.name}><td>{s.name} ({s.unit})</td><td>{s.received}</td><td>{s.distributed}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <h2>{t("reports.lowStock")}</h2>
              {summary.data.current.low_stock_items.length === 0 ? <p className="empty">{t("reports.nothing")}</p> :
                <p>{summary.data.current.low_stock_items.join(", ")}</p>}
            </section>
          </div>
          <DraftPanel key={`${period}:${day}`} period={period} day={day} aiAvailable={Boolean(ai.data?.available)}
            drafts={drafts.data ?? []} onChanged={drafts.reload} />
        </>
      )}
    </>
  );
}

function Breakdown({ rows }: { rows: [string, number][] }) {
  const { t } = useI18n();
  if (rows.length === 0) return <p className="empty">{t("reports.nothing")}</p>;
  return (
    <div className="table-wrap">
      <table className="table"><tbody>
        {rows.map(([label, value]) => <tr key={label}><th scope="row">{label}</th><td>{value}</td></tr>)}
      </tbody></table>
    </div>
  );
}

type Props = { period: Period; day: string; aiAvailable: boolean; drafts: ReportDraft[]; onChanged: () => void };

function DraftPanel({ period, day, aiAvailable, drafts, onChanged }: Props) {
  const { t } = useI18n();
  const toast = useToast();
  const [editing, setEditing] = useState<{ id: string | null; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const open = drafts.find((d) => d.status === "draft");
  const approved = drafts.filter((d) => d.status === "approved");

  async function generate() {
    setBusy(true);
    setAiError(null);
    try {
      const created = await reportsApi.createAiDraft(period, day);
      setEditing({ id: created.id, text: created.text });
      onChanged();
    } catch (failure) {
      setAiError(failure instanceof ApiError && failure.status === 503 ? t("reports.aiUnavailable") : errorText(failure, t));
    } finally {
      setBusy(false);
    }
  }

  async function save(approve: boolean) {
    if (!editing) return;
    setBusy(true);
    try {
      let draftId = editing.id;
      if (!draftId) draftId = (await reportsApi.createManualDraft(period, day, editing.text)).id;
      await reportsApi.updateDraft(draftId, approve ? { text: editing.text, status: "approved" } : { text: editing.text });
      toast(t(approve ? "reports.approved" : "reports.draftSaved"));
      setEditing(approve ? null : { id: draftId, text: editing.text });
      onChanged();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <h2>{t("reports.draftTitle")}</h2>
      <p className="muted">{t("reports.draftNote")}</p>
      {!editing && (
        <div className="row-actions" style={{ marginLeft: 0 }}>
          <button type="button" className="btn btn-gold" disabled={!aiAvailable || busy} onClick={() => void generate()}>
            {t("reports.generate")}
          </button>
          <button type="button" className="btn" onClick={() => setEditing({ id: null, text: "" })}>{t("reports.writeManually")}</button>
          {open && (
            <button type="button" className="btn" onClick={() => setEditing({ id: open.id, text: open.text })}>
              {t("reports.continue")}
            </button>
          )}
        </div>
      )}
      {busy && !editing && <p className="muted" role="status">{t("reports.generating")}</p>}
      {aiError && <p className="notice notice-error" role="alert">{aiError}</p>}
      {editing && (
        <>
          <label className="stack">{t("reports.draftText")}
            <textarea rows={8} maxLength={5000} value={editing.text} onChange={(e) => setEditing({ ...editing, text: e.target.value })} />
          </label>
          <div className="actions">
            <button type="button" className="btn" disabled={busy || !editing.text.trim()} onClick={() => void save(false)}>
              {t("reports.saveDraft")}
            </button>
            <button type="button" className="btn btn-primary" disabled={busy || !editing.text.trim()} onClick={() => void save(true)}>
              {t("reports.approve")}
            </button>
          </div>
        </>
      )}
      {approved.map((d) => (
        <article key={d.id} className="notice">
          <p className="muted">{t("reports.approvedOn", { date: d.updated_at.slice(0, 10) })}</p>
          <p className="draft-text">{d.text}</p>
        </article>
      ))}
    </section>
  );
}
