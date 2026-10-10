import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Role, User } from "../api/types";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthProvider";
import { SearchBox } from "../components/SearchBox";
import { LoadError, Loading } from "../components/Status";
import { errorText, useToast } from "../components/Toast";
import { useI18n } from "../i18n/i18n";

export function UsersPage() {
  const { t } = useI18n();
  const toast = useToast();
  const { user: me } = useAuth();
  const [q, setQ] = useState("");
  const list = useApi(() => api.listUsers({ q, limit: 100 }), [q]);
  const [resetFor, setResetFor] = useState<User | null>(null);
  const [newPassword, setNewPassword] = useState("");

  async function change(account: User, changes: { status?: "active" | "disabled"; role?: Role }) {
    try {
      await api.updateUser(account.id, changes);
      toast(t("users.updated"));
      list.reload();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  async function reset(event: FormEvent) {
    event.preventDefault();
    if (!resetFor) return;
    try {
      await api.resetPassword(resetFor.id, newPassword);
      toast(t("users.passwordReset"));
      setResetFor(null);
      setNewPassword("");
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  return (
    <>
      <div className="page-head"><h1>{t("users.title")}</h1></div>
      <SearchBox value={q} label={t("users.search")} onSearch={setQ} />
      {list.error ? <LoadError error={list.error} onRetry={list.reload} /> : !list.data ? <Loading /> : (
        <ul className="list">
          {list.data.items.map((account) => (
            <li key={account.id} className="list-row">
              <div><strong>{account.full_name}</strong> <span className="muted">@{account.username}</span></div>
              <span className={`badge badge-${account.status}`}>{t(`users.status.${account.status}`)}</span>
              <span className="badge">{t(`users.role.${account.role}`)}</span>
              <div className="row-actions">
                {account.status !== "active" && (
                  <button type="button" className="btn btn-small btn-primary" onClick={() => void change(account, { status: "active" })}>
                    {t(account.status === "pending" ? "users.approve" : "users.enable")}
                  </button>
                )}
                {account.status === "active" && account.id !== me?.id && (
                  <button type="button" className="btn btn-small" onClick={() => void change(account, { status: "disabled" })}>
                    {t("users.disable")}
                  </button>
                )}
                {account.id !== me?.id && (
                  <button type="button" className="btn btn-small"
                    onClick={() => void change(account, { role: account.role === "admin" ? "volunteer" : "admin" })}>
                    {t(account.role === "admin" ? "users.makeVolunteer" : "users.makeAdmin")}
                  </button>
                )}
                <button type="button" className="btn btn-small" onClick={() => { setResetFor(account); setNewPassword(""); }}>
                  {t("users.resetPassword")}
                </button>
              </div>
              {resetFor?.id === account.id && (
                <form className="inline-form" onSubmit={reset}>
                  <label className="stack">{t("users.newPassword", { name: account.full_name })}
                    <input type="password" autoComplete="new-password" required minLength={8} value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)} />
                  </label>
                  <button type="submit" className="btn btn-small btn-primary">{t("common.save")}</button>
                  <button type="button" className="btn btn-small" onClick={() => setResetFor(null)}>{t("common.cancel")}</button>
                </form>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
