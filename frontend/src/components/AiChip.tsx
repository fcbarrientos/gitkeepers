import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useI18n } from "../i18n/i18n";

export function AiChip() {
  const { t } = useI18n();
  const { data } = useApi(api.aiStatus, []);
  if (!data) return null;
  return (
    <span className={`chip ${data.available ? "chip-ok" : "chip-off"}`} title={data.model ?? t("ai.manualNote")}>
      {t(data.available ? "ai.ready" : "ai.off")}
    </span>
  );
}
