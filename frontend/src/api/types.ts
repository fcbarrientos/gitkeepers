export type Role = "admin" | "volunteer";
export type UserStatus = "pending" | "active" | "disabled";

export interface User {
  id: string;
  username: string;
  email: string | null;
  full_name: string;
  role: Role;
  status: UserStatus;
  created_at: string;
  updated_at: string;
}

export interface LoginResponse {
  token: string;
  expires_at: string;
  user: User;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type Sex = "female" | "male" | "intersex" | "unknown";

export interface MemberInput {
  full_name: string;
  birth_date: string | null;
  sex: Sex | null;
  relationship_to_head: string | null;
  contact_number: string | null;
  is_household_head: boolean;
}

export interface Patient extends MemberInput {
  id: string;
  household_id: string;
  created_at: string;
  updated_at: string;
}

export interface PatientSummary extends Patient {
  barangay: string;
  sitio: string | null;
}

export interface HouseholdInput {
  barangay: string;
  sitio: string | null;
  address_line: string | null;
  contact_number: string | null;
  members: MemberInput[];
}

export interface HouseholdSummary {
  id: string;
  barangay: string;
  sitio: string | null;
  address_line: string | null;
  contact_number: string | null;
  updated_at: string;
  member_count: number;
  head_name: string | null;
}

export interface Household {
  id: string;
  barangay: string;
  sitio: string | null;
  address_line: string | null;
  contact_number: string | null;
  created_at: string;
  updated_at: string;
  members: Patient[];
}

export type FieldType = "integer" | "number" | "boolean" | "choice" | "choices";
export type Labels = Record<string, string>;

export interface FormField {
  name: string;
  type: FieldType;
  label: Labels;
  required?: boolean;
  ai?: boolean;
  min?: number | null;
  max?: number | null;
  options?: string[] | null;
}

export interface FormDefinition {
  form_type: string;
  title: Labels;
  verification: string;
  default_follow_up_days: number;
  fields: FormField[];
}

export interface AIStatus {
  available: boolean;
  model: string | null;
}

export type FieldValue = number | boolean | string | string[] | null;
export type Values = Record<string, FieldValue>;

export interface Suggestion {
  suggestion_id: string;
  form_type: string;
  values: Values;
  missing: string[];
  problems: string[];
}

export type Source = "manual" | "ai_accepted" | "ai_edited";
export type VisitStatus = "draft" | "final";

export interface Visit {
  id: string;
  patient_id: string;
  form_type: string;
  visit_date: string;
  status: VisitStatus;
  values: Values;
  sources: Record<string, Source>;
  note: string | null;
  suggestion_id: string | null;
  recorded_by: string;
  created_at: string;
  updated_at: string;
  finalized_at: string | null;
}

export interface VisitSummary extends Visit {
  patient_name: string;
}

export interface VisitInput {
  form_type?: string;
  visit_date: string;
  values: Values;
  note: string | null;
  status: VisitStatus;
  suggestion_id: string | null;
  ai_accepted_fields: string[];
  follow_up?: { due_date: string; reason: string | null };
  completes_follow_up_id?: string;
}

export type FollowUpState = "overdue" | "due" | "upcoming" | "completed" | "cancelled";

export interface FollowUp {
  id: string;
  patient_id: string;
  patient_name: string;
  barangay: string;
  source_visit_id: string | null;
  form_type: string | null;
  due_date: string;
  reason: string | null;
  status: "scheduled" | "completed" | "cancelled";
  state: FollowUpState;
  completed_visit_id: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Dashboard {
  follow_ups: { overdue: number; due: number; upcoming: number };
  visits_today: number;
  drafts: number;
  households: number;
  patients: number;
  ai: AIStatus;
}
