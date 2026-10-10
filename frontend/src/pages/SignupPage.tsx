import { useState, type ChangeEvent, type FormEvent } from "react";
import { Link, Navigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { AuthScreen } from "../components/AuthScreen";
import { errorText } from "../components/Toast";
import { useI18n } from "../i18n/i18n";

export function SignupPage() {
  const { t } = useI18n();
  const { user, signIn } = useAuth();
  const [form, setForm] = useState({ username: "", full_name: "", email: "", password: "" });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to="/" replace />;

  const field = (name: keyof typeof form) => ({
    value: form[name],
    onChange: (e: ChangeEvent<HTMLInputElement>) => setForm({ ...form, [name]: e.target.value }),
  });

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api.signup({
        username: form.username.trim(), full_name: form.full_name.trim(),
        email: form.email.trim() || null, password: form.password,
      });
      if (created.status === "active") await signIn(form.username.trim(), form.password); // first account: admin
      else setPending(true);
    } catch (failure) {
      setError(errorText(failure, t));
    }
    setBusy(false);
  }

  if (pending) {
    return (
      <AuthScreen title={t("auth.pendingTitle")}>
        <p>{t("auth.pendingBody")}</p>
        <Link to="/login" className="btn btn-primary">{t("auth.backToSignIn")}</Link>
      </AuthScreen>
    );
  }
  return (
    <AuthScreen title={t("auth.signupTitle")}>
      <form className="stack" onSubmit={submit}>
        <label className="stack">{t("auth.username")}<input autoComplete="username" required minLength={3} {...field("username")} /></label>
        <label className="stack">{t("auth.fullName")}<input autoComplete="name" required {...field("full_name")} /></label>
        <label className="stack">{t("auth.email")}<input type="email" autoComplete="email" {...field("email")} /></label>
        <label className="stack">{t("auth.password")}
          <input type="password" autoComplete="new-password" required minLength={8} aria-describedby="password-hint" {...field("password")} />
        </label>
        <p id="password-hint" className="hint">{t("auth.passwordHint")}</p>
        {error && <p className="notice notice-error" role="alert">{error}</p>}
        <button type="submit" className="btn btn-primary" disabled={busy}>{t("auth.createAccount")}</button>
      </form>
      <p>{t("auth.haveAccount")} <Link to="/login">{t("auth.signIn")}</Link></p>
    </AuthScreen>
  );
}
