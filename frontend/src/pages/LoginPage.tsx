import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { AuthScreen } from "../components/AuthScreen";
import { errorText } from "../components/Toast";
import { useI18n } from "../i18n/i18n";

export function LoginPage() {
  const { t } = useI18n();
  const { user, signIn } = useAuth();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to={from} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(login.trim(), password); // the re-render redirects
    } catch (failure) {
      setError(errorText(failure, t));
      setBusy(false);
    }
  }

  return (
    <AuthScreen title={t("auth.signIn")}>
      <form className="stack" onSubmit={submit}>
        <label className="stack">{t("auth.login")}
          <input autoComplete="username" required value={login} onChange={(e) => setLogin(e.target.value)} />
        </label>
        <label className="stack">{t("auth.password")}
          <input type="password" autoComplete="current-password" required value={password}
            onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p className="notice notice-error" role="alert">{error}</p>}
        <button type="submit" className="btn btn-primary" disabled={busy}>{t("auth.signIn")}</button>
      </form>
      <p>{t("auth.noAccount")} <Link to="/signup">{t("auth.createAccount")}</Link></p>
    </AuthScreen>
  );
}
