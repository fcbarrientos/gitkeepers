import type { ReactNode } from "react";
import { useI18n } from "../i18n/i18n";
import { LanguageToggle } from "../i18n/LanguageToggle";

export function AuthScreen({ title, children }: { title: string; children: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="auth-screen">
      <main className="auth-card">
        <div className="brand">
          <span><img src="/icon.svg" alt="" width="32" height="32" /> {t("app.name")}</span>
          <LanguageToggle />
        </div>
        <h1>{title}</h1>
        {children}
      </main>
    </div>
  );
}
