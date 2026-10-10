import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import type { Dashboard } from "../api/types";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthProvider";
import { useI18n } from "../i18n/i18n";
import { LanguageToggle } from "../i18n/LanguageToggle";
import { useOnline } from "../lib/useOnline";
import { AiChip } from "./AiChip";
import { Icon, type IconName } from "./Icon";
import { Logo } from "./Logo";

type NavItem = { to: string; key: string; icon: IconName; end?: boolean; badge?: (d: Dashboard) => number; alert?: boolean };
type NavGroup = { key: string; items: NavItem[] };

const GROUPS: NavGroup[] = [
  { key: "nav.group.overview", items: [{ to: "/", key: "nav.dashboard", icon: "dashboard", end: true }] },
  {
    key: "nav.group.care",
    items: [
      { to: "/households", key: "nav.households", icon: "households" },
      { to: "/patients", key: "nav.patients", icon: "patients" },
      { to: "/checkups", key: "nav.checkups", icon: "checkups", badge: (d) => d.drafts },
      { to: "/follow-ups", key: "nav.followUps", icon: "followUps", badge: (d) => d.follow_ups.overdue + d.follow_ups.due, alert: true },
      { to: "/referrals", key: "nav.referrals", icon: "referrals", badge: (d) => d.referral_flags_open, alert: true },
    ],
  },
  {
    key: "nav.group.operations",
    items: [
      { to: "/supplies", key: "nav.supplies", icon: "supplies", badge: (d) => d.low_stock, alert: true },
      { to: "/reports", key: "nav.reports", icon: "reports" },
      { to: "/sync", key: "nav.sync", icon: "sync", badge: (d) => d.unsynced },
    ],
  },
];

const SECTIONS: Record<string, string> = {
  households: "nav.households", patients: "nav.patients", checkups: "nav.checkups", visits: "nav.checkups",
  "follow-ups": "nav.followUps", referrals: "nav.referrals", supplies: "nav.supplies", reports: "nav.reports",
  sync: "nav.sync", profile: "profile.title", admin: "nav.admin",
};
const COLLAPSE_KEY = "rp.sidebar";

function storedCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

/** Breadcrumb for the current path: Dashboard › Section › (details | new). */
function useCrumbs(): { label: string; to?: string }[] {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const parts = pathname.split("/").filter(Boolean);
  const crumbs: { label: string; to?: string }[] = [{ label: t("nav.dashboard"), to: "/" }];
  if (parts.length === 0) return [{ label: t("nav.dashboard") }];
  const section = SECTIONS[parts[0]];
  if (section) crumbs.push({ label: t(section), to: parts[0] === "visits" ? "/checkups" : `/${parts[0]}` });
  if (parts.length > 1 && parts[0] !== "admin") {
    const last = parts[parts.length - 1];
    crumbs.push({ label: last === "new" ? t("crumb.new") : last === "slip" ? t("slip.title") :
      last === "request-list" ? t("supplies.requestList") : t("crumb.details") });
  }
  delete crumbs[crumbs.length - 1].to;
  return crumbs;
}

