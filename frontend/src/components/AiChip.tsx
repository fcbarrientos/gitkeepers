import { useEffect } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useI18n } from "../i18n/i18n";
import { Icon } from "./Icon";

const RECHECK_MS = 60_000;

/** Local AI (Ollama) status, rechecked every minute: checking, ready or unavailable. */
export function AiChip() {
  const { t } = useI18n();
  const { data, error, reload } = useApi(api.aiStatus, []);
  useEffect(() => {
    const timer = window.setInterval(reload, RECHECK_MS);
    return () => window.clearInterval(timer);
  }, [reload]);
  const state = data ? (data.available ? "ok" : "off") : error ? "off" : "wait";
  const label = state === "ok" ? t("ai.ready") : state === "off" ? t("ai.off") : t("ai.checking");
  const title = data?.model ? t("ai.model", { model: data.model }) : t("ai.manualNote");
  return (
    <span className={`chip chip-${state}`} title={title}>
      <Icon name="cpu" size={16} />
      <span className="chip-text">{label}</span>
    </span>
  );
}
