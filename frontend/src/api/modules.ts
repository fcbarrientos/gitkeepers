import { qs, request } from "./client";
import type {
  Page, Period, Referral, ReferralFlag, ReferralInput, ReportDraft, ReportSummary, RequestItem, SupplyItem,
  SupplyItemInput, SupplyMovement, SyncBundle, SyncBundleSummary, SyncStatus, MovementKind,
} from "./types";

type Params = Record<string, string | number | null | undefined>;
const id = encodeURIComponent;

export const referralsApi = {
  listFlags: (params: Params = {}) => request<ReferralFlag[]>("GET", `/referral-flags${qs(params)}`),
  getFlag: (flagId: string) => request<ReferralFlag>("GET", `/referral-flags/${id(flagId)}`),
  dismissFlag: (flagId: string, note: string | null) =>
    request<ReferralFlag>("POST", `/referral-flags/${id(flagId)}/dismiss`, { note }),
  list: (params: Params = {}) => request<Page<Referral>>("GET", `/referrals${qs(params)}`),
  get: (referralId: string) => request<Referral>("GET", `/referrals/${id(referralId)}`),
  create: (body: ReferralInput) => request<Referral>("POST", "/referrals", body),
};

export const suppliesApi = {
  list: () => request<SupplyItem[]>("GET", "/supplies"),
  get: (itemId: string) => request<SupplyItem>("GET", `/supplies/${id(itemId)}`),
  create: (body: SupplyItemInput) => request<SupplyItem>("POST", "/supplies", body),
  update: (itemId: string, body: Partial<SupplyItemInput> & { active?: boolean }) =>
    request<SupplyItem>("PATCH", `/supplies/${id(itemId)}`, body),
  movements: (itemId: string, params: Params = {}) =>
    request<Page<SupplyMovement>>("GET", `/supplies/${id(itemId)}/movements${qs(params)}`),
  addMovement: (itemId: string, body: { kind: MovementKind; quantity: number; movement_date: string; note: string | null }) =>
    request<SupplyMovement>("POST", `/supplies/${id(itemId)}/movements`, body),
  requestList: () => request<RequestItem[]>("GET", "/supplies/request-list"),
};

export const reportsApi = {
  summary: (period: Period, date: string) => request<ReportSummary>("GET", `/reports/summary${qs({ period, date })}`),
  drafts: (period: Period, date: string) => request<ReportDraft[]>("GET", `/reports/drafts${qs({ period, date })}`),
  createAiDraft: (period: Period, date: string) => request<ReportDraft>("POST", "/reports/drafts", { period, date }),
  createManualDraft: (period: Period, date: string, text: string) =>
    request<ReportDraft>("POST", "/reports/drafts/manual", { period, date, text }),
  updateDraft: (draftId: string, body: { text?: string; status?: "approved" }) =>
    request<ReportDraft>("PATCH", `/reports/drafts/${id(draftId)}`, body),
};

export const syncApi = {
  status: () => request<SyncStatus>("GET", "/sync/status"),
  bundles: () => request<SyncBundleSummary[]>("GET", "/sync/bundles"),
  createBundle: () => request<SyncBundle>("POST", "/sync/bundles"),
  getBundle: (bundleId: string) => request<SyncBundle>("GET", `/sync/bundles/${id(bundleId)}`),
  cancelBundle: (bundleId: string) => request<void>("POST", `/sync/bundles/${id(bundleId)}/cancel`),
  sendReceipt: (receipt: unknown) => request<SyncBundleSummary>("POST", "/sync/receipts", receipt),
  setPassphrase: (passphrase: string) => request<void>("PUT", "/sync/settings", { passphrase }),
};
