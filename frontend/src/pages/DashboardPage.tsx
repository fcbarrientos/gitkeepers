import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { referralsApi, reportsApi, suppliesApi, syncApi } from "../api/modules";
import type { Dashboard, SyncStatus } from "../api/types";
import { useApi } from "../api/useApi";
import { BarList, ColumnChart, StackedBar } from "../components/Charts";
import { Icon, type IconName } from "../components/Icon";
import { LoadError, Loading } from "../components/Status";
import { pick, useI18n, type Translate } from "../i18n/i18n";
import { addDays, fromUtcStamp, shortStamp, todayIso } from "../lib/dates";
import { useAuth } from "../auth/AuthProvider";

const locale = (lang: string) => (lang === "fil" ? "fil-PH" : "en-PH");

function Panel({ title, action, children, className }: { title: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel${className ? ` ${className}` : ""}`}>
      <header className="panel-head"><h2>{title}</h2>{action}</header>
      {children}
    </section>
  );
}

function SectionError({ onRetry }: { onRetry: () => void }) {
  const { t } = useI18n();
  return <p className="empty">{t("dashboard.sectionError")} <button type="button" className="link-btn" onClick={onRetry}>{t("common.retry")}</button></p>;
}

function greeting(t: Translate, hour: number): string {
  return t(hour < 12 ? "dashboard.morning" : hour < 18 ? "dashboard.afternoon" : "dashboard.evening");
}

type Stat = { key: string; label: string; value: number; to: string; tone?: "danger" | "warn" | "gold"; icon: IconName };

function stats(d: Dashboard, t: Translate): Stat[] {
  return [
    { key: "households", label: t("dashboard.households"), value: d.households, to: "/households", icon: "households" },
    { key: "patients", label: t("dashboard.patients"), value: d.patients, to: "/patients", icon: "patients" },
    { key: "today", label: t("dashboard.visitsToday"), value: d.visits_today, to: `/checkups?date=${todayIso()}`, icon: "checkups", tone: "gold" },
    { key: "due", label: t("followUps.due"), value: d.follow_ups.due, to: "/follow-ups?state=due", icon: "clock",
      tone: d.follow_ups.due ? "warn" : undefined },
    { key: "overdue", label: t("dashboard.overdue"), value: d.follow_ups.overdue, to: "/follow-ups?state=overdue", icon: "alert",
      tone: d.follow_ups.overdue ? "danger" : undefined },
    { key: "flags", label: t("dashboard.referralFlags"), value: d.referral_flags_open, to: "/referrals", icon: "referrals",
      tone: d.referral_flags_open ? "danger" : undefined },
    { key: "sync", label: t("dashboard.sync"), value: d.unsynced, to: "/sync", icon: "sync" },
  ];
}

type Alert = { key: string; level: "urgent" | "soon" | "info"; text: string; to: string };

function alerts(d: Dashboard, sync: SyncStatus | undefined, t: Translate): Alert[] {
  const list: Alert[] = [];
  if (d.follow_ups.overdue) list.push({ key: "overdue", level: "urgent", to: "/follow-ups?state=overdue", text: t("alerts.overdue", { count: d.follow_ups.overdue }) });
  if (d.referral_flags_open) list.push({ key: "flags", level: "urgent", to: "/referrals", text: t("alerts.flags", { count: d.referral_flags_open }) });
  if (d.follow_ups.due) list.push({ key: "due", level: "soon", to: "/follow-ups?state=due", text: t("alerts.due", { count: d.follow_ups.due }) });
  if (d.low_stock) list.push({ key: "stock", level: "soon", to: "/supplies/request-list", text: t("alerts.lowStock", { count: d.low_stock }) });
  if (d.drafts) list.push({ key: "drafts", level: "info", to: "/checkups?status=draft", text: t("alerts.drafts", { count: d.drafts }) });
  if (sync?.open_bundles) list.push({ key: "bundles", level: "info", to: "/sync", text: t("alerts.bundles", { count: sync.open_bundles }) });
  if (d.unsynced) list.push({ key: "sync", level: "info", to: "/sync", text: t("alerts.unsynced", { count: d.unsynced }) });
  return list;
}

type Activity = { key: string; at: string; icon: IconName; text: string; detail?: string; to: string; badge?: { cls: string; label: string } };

export function DashboardPage() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const today = todayIso();
  const summary = useApi(api.dashboard, []);
  const forms = useApi(api.listForms, []);
  const days = Array.from({ length: 7 }, (_, i) => addDays(today, i - 6));
  const week = useApi(() => Promise.all(days.map((date) => api.listVisits({ date, limit: 1 }).then((p) => p.total))), [today]);
  const report = useApi(() => reportsApi.summary("week", today), [today]);
  const overdue = useApi(() => api.listFollowUps({ state: "overdue", limit: 5 }), []);
  const due = useApi(() => api.listFollowUps({ state: "due", limit: 5 }), []);
  const visits = useApi(() => api.listVisits({ limit: 6 }), []);
  const referrals = useApi(() => referralsApi.list({ limit: 4 }), []);
  const bundles = useApi(syncApi.bundles, []);
  const sync = useApi(syncApi.status, []);
  const supplies = useApi(suppliesApi.list, []);

  if (summary.error) return <LoadError error={summary.error} onRetry={summary.reload} />;
  if (!summary.data) return <Loading />;
  const d = summary.data;
  const formTitle = (type: string) => {
    const form = forms.data?.find((f) => f.form_type === type);
    return form ? pick(form.title, lang) : type;
  };
  const now = new Date();
  const firstName = user?.full_name.split(/\s+/)[0] ?? "";
  const dateLine = now.toLocaleDateString(locale(lang), { weekday: "long", year: "numeric", month: "long", day: "numeric" });

  const weekData = week.data?.map((value, i) => {
    const date = new Date(`${days[i]}T00:00:00`);
    const label = date.toLocaleDateString(locale(lang), { weekday: "short" });
    return { label, value, highlight: days[i] === today, tip: t("dashboard.chartTip", { date: days[i], count: value }) };
  });
  const weekTotal = week.data?.reduce((a, b) => a + b, 0) ?? 0;
  const byForm = report.data
    ? Object.entries(report.data.current.visits.by_form).map(([type, value]) => ({ label: formTitle(type), value, tip: `${formTitle(type)}: ${value}` }))
    : [];

  const tasks = [...(overdue.data?.items ?? []), ...(due.data?.items ?? [])].slice(0, 6);
  const tasksError = overdue.error || due.error;

  const activity: Activity[] = [
    ...(visits.data?.items ?? []).map((v): Activity => ({
      key: `v${v.id}`, at: v.finalized_at ?? v.updated_at, icon: "checkups", to: `/visits/${v.id}`,
      text: t(v.status === "final" ? "activity.visitFinal" : "activity.visitDraft", { name: v.patient_name }),
      detail: formTitle(v.form_type), badge: { cls: `badge-${v.status}`, label: t(`visit.${v.status}`) },
    })),
    ...(referrals.data?.items ?? []).map((r): Activity => ({
      key: `r${r.id}`, at: r.created_at, icon: "referrals", to: `/referrals/${r.id}/slip`,
      text: t("activity.referral", { name: r.patient_name }), detail: r.facility,
      badge: { cls: `badge-${r.urgency}`, label: t(`referrals.urgency.${r.urgency}`) },
    })),
    ...(bundles.data ?? []).map((b): Activity => ({
      key: `b${b.id}`, at: b.acknowledged_at ?? b.created_at, icon: "sync", to: "/sync",
      text: t(b.acknowledged_at ? "activity.synced" : "activity.bundle", { count: b.record_count }),
      badge: b.acknowledged_at ? { cls: "badge-sent", label: t("sync.synced") } : { cls: "badge-pending", label: t("activity.awaiting") },
    })),
  ].sort((a, b) => fromUtcStamp(b.at).getTime() - fromUtcStamp(a.at).getTime()).slice(0, 8);

  const attention = alerts(d, sync.data, t);
  const lowItems = (supplies.data ?? []).filter((s) => s.low).slice(0, 4);
  const syncTotals = sync.data
    ? Object.values(sync.data.records).reduce((acc, c) => ({ pending: acc.pending + c.pending, awaiting: acc.awaiting + c.awaiting, synced: acc.synced + c.synced }), { pending: 0, awaiting: 0, synced: 0 })
    : null;

  return (
    <div className="dashboard">
      <section className="welcome">
        <div>
          <p className="eyebrow">{dateLine}</p>
          <h1>{t("dashboard.greeting", { greeting: greeting(t, now.getHours()), name: firstName })}</h1>
          <p className="muted welcome-line">
            {t("dashboard.overview", { visits: d.visits_today, due: d.follow_ups.due, overdue: d.follow_ups.overdue })}
          </p>
        </div>
        <div className="quick-actions">
          <Link className="btn btn-primary btn-lg" to="/patients?pick=checkup"><Icon name="plus" />{t("dashboard.newCheckup")}</Link>
          <div className="quick-secondary">
            <Link className="btn" to="/households?pick=member"><Icon name="patients" size={18} />{t("dashboard.registerPatient")}</Link>
            <Link className="btn" to="/households/new"><Icon name="households" size={18} />{t("households.register")}</Link>
            <Link className="btn" to="/follow-ups?state=due"><Icon name="followUps" size={18} />{t("dashboard.viewFollowUps")}</Link>
          </div>
        </div>
      </section>

      <nav className="stats" aria-label={t("dashboard.statsLabel")}>
        {stats(d, t).map((s) => (
          <Link key={s.key} to={s.to} className={`stat${s.tone ? ` stat-${s.tone}` : ""}`}>
            <span className="stat-label"><Icon name={s.icon} size={16} />{s.label}</span>
            <span className="stat-value">{s.value}</span>
          </Link>
        ))}
      </nav>

      <div className="dash-grid">
        <div className="dash-main">
          <Panel title={t("dashboard.activityTitle")} action={<Link to="/checkups" className="panel-link">{t("dashboard.allCheckups")}</Link>}>
            <div className="activity-split">
              <div>
                <p className="panel-sub">{t("dashboard.last7", { count: weekTotal })}</p>
                {week.error ? <SectionError onRetry={week.reload} /> : !weekData ? <Loading /> :
                  weekTotal === 0 ? <p className="empty">{t("dashboard.noWeek")}</p> :
                  <ColumnChart data={weekData} summary={t("dashboard.last7", { count: weekTotal })} />}
              </div>
              <div>
                <p className="panel-sub">{t("dashboard.byForm")}</p>
                {report.error ? <SectionError onRetry={report.reload} /> : !report.data ? <Loading /> :
                  byForm.length === 0 ? <p className="empty">{t("reports.nothing")}</p> : <BarList data={byForm} />}
                <p className="panel-sub">{t("dashboard.followUpStatus")}</p>
                <StackedBar label={t("dashboard.followUpStatus")} segments={[
                  { key: "overdue", label: t("followUps.overdue"), value: d.follow_ups.overdue, tone: "danger" },
                  { key: "due", label: t("followUps.due"), value: d.follow_ups.due, tone: "warn" },
                  { key: "upcoming", label: t("followUps.upcoming"), value: d.follow_ups.upcoming, tone: "info" },
                ]} />
              </div>
            </div>
          </Panel>

          <Panel title={t("dashboard.tasksTitle")} action={<Link to="/follow-ups" className="panel-link">{t("dashboard.viewAll")}</Link>}>
            {tasksError ? <SectionError onRetry={() => { overdue.reload(); due.reload(); }} /> :
              !overdue.data || !due.data ? <Loading /> :
              tasks.length === 0 ? <p className="empty">{t("dashboard.noTasks")}</p> : (
                <ul className="rows">
                  {tasks.map((f) => (
                    <li key={f.id} className="row">
                      <span className={`badge badge-${f.state}`}>{t(`followUps.${f.state}`)}</span>
                      <div className="row-main">
                        <Link to={`/patients/${f.patient_id}`} className="row-title">{f.patient_name}</Link>
                        <span className="muted">{[f.reason, f.barangay].filter(Boolean).join(" · ")}</span>
                      </div>
                      <span className="row-meta">{t("followUps.dueOn", { date: f.due_date })}</span>
                      <Link className="btn btn-small" to={f.form_type
                        ? `/patients/${f.patient_id}/visits/new?form=${encodeURIComponent(f.form_type)}` : `/patients/${f.patient_id}`}>
                        {t("followUps.recordVisit")}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
          </Panel>

          <Panel title={t("dashboard.recentActivity")}>
            {visits.error ? <SectionError onRetry={visits.reload} /> : !visits.data ? <Loading /> :
              activity.length === 0 ? <p className="empty">{t("dashboard.noVisits")}</p> : (
                <ol className="feed">
                  {activity.map((a) => (
                    <li key={a.key}>
                      <Link to={a.to} className="feed-item">
                        <span className="feed-icon"><Icon name={a.icon} size={16} /></span>
                        <span className="feed-text">{a.text}{a.detail && <span className="muted"> · {a.detail}</span>}</span>
                        {a.badge && <span className={`badge ${a.badge.cls}`}>{a.badge.label}</span>}
                        <time className="feed-time" dateTime={a.at}>{shortStamp(a.at, now)}</time>
                      </Link>
                    </li>
                  ))}
                </ol>
              )}
          </Panel>
        </div>

        <aside className="dash-side">
          <Panel title={t("dashboard.attention")} className="panel-attention">
            {attention.length === 0 ? <p className="empty"><Icon name="check" size={16} /> {t("dashboard.allClear")}</p> : (
              <ul className="alerts">
                {attention.map((a) => (
                  <li key={a.key}>
                    <Link to={a.to} className={`alert alert-${a.level}`}>
                      <span className="alert-level">{t(`alerts.level.${a.level}`)}</span>
                      <span className="alert-text">{a.text}</span>
                      <Icon name="chevronRight" size={16} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title={t("dashboard.syncTitle")} action={<Link to="/sync" className="panel-link">{t("dashboard.open")}</Link>}>
            {sync.error ? <SectionError onRetry={sync.reload} /> : !syncTotals ? <Loading /> : (
              <>
                <dl className="kv">
                  <div><dt>{t("sync.pending")}</dt><dd>{syncTotals.pending}</dd></div>
                  <div><dt>{t("sync.awaiting")}</dt><dd>{syncTotals.awaiting}</dd></div>
                  <div><dt>{t("sync.synced")}</dt><dd>{syncTotals.synced}</dd></div>
                  <div><dt>{t("sync.lastReceipt")}</dt><dd>{sync.data!.last_acknowledged_at ? shortStamp(sync.data!.last_acknowledged_at, now) : t("sync.never")}</dd></div>
                </dl>
                <p className="hint">{t("dashboard.syncNote")}</p>
              </>
            )}
          </Panel>

          <Panel title={t("dashboard.ai")}>
            <p className={`status-line ${d.ai.available ? "is-ok" : "is-off"}`}>
              <Icon name="cpu" size={18} />
              <strong>{t(d.ai.available ? "ai.ready" : "ai.off")}</strong>
            </p>
            <p className="hint">{d.ai.available && d.ai.model ? t("ai.model", { model: d.ai.model }) : t("ai.manualNote")}</p>
          </Panel>

          <Panel title={t("dashboard.lowStock")} action={<Link to="/supplies" className="panel-link">{t("dashboard.open")}</Link>}>
            {supplies.error ? <SectionError onRetry={supplies.reload} /> : !supplies.data ? <Loading /> :
              supplies.data.length === 0 ? <p className="empty">{t("supplies.none")}</p> :
              lowItems.length === 0 ? <p className="empty">{t("supplies.requestNone")}</p> : (
                <ul className="stock">
                  {lowItems.map((item) => (
                    <li key={item.id}>
                      <Link to={`/supplies/${item.id}`}>{item.name}</Link>
                      <span className="muted">{t("supplies.onHand", { count: item.on_hand, unit: item.unit })}</span>
                      <span className="meter" aria-hidden="true">
                        <span style={{ width: `${Math.min(100, (item.on_hand / Math.max(1, item.target_level)) * 100)}%` }} />
                      </span>
                    </li>
                  ))}
                </ul>
              )}
          </Panel>
        </aside>
      </div>
    </div>
  );
}
