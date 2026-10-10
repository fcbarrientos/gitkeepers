import bp from "../../../backend/forms/bp_followup.json";
import child from "../../../backend/forms/child_growth.json";
import type { Dashboard, FollowUp, FormDefinition, Household, Page, PatientSummary, User, Visit } from "../api/types";

export const bpForm = bp as unknown as FormDefinition;
export const childForm = child as unknown as FormDefinition;

const stamp = "2026-10-01 08:00:00";

export const admin: User = {
  id: "u1", username: "admin", email: null, full_name: "Ada Admin", role: "admin", status: "active",
  created_at: stamp, updated_at: stamp,
};
export const volunteer: User = { ...admin, id: "u2", username: "bhw.ben", full_name: "Ben Volunteer", role: "volunteer" };

export const patient: PatientSummary = {
  id: "p1", household_id: "h1", full_name: "Ana Dela Cruz", birth_date: "1995-03-14", sex: "female",
  relationship_to_head: null, contact_number: "09171234567", is_household_head: true,
  created_at: stamp, updated_at: stamp, barangay: "San Roque", sitio: "Malinis",
};

export const household: Household = {
  id: "h1", barangay: "San Roque", sitio: null, address_line: null, contact_number: null,
  created_at: stamp, updated_at: stamp, members: [patient],
};

export const dashboard: Dashboard = {
  follow_ups: { overdue: 3, due: 1, upcoming: 4 }, visits_today: 2, drafts: 1, households: 12, patients: 40,
  ai: { available: true, model: "Qwen3-4B-Q4_K_M.gguf" },
};

export function page<T>(items: T[]): Page<T> {
  return { items, total: items.length, limit: 25, offset: 0 };
}

export function visit(overrides: Partial<Visit> = {}): Visit {
  return {
    id: "v1", patient_id: "p1", form_type: "bp_followup", visit_date: "2026-10-10", status: "draft",
    values: {}, sources: {}, note: null, suggestion_id: null, recorded_by: "u1",
    created_at: stamp, updated_at: stamp, finalized_at: null, ...overrides,
  };
}

export function followUp(overrides: Partial<FollowUp> = {}): FollowUp {
  return {
    id: "f1", patient_id: "p1", patient_name: "Ana Dela Cruz", barangay: "San Roque", source_visit_id: null,
    form_type: "bp_followup", due_date: "2026-10-05", reason: "BP recheck", status: "scheduled", state: "overdue",
    completed_visit_id: null, completed_at: null, created_at: stamp, updated_at: stamp, ...overrides,
  };
}
