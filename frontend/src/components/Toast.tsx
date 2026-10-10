import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { ApiError, NetworkError } from "../api/client";
import type { Translate } from "../i18n/i18n";

type Kind = "info" | "error";
type Toast = { id: number; text: string; kind: Kind };
type Show = (text: string, kind?: Kind) => void;

const ToastContext = createContext<Show>(() => {});
let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const show = useCallback<Show>((text, kind = "info") => {
    const id = nextId++;
    setToasts((current) => [...current, { id, text, kind }]);
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 5000);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast-${toast.kind}`} role={toast.kind === "error" ? "alert" : "status"}>
            {toast.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

/** One line for a failed request, safe to show. */
export function errorText(error: unknown, t: Translate): string {
  if (error instanceof NetworkError) return t("server.downTitle");
  if (error instanceof ApiError) return error.messages.join(" ");
  return t("common.unexpected");
}
