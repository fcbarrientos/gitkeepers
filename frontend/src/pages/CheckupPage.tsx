import { useEffect, useReducer, useRef, useState } from "react";
import { Link, useBlocker, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { AIStatus, FollowUp, FormDefinition, PatientSummary, Values, Visit, VisitInput, VisitStatus } from "../api/types";
import { useApi } from "../api/useApi";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { LoadError, Loading } from "../components/Status";
import { errorText, useToast } from "../components/Toast";
import { acceptedFrom, checkupReducer, emptyCheckup, savedFields } from "../forms/checkup";
import { FormRenderer } from "../forms/FormRenderer";
import { pick, useI18n } from "../i18n/i18n";
import { addDays, todayIso } from "../lib/dates";

type Loaded = {
  visit: Visit | null;
  patient: PatientSummary;
  form: FormDefinition;
  openFollowUps: FollowUp[];
  ai: AIStatus;
};

type FollowUpDraft = { on: boolean; date: string; reason: string; completes: string };

/** Unsaved checkup kept in this tab, so an expired session or a reload does not lose the form. */
type Stash = { values: Values; suggestionId: string | null; accepted: string[]; note: string; visitDate: string; followUp: FollowUpDraft };

function readStash(key: string): Stash | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as Stash) : null;
  } catch {
    return null;
  }
}

function writeStash(key: string, stash: Stash | null): void {
  try {
    if (stash) sessionStorage.setItem(key, JSON.stringify(stash));
    else sessionStorage.removeItem(key);
  } catch {
    // Storage blocked: the form just isn't kept across sign-ins.
  }
}

export function CheckupPage() {
  const { patientId: routePatient, visitId } = useParams();
  const [params] = useSearchParams();
  const formParam = params.get("form");
  const loader = useApi<Loaded>(async () => {
    const visit = visitId ? await api.getVisit(visitId) : null;
    const patientId = visit?.patient_id ?? routePatient ?? "";
    const [patient, form, followUps, ai] = await Promise.all([
      api.getPatient(patientId),
      api.getForm(visit?.form_type ?? formParam ?? ""),
      api.listFollowUps({ patient_id: patientId, limit: 100 }),
      api.aiStatus(),
    ]);
    return { visit, patient, form, ai, openFollowUps: followUps.items.filter((f) => f.status === "scheduled") };
  }, [visitId, routePatient, formParam]);
  if (loader.error) return <LoadError error={loader.error} onRetry={loader.reload} />;
  if (!loader.data) return <Loading />;
  const { visit } = loader.data;
  return <CheckupEditor key={`${visit?.id ?? "new"}:${visit?.status ?? ""}`} {...loader.data} onFinalized={loader.reload} />;
}