function initials(name: string | undefined): string {
  return (name ?? "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("");
}

function ProfileMenu() {
  const { user, signOut } = useAuth();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => { if (!ref.current?.contains(event.target as Node)) setOpen(false); };
    const esc = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return (
    <div className="profile" ref={ref}>
      <button type="button" className="profile-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="avatar" aria-hidden="true">{initials(user?.full_name)}</span>
        <span className="profile-name">{user?.full_name}</span>
        <Icon name="chevronDown" size={16} />
      </button>
      {open && (
        <div className="menu" role="menu">
          <div className="menu-head">
            <strong>{user?.full_name}</strong>
            <span className="muted">{user && t(`users.role.${user.role}`)}</span>
          </div>
          <Link role="menuitem" to="/profile" className="menu-item"><Icon name="user" size={18} />{t("profile.title")}</Link>
          <button role="menuitem" type="button" className="menu-item" onClick={() => void signOut()}>
            <Icon name="logout" size={18} />{t("auth.signOut")}
          </button>
        </div>
      )}
    </div>
  );
}

export function Layout() {
  const { user } = useAuth();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(storedCollapsed);
  const location = useLocation();
  const online = useOnline();
  const crumbs = useCrumbs();
  const summary = useApi(api.dashboard, [location.pathname]);
  const counts = summary.data;
  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    const title = crumbs[crumbs.length - 1]?.label;
    document.title = title && location.pathname !== "/" ? `${title} · ${t("app.name")}` : t("app.name");
  });

  function toggleCollapsed() {
    setCollapsed((value) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, value ? "0" : "1");
      } catch {
        // Not remembered in this browser.
      }
      return !value;
    });
  }

  const groups = user?.role === "admin"
    ? [...GROUPS, { key: "nav.group.admin", items: [{ to: "/admin/users", key: "nav.admin", icon: "accounts" as const }] }]
    : GROUPS;

  return (
    <div className={`shell${open ? " nav-open" : ""}${collapsed ? " collapsed" : ""}`}>
      <aside className="sidebar" id="sidebar">
        <div className="brand">
          <Link to="/" className="brand-link"><Logo compact={collapsed} tone="light" /></Link>
          <button type="button" className="icon-btn drawer-close" aria-label={t("nav.close")} onClick={() => setOpen(false)}>
            <Icon name="close" />
          </button>
        </div>
        <nav aria-label={t("nav.label")} className="nav">
          {groups.map((group) => (
            <div key={group.key} className="nav-group">
              <p className="nav-group-label">{t(group.key)}</p>
              {group.items.map((item) => {
                const count = counts && item.badge ? item.badge(counts) : 0;
                return (
                  <NavLink key={item.to} to={item.to} end={item.end} className="nav-link" title={collapsed ? t(item.key) : undefined}>
                    <Icon name={item.icon} />
                    <span className="nav-text">{t(item.key)}</span>
                    {count > 0 && (
                      <span className={`nav-badge${item.alert ? " nav-badge-alert" : ""}`}>
                        <span aria-hidden="true">{count > 99 ? "99+" : count}</span>
                        <span className="sr-only">{t("nav.badge", { count })}</span>
                      </span>
                    )}
                  </NavLink>
                );
              })}
            </div>
          ))}
        </nav>
        <button type="button" className="collapse-btn" aria-pressed={collapsed} onClick={toggleCollapsed}>
          <Icon name={collapsed ? "chevronRight" : "chevronLeft"} size={18} />
          <span className="nav-text">{t(collapsed ? "nav.expand" : "nav.collapse")}</span>
        </button>
      </aside>
      <button type="button" className="scrim" aria-hidden="true" tabIndex={-1} onClick={() => setOpen(false)} />
      <div className="main">
        <header className="topbar">
          <button type="button" className="icon-btn menu-btn" aria-label={t("nav.menu")} aria-controls="sidebar"
            aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            <Icon name="menu" />
          </button>
          <nav aria-label={t("nav.breadcrumb")} className="crumbs">
            <ol>
              {crumbs.map((crumb, index) => (
                <li key={index}>
                  {crumb.to ? <Link to={crumb.to}>{crumb.label}</Link> : <span aria-current="page">{crumb.label}</span>}
                </li>
              ))}
            </ol>
          </nav>
          <div className="topbar-right">
            <span className={`chip ${online ? "chip-ok" : "chip-off"}`} title={t(online ? "net.onlineNote" : "net.offlineNote")}>
              <Icon name={online ? "wifi" : "wifiOff"} size={16} />
              <span className="chip-text">{t(online ? "net.online" : "net.offline")}</span>
            </span>
            <AiChip />
            {counts && counts.unsynced > 0 && (
              <Link to="/sync" className="chip chip-sync" title={t("dashboard.unsyncedNote")}>
                <Icon name="sync" size={16} />
                <span className="chip-text">{t("sync.chip", { count: counts.unsynced })}</span>
              </Link>
            )}
            <LanguageToggle />
            <ProfileMenu />
          </div>
        </header>
        <main className="content"><Outlet /></main>
      </div>
    </div>
  );
}
