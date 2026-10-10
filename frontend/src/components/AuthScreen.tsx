import type { ReactNode } from "react";
import { useI18n } from "../i18n/i18n";
import { LanguageToggle } from "../i18n/LanguageToggle";
import { Logo } from "./Logo";

export function AuthScreen({ title, children }: { title: string; children: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="auth-screen">
      <section className="auth-aside" aria-hidden="true">
        <Logo tone="light" />
        <p className="auth-tagline">{t("app.tagline")}</p>
        <ul className="auth-points">
          <li>{t("auth.point.offline")}</li>
          <li>{t("auth.point.ai")}</li>
          <li>{t("auth.point.sync")}</li>
        </ul>
      </section>
      <main className="auth-card">
        <div className="auth-top">
          <span className="auth-logo-small"><Logo /></span>
          <LanguageToggle />
        </div>
        <h1>{title}</h1>
        {children}
      </main>
    </div>
  );
}
