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
  referral_flags_open: number;
  low_stock: number;
  unsynced: number;
  ai: AIStatus;
}

export type Urgency = "urgent" | "routine";

export interface ReferralFlag {
  id: string;
  visit_id: string;
  patient_id: string;
  patient_name: string;
  rule_id: string;
  reason_en: string;
  reason_fil: string;
  urgency: Urgency;
  status: "open" | "referred" | "dismissed";
  dismiss_note: string | null;
  created_at: string;
  form_type: string;
  visit_date: string;
}

export interface Referral {
  id: string;
  patient_id: string;
  patient_name: string;
  birth_date: string | null;
  sex: Sex | null;
  barangay: string;
  sitio: string | null;
  flag_id: string | null;
  facility: string;
  reason: string;
  urgency: Urgency;
  notes: string | null;
  status: "issued" | "sent";
  created_by: string;
  created_by_name: string;
  created_at: string;
  updated_at: string;
  visit: { id: string; form_type: string; visit_date: string; values: Values } | null;
}

export interface ReferralInput {
  patient_id: string;
  flag_id: string | null;
  facility: string;
  reason: string;
  urgency: Urgency;
  notes: string | null;
}

export interface SupplyItem {
  id: string;
  name: string;
  unit: string;
  low_stock_threshold: number;
  target_level: number;
  active: boolean;
  on_hand: number;
  low: boolean;
  created_at: string;
  updated_at: string;
}

export interface SupplyItemInput {
  name: string;
  unit: string;
  low_stock_threshold: number;
  target_level: number;
}

export type MovementKind = "received" | "distributed" | "adjusted";

export interface SupplyMovement {
  id: string;
  item_id: string;
  kind: MovementKind;
  quantity: number;
  movement_date: string;
  note: string | null;
  recorded_by: string;
  recorded_by_name: string;
  created_at: string;
}

export interface RequestItem extends SupplyItem {
  request_quantity: number;
}

export type Period = "week" | "month";

export interface ReportFigures {
  start: string;
  end: string;
  visits: { total: number; final: number; by_form: Record<string, number> };
  new_households: number;
  new_patients: number;
  follow_ups_completed: number;
  follow_ups_overdue: number;
  referral_flags: number;
  referrals_issued: number;
  referrals_by_reason: Record<string, number>;
  supplies: { name: string; unit: string; received: number; distributed: number }[];
  low_stock_items: string[];
}

export interface ReportSummary {
  period: Period;
  current: ReportFigures;
  previous: ReportFigures;
  unsynced_records: number;
}

export interface ReportDraft {
  id: string;
  period: Period;
  start_date: string;
  end_date: string;
  figures: ReportSummary;
  text: string;
  status: "draft" | "approved";
  model: string | null;
  created_by: string;
  approved_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface SyncCounts {
  pending: number;
  awaiting: number;
  synced: number;
}

export interface SyncStatus {
  station_id: string;
  passphrase_set: boolean;
  records: Record<string, SyncCounts>;
  last_acknowledged_at: string | null;
  open_bundles: number;
}

export interface SyncBundleSummary {
  id: string;
  record_count: number;
  created_at: string;
  acknowledged_at: string | null;
  created_by_name: string;
}

export interface SyncBundle {
  bundle_id: string;
  station_id: string;
  record_count: number;
  [key: string]: unknown;
}
