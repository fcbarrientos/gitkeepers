import { ApiError, NetworkError } from "../api/client";
import { useI18n } from "../i18n/i18n";

export function Loading() {
  const { t } = useI18n();
  return <p className="loading" role="status">{t("common.loading")}</p>;
}

export function ServerDown({ onRetry }: { onRetry: () => void }) {
  const { t } = useI18n();
  return (
    <div className="server-down" role="alert">
      <h1>{t("server.downTitle")}</h1>
      <p>{t("server.downBody")}</p>
      <button type="button" className="btn btn-primary" onClick={onRetry}>{t("common.retry")}</button>
    </div>
  );
}

export function LoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { t } = useI18n();
  if (error instanceof NetworkError) return <ServerDown onRetry={onRetry} />;
  const messages = error instanceof ApiError ? error.messages : [t("common.unexpected")];
  return (
    <div className="notice notice-error" role="alert">
      {messages.map((message) => <p key={message}>{message}</p>)}
      <button type="button" className="btn" onClick={onRetry}>{t("common.retry")}</button>
    </div>
  );
}