function CheckupEditor({ visit, patient, form, openFollowUps, ai, onFinalized }: Loaded & { onFinalized: () => void }) {
  const { t, lang } = useI18n();
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const readOnly = visit?.status === "final";
  const stashKey = `gk.checkup:${location.pathname}${location.search}`;
  const [restored] = useState(() => (readOnly ? null : readStash(stashKey)));
  // Follow-up choices carried over from the first draft save of a new visit.
  const carried = (location.state as { followUp?: FollowUpDraft } | null)?.followUp;
  const seed: FollowUpDraft = restored?.followUp ?? carried ?? {
    on: false, date: addDays(visit?.visit_date ?? todayIso(), form.default_follow_up_days), reason: "", completes: "",
  };
  const [state, dispatch] = useReducer(checkupReducer, emptyCheckup, (initial) => {
    if (restored) return checkupReducer(initial, { type: "load", values: restored.values, suggestionId: restored.suggestionId, accepted: restored.accepted });
    if (visit) return checkupReducer(initial, { type: "load", values: visit.values, suggestionId: visit.suggestion_id, accepted: acceptedFrom(visit.sources) });
    return initial;
  });
  const [visitDate, setVisitDate] = useState(restored?.visitDate ?? visit?.visit_date ?? todayIso());
  const [note, setNote] = useState(restored?.note ?? visit?.note ?? "");
  const [metaDirty, setMetaDirty] = useState(Boolean(restored) || seed.on || Boolean(seed.completes));
  const [invalidFields, setInvalidFields] = useState<string[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string[]>([]);
  const [conflict, setConflict] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmFinal, setConfirmFinal] = useState(false);
  const [followUpOn, setFollowUpOn] = useState(seed.on);
  const [followUpDate, setFollowUpDate] = useState(seed.date);
  const [followUpReason, setFollowUpReason] = useState(seed.reason);
  const [completes, setCompletes] = useState(seed.completes);
  const [aiRunning, setAiRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiInfo, setAiInfo] = useState<{ missing: string[]; problems: string[] } | null>(null);
  const savingRef = useRef(false);
  const leaving = useRef(false);

  const dirty = !readOnly && (state.dirty || metaDirty);
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    dirty && !leaving.current && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const followUp: FollowUpDraft = { on: followUpOn, date: followUpDate, reason: followUpReason, completes };
  useEffect(() => {
    if (leaving.current || readOnly) return;
    writeStash(stashKey, dirty ? { values: state.values, suggestionId: state.suggestionId, accepted: state.accepted, note, visitDate, followUp } : null);
  }, [dirty, stashKey, state, note, visitDate, followUpOn, followUpDate, followUpReason, completes]);

  const labelOf = (name: string) => {
    const field = form.fields.find((f) => f.name === name);
    return field ? pick(field.label, lang) : name;
  };
  const meta = <T,>(set: (value: T) => void) => (value: T) => {
    set(value);
    setMetaDirty(true);
  };

  async function fillFromNote() {
    setAiRunning(true);
    setAiError(null);
    setAiInfo(null);
    setElapsed(0);
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    try {
      const suggestion = await api.suggest(patient.id, form.form_type, note.trim());
      dispatch({ type: "suggested", suggestionId: suggestion.suggestion_id, values: suggestion.values });
      setAiInfo({ missing: suggestion.missing, problems: suggestion.problems });
    } catch (failure) {
      setAiError(failure instanceof ApiError && failure.status === 503 ? t("ai.unavailable") : errorText(failure, t));
    } finally {
      window.clearInterval(timer);
      setAiRunning(false);
    }
  }

  function showSaveError(failure: unknown) {
    if (failure instanceof ApiError && failure.status === 422) {
      const names = new Set(form.fields.map((f) => f.name));
      const byField: Record<string, string> = {};
      const rest: string[] = [];
      for (const message of failure.messages) {
        const [name, ...problem] = message.split(": ");
        if (names.has(name) && problem.length) byField[name] = problem.join(": ");
        else rest.push(message);
      }
      setErrors(byField);
      setGeneral(rest);
    } else if (failure instanceof ApiError && failure.status === 409) {
      setConflict(true);
    } else {
      toast(errorText(failure, t), "error");
    }
  }

  async function save(status: VisitStatus) {
    if (savingRef.current) return;
    if (invalidFields.length > 0) {
      setConfirmFinal(false);
      setGeneral([t("checkup.fixInvalid")]);
      return;
    }
    savingRef.current = true;
    setConfirmFinal(false);
    setSaving(true);
    setErrors({});
    setGeneral([]);
    setConflict(false);
    const body: VisitInput = { visit_date: visitDate, note: note.trim() || null, status, ...savedFields(state) };
    if (status === "final") {
      // The backend accepts follow-up options only when finalizing.
      if (followUpOn) body.follow_up = { due_date: followUpDate, reason: followUpReason.trim() || null };
      if (completes) body.completes_follow_up_id = completes;
    }
    try {
      const saved = visit ? await api.updateVisit(visit.id, body) : await api.createVisit(patient.id, { ...body, form_type: form.form_type });
      dispatch({ type: "saved" });
      // Follow-up choices are only sent on finalize, so after a draft save they are still unsaved.
      setMetaDirty(status === "draft" && (followUpOn || Boolean(completes)));
      toast(t(status === "final" ? "checkup.finalized" : "checkup.draftSaved"));
      if (!visit) {
        leaving.current = true;
        writeStash(stashKey, null);
        navigate(`/visits/${saved.id}`, { replace: true, state: status === "draft" ? { followUp } : null });
      } else if (status === "final") {
        onFinalized();
      }
    } catch (failure) {
      showSaveError(failure);
    } finally {
      // After creating a visit this editor stays locked: it is about to be replaced by the
      // saved visit's page, and saving again from here would create a second visit.
      if (!leaving.current) {
        savingRef.current = false;
        setSaving(false);
      }
    }
  }

  return (
    <div className="checkup">
      <div className="page-head">
        <div>
          <p className="eyebrow"><Link to={`/patients/${patient.id}`}>{patient.full_name}</Link></p>
          <h1>{pick(form.title, lang)}</h1>
          <p className="muted">{t("checkup.pendingReview")}</p>
        </div>
        {visit && <span className={`badge badge-${visit.status}`}>{t(`visit.${visit.status}`)}</span>}
      </div>
      {readOnly && <p className="notice">{t("checkup.readOnly")}</p>}
      {conflict && (
        <div className="notice notice-error" role="alert">
          <p>{t("checkup.conflict")}</p>
          <button type="button" className="btn" onClick={() => window.location.reload()}>{t("common.reload")}</button>
        </div>
      )}
      {general.length > 0 && (
        <div className="notice notice-error" role="alert">{general.map((m) => <p key={m}>{m}</p>)}</div>
      )}
      <div className="checkup-layout">
        <section className="card">
          <label className="stack">{t("checkup.visitDate")}
            <input type="date" value={visitDate} max={todayIso()} readOnly={readOnly}
              onChange={(e) => meta(setVisitDate)(e.target.value)} />
          </label>
          <FormRenderer
            form={form}
            values={state.values}
            pending={readOnly ? undefined : state.pending}
            errors={errors}
            sources={visit?.sources}
            readOnly={readOnly}
            onChange={(name, value) => dispatch({ type: "set", name, value })}
            onAccept={(name) => dispatch({ type: "accept", name })}
            onReject={(name) => dispatch({ type: "reject", name })}
            onInvalid={(name, invalid) =>
              setInvalidFields((current) => (invalid ? [...new Set([...current, name])] : current.filter((n) => n !== name)))}
          />
          {!readOnly && (
            <section className="card">
              <h2>{t("checkup.followUpTitle")}</h2>
              <p className="muted">{t("checkup.finalOnly")}</p>
              <label className="check">
                <input type="checkbox" checked={followUpOn} onChange={(e) => meta(setFollowUpOn)(e.target.checked)} />
                {t("checkup.scheduleFollowUp")}
              </label>
              {followUpOn && (
                <div className="inline-fields">
                  <label className="stack">{t("checkup.followUpDate")}
                    <input type="date" value={followUpDate} min={addDays(visitDate, 1)}
                      onChange={(e) => meta(setFollowUpDate)(e.target.value)} />
                  </label>
                  <label className="stack">{t("checkup.followUpReason")}
                    <input value={followUpReason} maxLength={500} onChange={(e) => meta(setFollowUpReason)(e.target.value)} />
                  </label>
                </div>
              )}
              {openFollowUps.length > 0 && (
                <label className="stack">{t("checkup.completesFollowUp")}
                  <select value={completes} onChange={(e) => meta(setCompletes)(e.target.value)}>
                    <option value="">{t("checkup.completesNone")}</option>
                    {openFollowUps.map((f) => (
                      <option key={f.id} value={f.id}>{t("checkup.completesOption", { date: f.due_date })}</option>
                    ))}
                  </select>
                </label>
              )}
            </section>
          )}
          {!readOnly && (
            <div className="actions">
              <button type="button" className="btn" disabled={saving} onClick={() => void save("draft")}>{t("checkup.saveDraft")}</button>
              <button type="button" className="btn btn-primary" disabled={saving} onClick={() => setConfirmFinal(true)}>
                {t("checkup.finalize")}
              </button>
            </div>
          )}
        </section>
        <details className="checkup-ai card" open>
          <summary>{t("checkup.aiTitle")}</summary>
          <label className="stack">{t("checkup.note")}
            <textarea rows={6} value={note} readOnly={readOnly} placeholder={t("checkup.notePlaceholder")}
              onChange={(e) => meta(setNote)(e.target.value)} />
          </label>
          {!readOnly && (
            <>
              {!ai.available && <p className="notice">{t("ai.unavailable")}</p>}
              <button type="button" className="btn btn-gold" disabled={!ai.available || aiRunning || !note.trim()}
                onClick={() => void fillFromNote()}>
                {t("checkup.fillFromNote")}
              </button>
              {aiRunning && <p className="muted" role="status">{t("checkup.aiWorking", { seconds: elapsed })}</p>}
              {aiError && <p className="notice notice-error" role="alert">{aiError}</p>}
              {aiInfo && (
                <div>
                  <p>{t("checkup.aiDone")}</p>
                  {Object.keys(state.pending).length > 0 && (
                    <button type="button" className="btn btn-small" onClick={() => dispatch({ type: "acceptAll" })}>
                      {t("checkup.acceptAll")}
                    </button>
                  )}
                  {aiInfo.missing.length > 0 && (
                    <p className="muted">{t("checkup.aiMissing", { fields: aiInfo.missing.map(labelOf).join(", ") })}</p>
                  )}
                  {aiInfo.problems.length > 0 && (
                    <>
                      <p>{t("checkup.aiProblems")}</p>
                      <ul>{aiInfo.problems.map((p) => <li key={p}>{p}</li>)}</ul>
                    </>
                  )}
                </div>
              )}
            </>
          )}
        </details>
      </div>
      <ConfirmDialog open={confirmFinal} title={t("checkup.finalizeTitle")} body={t("checkup.finalizeBody")}
        confirmLabel={t("checkup.finalize")} onConfirm={() => void save("final")} onCancel={() => setConfirmFinal(false)} />
      <ConfirmDialog open={blocker.state === "blocked"} title={t("checkup.leaveTitle")} body={t("checkup.leaveBody")}
        confirmLabel={t("checkup.leave")} onConfirm={() => { writeStash(stashKey, null); blocker.proceed?.(); }} onCancel={() => blocker.reset?.()} />
    </div>
  );
}
