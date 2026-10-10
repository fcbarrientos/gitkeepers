import type {
  AIStatus, Dashboard, FollowUp, FormDefinition, Household, HouseholdInput, HouseholdSummary, LoginResponse,
  MemberInput, Page, Patient, PatientSummary, Role, Suggestion, User, Visit, VisitInput, VisitSummary,
} from "./types";

/** A response the backend rejected; `messages` are safe to show to the user. */
export class ApiError extends Error {
  constructor(public status: number, public messages: string[]) {
    super(messages.join("; ") || `HTTP ${status}`);
  }
}

/** The local server could not be reached at all. */
export class NetworkError extends Error {
  constructor() {
    super("network");
  }
}

type Handlers = { getToken: () => string | null; onUnauthorized: () => void };
let handlers: Handlers = { getToken: () => null, onUnauthorized: () => {} };

export function configureClient(next: Handlers): void {
  handlers = next;
}

type ValidationItem = { loc?: unknown[]; msg?: string };

function messagesFrom(detail: unknown, status: number): string[] {
  if (typeof detail === "string") return [detail];
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (typeof item === "string") return item;
      const { loc = [], msg = "invalid" } = item as ValidationItem;
      const where = loc.filter((part) => part !== "body").join(".");
      return where ? `${where}: ${msg}` : msg;
    });
  }
  return [`HTTP ${status}`];
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = handlers.getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new NetworkError();
  }
  if (response.status === 204) return undefined as T;
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && token) handlers.onUnauthorized();
    throw new ApiError(response.status, messagesFrom((data as { detail?: unknown } | null)?.detail, response.status));
  }
  return data as T;
}

type Params = Record<string, string | number | null | undefined>;

export function qs(params: Params = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

const id = encodeURIComponent;

export const api = {
  signup: (body: { username: string; password: string; full_name: string; email: string | null }) =>
    request<User>("POST", "/auth/signup", body),
  login: (login: string, password: string) => request<LoginResponse>("POST", "/auth/login", { login, password }),
  logout: () => request<void>("POST", "/auth/logout"),
  me: () => request<User>("GET", "/auth/me"),
  updateMe: (body: { full_name?: string; email?: string | null }) => request<User>("PATCH", "/me", body),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("POST", "/me/password", { current_password, new_password }),
  listUsers: (params: Params = {}) => request<Page<User>>("GET", `/users${qs(params)}`),
  updateUser: (userId: string, body: { status?: "active" | "disabled"; role?: Role }) =>
    request<User>("PATCH", `/users/${id(userId)}`, body),
  resetPassword: (userId: string, new_password: string) =>
    request<void>("POST", `/users/${id(userId)}/password`, { new_password }),

  dashboard: () => request<Dashboard>("GET", "/dashboard"),
  listVisits: (params: Params = {}) => request<Page<VisitSummary>>("GET", `/visits${qs(params)}`),

  listHouseholds: (params: Params = {}) => request<Page<HouseholdSummary>>("GET", `/households${qs(params)}`),
  getHousehold: (householdId: string) => request<Household>("GET", `/households/${id(householdId)}`),
  createHousehold: (body: HouseholdInput) => request<Household>("POST", "/households", body),
  addMember: (householdId: string, body: MemberInput) =>
    request<Patient>("POST", `/households/${id(householdId)}/members`, body),
  listPatients: (params: Params = {}) => request<Page<PatientSummary>>("GET", `/patients${qs(params)}`),
  getPatient: (patientId: string) => request<PatientSummary>("GET", `/patients/${id(patientId)}`),

  listForms: () => request<FormDefinition[]>("GET", "/forms"),
  getForm: (formType: string) => request<FormDefinition>("GET", `/forms/${id(formType)}`),
  aiStatus: () => request<AIStatus>("GET", "/ai/status"),
  suggest: (patientId: string, form_type: string, note: string) =>
    request<Suggestion>("POST", `/patients/${id(patientId)}/suggestions`, { form_type, note }),
  createVisit: (patientId: string, body: VisitInput) =>
    request<Visit>("POST", `/patients/${id(patientId)}/visits`, body),
  updateVisit: (visitId: string, body: VisitInput) => request<Visit>("PATCH", `/visits/${id(visitId)}`, body),
  getVisit: (visitId: string) => request<Visit>("GET", `/visits/${id(visitId)}`),
  listPatientVisits: (patientId: string, params: Params = {}) =>
    request<Page<Visit>>("GET", `/patients/${id(patientId)}/visits${qs(params)}`),

  listFollowUps: (params: Params = {}) => request<Page<FollowUp>>("GET", `/follow-ups${qs(params)}`),
  updateFollowUp: (followUpId: string, body: { due_date?: string; reason?: string | null; status?: "cancelled" }) =>
    request<FollowUp>("PATCH", `/follow-ups/${id(followUpId)}`, body),
  completeFollowUp: (followUpId: string) => request<FollowUp>("POST", `/follow-ups/${id(followUpId)}/complete`, {}),
};
