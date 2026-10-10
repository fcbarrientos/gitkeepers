import { useState, type ChangeEvent, type FormEvent } from "react";
import { syncApi } from "../api/modules";
import type { SyncBundle } from "../api/types";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthProvider";
import { BentoCard } from "../components/BentoCard";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { LoadError, Loading } from "../components/Status";
import { errorText, useToast } from "../components/Toast";
import { useI18n } from "../i18n/i18n";
import { downloadFile, readText } from "../lib/download";

const TYPES = ["household", "patient", "visit", "follow_up", "referral", "supply_item", "supply_movement"];

function saveBundle(bundle: SyncBundle) {
  downloadFile(`gitkeepers-${bundle.station_id}-${bundle.bundle_id}.json`, JSON.stringify(bundle, null, 2), "application/json");
}

export function SyncPage() {
  const { t } = useI18n();
  const toast = useToast();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const status = useApi(syncApi.status, []);
  const bundles = useApi(syncApi.bundles, []);
  const [busy, setBusy] = useState(false);
  const [receiptError, setReceiptError] = useState<string | null>(null);
  const [passphrase, setPassphrase] = useState("");
  const [cancelling, setCancelling] = useState<string | null>(null);
  const reload = () => {
    status.reload();
    bundles.reload();
  };

  async function createBundle() {
    setBusy(true);
    try {
      const bundle = await syncApi.createBundle();
      saveBundle(bundle);
      toast(t("sync.bundleCreated", { count: bundle.record_count }));
      reload();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    } finally {
      setBusy(false);
    }
  }

  async function downloadAgain(bundleId: string) {
    try {
      saveBundle(await syncApi.getBundle(bundleId));
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  async function cancelFile() {
    if (!cancelling) return;
    const bundleId = cancelling;
    setCancelling(null);
    try {
      await syncApi.cancelBundle(bundleId);
      toast(t("sync.cancelled"));
      reload();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  async function importReceipt(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // allow picking the same file again
    if (!file) return;
    let receipt: unknown;
    try {
      receipt = JSON.parse(await readText(file));
    } catch {
      setReceiptError(t("sync.notJson"));
      return;
    }
    try {
      await syncApi.sendReceipt(receipt);
      setReceiptError(null);
      toast(t("sync.receiptAccepted"));
      reload();
    } catch (failure) {
      setReceiptError(errorText(failure, t));
    }
  }

  async function savePassphrase(event: FormEvent) {
    event.preventDefault();
    try {
      await syncApi.setPassphrase(passphrase);
      setPassphrase("");
      toast(t("sync.passphraseSaved"));
      reload();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  if (status.error) return <LoadError error={status.error} onRetry={status.reload} />;
  if (!status.data) return <Loading />;
  const s = status.data;
  const total = (key: "pending" | "awaiting") => Object.values(s.records).reduce((sum, c) => sum + c[key], 0);
  const open = (bundles.data ?? []).filter((b) => !b.acknowledged_at);
  const done = (bundles.data ?? []).filter((b) => b.acknowledged_at);

  return (
    <>
      <div className="page-head"><h1>{t("sync.title")}</h1></div>
      <p className="muted">{t("sync.manualNote")}</p>
      <div className="bento">
        <BentoCard title={t("sync.pending")} value={total("pending")} tone={total("pending") ? "gold" : undefined} />
        <BentoCard title={t("sync.awaiting")} value={total("awaiting")} />
        <BentoCard title={t("sync.lastReceipt")} value={s.last_acknowledged_at?.slice(0, 10) ?? t("sync.never")} note={s.station_id} />
      </div>
      <section className="card" style={{ marginTop: 16 }}>
        <div className="table-wrap">
          <table className="table">
            <thead><tr>
              <th scope="col">{t("sync.type")}</th><th scope="col">{t("sync.pending")}</th>
              <th scope="col">{t("sync.awaiting")}</th><th scope="col">{t("sync.synced")}</th>
            </tr></thead>
            <tbody>
              {TYPES.filter((type) => s.records[type]).map((type) => (
                <tr key={type}>
                  <th scope="row">{t(`sync.type.${type}`)}</th>
                  <td>{s.records[type].pending}</td><td>{s.records[type].awaiting}</td><td>{s.records[type].synced}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {isAdmin ? (
          <div className="actions">
            {!s.passphrase_set && <p className="muted">{t("sync.needPassphrase")}</p>}
            <button type="button" className="btn btn-primary" disabled={busy || !s.passphrase_set || total("pending") === 0}
              onClick={() => void createBundle()}>
              {t("sync.createBundle")}
            </button>
          </div>
        ) : <p className="notice">{t("sync.adminOnly")}</p>}
      </section>
      <section className="card">
        <h2>{t("sync.awaitingFiles")}</h2>
        {open.length === 0 ? <p className="empty">{t("sync.noAwaiting")}</p> : (
          <ul className="list">
            {open.map((b) => (
              <li key={b.id} className="list-row">
                <span>{t("sync.fileLine", { date: b.created_at.slice(0, 16), count: b.record_count })}</span>
                {isAdmin && (
                  <div className="row-actions">
                    <button type="button" className="btn btn-small" onClick={() => void downloadAgain(b.id)}>{t("sync.downloadAgain")}</button>
                    <button type="button" className="btn btn-small" onClick={() => setCancelling(b.id)}>{t("sync.cancelFile")}</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        {isAdmin && (
          <>
            <h2>{t("sync.importReceipt")}</h2>
            <label className="stack">{t("sync.receiptFile")}
              <input type="file" accept=".json,application/json" onChange={(e) => void importReceipt(e)} />
            </label>
            {receiptError && <p className="notice notice-error" role="alert">{receiptError}</p>}
          </>
        )}
      </section>
      {done.length > 0 && (
        <section className="card">
          <h2>{t("sync.history")}</h2>
          <ul className="list">
            {done.map((b) => (
              <li key={b.id} className="list-row">
                <span>{t("sync.fileLine", { date: b.acknowledged_at!.slice(0, 16), count: b.record_count })}</span>
                <span className="badge badge-final">{t("sync.synced")}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <ConfirmDialog open={cancelling !== null} title={t("sync.cancelTitle")} body={t("sync.cancelBody")}
        confirmLabel={t("sync.cancelFile")} onConfirm={() => void cancelFile()} onCancel={() => setCancelling(null)} />
      {isAdmin && (
        <form className="card" onSubmit={savePassphrase}>
          <h2>{t("sync.passphraseTitle")}</h2>
          <p className="muted">{t("sync.passphraseHint")}</p>
          {s.passphrase_set && <p>{t("sync.passphraseSet")}</p>}
          <div className="inline-form">
            <label className="stack">{t("sync.passphrase")}
              <input type="password" autoComplete="new-password" required minLength={12} maxLength={200}
                value={passphrase} onChange={(e) => setPassphrase(e.target.value)} />
            </label>
            <button type="submit" className="btn btn-primary">{t("common.save")}</button>
          </div>
        </form>
      )}
    </>
  );
}
