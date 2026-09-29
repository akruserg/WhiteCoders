// Типы ответов API (по to_dict() моделей бэкенда и api.txt).

export type RoleCode = "admin" | "teacher" | "student";

export interface Role { id: number; code: RoleCode; name?: string; description?: string }
export interface Category { id: number; code: string; name: string; parent_id: number | null; service_code: string | null; is_active: boolean }
export interface GroupRef { id: string; name: string }

export interface User {
  id: string; username: string; full_name: string; email: string | null; role_id: number;
  mfa_enabled: boolean; is_active: boolean; is_blocked: boolean;
  pd_consent_at: string | null; anonymized_at: string | null; failed_attempts: number;
  last_login_at: string | null; created_at: string;
}
export interface Profile extends User {
  role: Role; permissions: string[]; consent_required: boolean;
  service_scope: Category[]; groups: GroupRef[];
}
export interface LoginResult {
  access_token: string; refresh_token: string; expires_in: number; user: Profile;
}
export interface MfaChallenge { mfa_required: true; mfa_token: string; expires_in: number }

export interface Paged<T> { items: T[]; page: number; per_page: number; total: number; pages: number }
export interface Listed<T> { items: T[]; total: number }

export type SessionStatus = "planned" | "running" | "finished";
export interface Session {
  id: string; title: string; teacher_id: string; group_id: string | null;
  mode: "cards" | "card_actions" | "mixed"; question_source: "generated" | "student" | "mixed";
  status: SessionStatus; grading_profile_id: string | null; category_ids: number[];
  difficulty_min: number; difficulty_max: number; time_limit_sec: number | null;
  settings: Record<string, any>; started_at: string | null; finished_at: string | null; created_at: string;
  participants: { user_id: string; full_name: string | null; joined_at: string | null }[];
  channel: "text" | "voip";
}

export type AttemptStatus = "issued" | "in_progress" | "submitted" | "evaluated" | "expired";
export interface Attempt {
  id: string; session_id: string; user_id: string; scenario_id: string; seq: number;
  status: AttemptStatus; issued_at: string; started_at: string | null; submitted_at: string | null;
  duration_ms: number | null; time_limit_sec: number; answer: Record<string, any>; actions: any[];
  score: number | null; passed: boolean | null; final_score: number | null;
}
export interface Call {
  id: string; attempt_id: string; channel: "text" | "voip"; sip_call_id: string | null; caller_number: string;
  status: "ringing" | "answered" | "finished" | string; ring_at: string; answer_at: string | null;
  degraded?: boolean; sip_server?: string | null; sip?: Record<string, any> | null; ring_timeout_sec?: number | null;
}
export interface CallMessage { id: number; call_id: string; author: "caller" | "operator"; text: string; created_at: string }

export interface TemplateField {
  key: string; label: string; type: "text" | "textarea" | "phone" | "select" | "multiselect";
  required: boolean; weight: number; options?: string[];
}
export interface NextCard {
  attempt: Attempt; call: Call;
  scenario: { id: string; category_id: number; difficulty: number; legend: Record<string, any> };
  template_fields: TemplateField[]; time_limit_sec: number;
}

export interface AttemptErrorItem {
  kind: string; field_key: string | null; severity: number; message: string;
  expected: unknown; actual: unknown; position?: unknown;
}
export interface AttemptResult {
  attempt_id: string; session_id: string; seq: number; status: AttemptStatus;
  score: number | null; auto_score: number | null; expert_score: number | null; expert_comment: string | null;
  passed: boolean | null; duration_ms: number | null; time_limit_sec: number; delta_sec: number;
  breakdown: Record<string, any>; errors: AttemptErrorItem[]; details_hidden?: boolean;
  answer?: Record<string, any>; actions?: any[]; reference_card?: Record<string, any>; reference_actions?: any[];
}

export interface Scenario {
  id: string; title: string; category_id: number; template_id: string; difficulty: number;
  origin: "ai" | "manual" | "imported" | "student"; status: "draft" | "pending_review" | "validated" | "rejected" | string;
  legend: Record<string, any>; reference_card: Record<string, any>; reference_actions: any[];
  time_limit_sec: number | null; created_at: string; updated_at: string;
}
