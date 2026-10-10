import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { useI18n } from "../i18n/i18n";
import { LanguageToggle } from "../i18n/LanguageToggle";
import { AiChip } from "./AiChip";

const NAV = [
  { to: "/", key: "nav.dashboard", end: true },
  { to: "/households", key: "nav.households" },
  { to: "/patients", key: "nav.patients" },
  { to: "/follow-ups", key: "nav.followUps" },
  { to: "/referrals", key: "nav.referrals", soon: true },
  { to: "/supplies", key: "nav.supplies", soon: true },
  { to: "/reports", key: "nav.reports", soon: true },
  { to: "/sync", key: "nav.sync", soon: true },
];

export function Layout() {
  const { user, signOut } = useAuth();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);
  return (
    <div className={`shell${open ? " nav-open" : ""}`}>
      <aside className="sidebar">
        <div className="brand"><img src="/icon.svg" alt="" width="32" height="32" /><span>{t("app.name")}</span></div>
        <nav aria-label={t("nav.label")}>
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className="nav-link">
              {t(item.key)}
              {item.soon && <span className="soon-tag">{t("common.soon")}</span>}
            </NavLink>
          ))}
          {user?.role === "admin" && <NavLink to="/admin/users" className="nav-link">{t("nav.admin")}</NavLink>}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <button type="button" className="btn menu-btn" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            {t("nav.menu")}
          </button>
          <div className="topbar-right">
            <AiChip />
            <LanguageToggle />
            <Link to="/profile" className="user-link">{user?.full_name}</Link>
            <button type="button" className="btn btn-ghost" onClick={() => void signOut()}>{t("auth.signOut")}</button>
          </div>
        </header>
        <main className="content"><Outlet /></main>
      </div>
    </div>
  );
}
