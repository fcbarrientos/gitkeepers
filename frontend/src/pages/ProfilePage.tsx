import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { errorText, useToast } from "../components/Toast";
import { useI18n } from "../i18n/i18n";

export function ProfilePage() {
  const { t } = useI18n();
  const toast = useToast();
  const { user, setUser } = useAuth();
  const [details, setDetails] = useState({ full_name: user?.full_name ?? "", email: user?.email ?? "" });
  const [passwords, setPasswords] = useState({ current: "", next: "" });

  async function saveDetails(event: FormEvent) {
    event.preventDefault();
    try {
      setUser(await api.updateMe({ full_name: details.full_name.trim(), email: details.email.trim() || null }));
      toast(t("profile.saved"));
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  async function changePassword(event: FormEvent) {
    event.preventDefault();
    try {
      await api.changePassword(passwords.current, passwords.next);
      setPasswords({ current: "", next: "" });
      toast(t("profile.passwordChanged"));
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  return (
    <>
      <div className="page-head"><h1>{t("profile.title")}</h1></div>
      <section className="card">
        <h2>{t("profile.details")}</h2>
        <p className="muted">
          {t("profile.username")}: {user?.username} · {t("profile.role")}: {user && t(`users.role.${user.role}`)}
        </p>
        <form className="stack" onSubmit={saveDetails}>
          <label className="stack">{t("auth.fullName")}
            <input required value={details.full_name} onChange={(e) => setDetails({ ...details, full_name: e.target.value })} />
          </label>
          <label className="stack">{t("auth.email")}
            <input type="email" value={details.email} onChange={(e) => setDetails({ ...details, email: e.target.value })} />
          </label>
          <div className="actions"><button type="submit" className="btn btn-primary">{t("common.save")}</button></div>
        </form>
      </section>
      <section className="card">
        <h2>{t("profile.passwordTitle")}</h2>
        <form className="stack" onSubmit={changePassword}>
          <label className="stack">{t("profile.currentPassword")}
            <input type="password" autoComplete="current-password" required value={passwords.current}
              onChange={(e) => setPasswords({ ...passwords, current: e.target.value })} />
          </label>
          <label className="stack">{t("profile.newPassword")}
            <input type="password" autoComplete="new-password" required minLength={8} value={passwords.next}
              onChange={(e) => setPasswords({ ...passwords, next: e.target.value })} />
          </label>
          <div className="actions"><button type="submit" className="btn btn-primary">{t("profile.passwordTitle")}</button></div>
        </form>
      </section>
    </>
  );
}
