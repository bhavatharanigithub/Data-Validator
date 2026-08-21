export type Role = "FIELD_SUPERVISOR" | "SURVEY_ADMIN";

export type PipelineStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED" | "UNAVAILABLE";

export interface BatchItem {
  batch_id: string;
  source: string;
  status: string;
  schema_version: string | null;
  records: number | null;
  columns: number | null;
  parquet_path: string | null;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
  survey_code?: string | null;
  pipeline_status?: string | null;
  pipeline_run_id?: number | null;
  pipeline_version?: string | null;
  confirmed_issues?: number | null;
  investigation_signals?: number | null;
}

export interface Overview {
  available: boolean;
  batch_id: string | null;
  survey_code: string | null;
  total_records: number | null;
  processed: number | null;
  high_risk: number | null;
  medium_risk: number | null;
  low_risk: number | null;
  clean: number | null;
  critical: number | null;
  confirmed_anomalies: number | null;
  review_signals: number | null;
  anomaly_rate: number | null;
  enumerators: number | null;
  fusion_run_id: number | null;
  fusion_status: string | null;
  validation_errors?: number | null;
  unusual_patterns?: number | null;
  investigation_required?: number | null;
  enumerator_alerts?: number | null;
  cluster_alerts?: number | null;
  temporal_alerts?: number | null;
  geographic_alerts?: number | null;
  relationship_alerts?: number | null;
  quality_signals?: Record<string, number> | null;
  pipeline_status?: string | null;
  current_stage?: string | null;
  active_pipeline_run_id?: number | null;
  message: string | null;
}

export interface PipelineStage {
  id: string;
  label: string;
  status: PipelineStatus;
  timestamp: string | null;
  record_count: number | null;
  detail: string | null;
}

export interface AnomalyRow {
  batch_id: string;
  record_id: string;
  risk_score: number;
  severity: string;
  agreement: string;
  evidence_confidence: number;
  enumerator_id: string | null;
  cluster_id: string | null;
  district_id: string | null;
  available_sources: string[];
  missing_sources: string[];
  source_scores: Record<string, number>;
  source_severities: Record<string, string>;
  escalation_applied: boolean;
  anomaly_status?: string;
  classification_reason?: string | null;
  intelligence_classification?: string | null;
  primary_detector?: string | null;
  detector_count?: number | null;
  review_required?: boolean;
  detectors?: string[];
  ai_explanation_status: string;
  ai_explanation_reason: string | null;
}

export interface AnomalyList {
  available: boolean;
  batch_id: string | null;
  fusion_run_id: number | null;
  total: number;
  page: number;
  page_size: number;
  items: AnomalyRow[];
  message: string | null;
}

export interface EvidenceItem {
  source: string;
  code: string | null;
  detector: string | null;
  field: string | null;
  variable: string | null;
  observed_value: unknown;
  expected: string | null;
  score: number | null;
  threshold: number | null;
  severity: string | null;
  model_type: string | null;
  anomaly_score: number | null;
  message: string | null;
}

export interface SourceCard {
  source: string;
  status: string;
  score: number | null;
  severity: string | null;
  detections: number;
  items: EvidenceItem[];
}

export interface RecordDetail {
  available: boolean;
  batch_id: string;
  record_id: string;
  assessment: AnomalyRow | null;
  sources: SourceCard[];
    explanation: {
    status: string;
    reason: string | null;
    primary_reason: string | null;
    secondary_reason: string | null;
    summary: string | null;
    what_it_means?: string | null;
    key_findings: string[];
    evidence_explanations: { source: string; finding: string; severity: string }[];
    recommended_action: string | null;
    limitations: string[];
    explanation_confidence: number | null;
  } | null;
  sirl_available: boolean;
  escalation_applied: boolean;
  escalation_reason: string | null;
  message: string | null;
}

export interface GroupRow {
  id: string;
  district_id: string | null;
  cluster_id: string | null;
  records: number;
  high_risk: number;
  medium_risk: number;
  low_risk: number;
  critical: number;
  anomaly_rate: number | null;
  missingness_rate: number | null;
  enumerators: number | null;
}

export interface GroupList {
  available: boolean;
  batch_id: string | null;
  grain: string;
  items: GroupRow[];
  message: string | null;
  view?: string;
  batch_count?: number | null;
}

export interface GroupDetail extends GroupList {
  group_id: string;
  high_risk_records: AnomalyRow[];
  common_sources: string[];
}

export interface AIHealth {
  configured: boolean;
  provider_reachable: boolean;
  model_configured: boolean;
  status: string;
}

export interface AuthStatus {
  demo: boolean;
  notice: string;
  default_username: string;
  password_configured: boolean;
  cookie_auth?: boolean;
  accounts?: { username: string; role: string; password_matches_username?: boolean }[];
}

export interface AuthUser {
  username: string;
  role: Role;
  display_name: string;
  demo: boolean;
  district_scope: string[];
  cluster_scope: string[];
}

export interface InvestigationItem {
  id: number;
  batch_id: string;
  record_id: string;
  assigned_to: string | null;
  status: string;
  priority: string;
  action: string | null;
  supervisor_notes: string | null;
  finding?: string | null;
  action_taken?: string | null;
  final_classification?: string | null;
  created_by: string;
  enumerator_id: string | null;
  district_id: string | null;
  risk_score: number | null;
  severity: string | null;
  created_at: string | null;
  updated_at: string | null;
  resolved_at: string | null;
}

export interface InvestigationList {
  items: InvestigationItem[];
  kpis: Record<string, number>;
}

export interface AuditEvent {
  id: number;
  investigation_id: number;
  user_id: string;
  action: string;
  previous_status: string | null;
  new_status: string | null;
  note: string | null;
  timestamp: string | null;
}

export interface OrchestratorStage {
  stage: string;
  status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED" | "UNAVAILABLE" | "SKIPPED";
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  engine_run_id: number | null;
  records_processed: number | null;
  detail: Record<string, unknown>;
}

export interface OrchestratorRun {
  pipeline_run_id: number;
  batch_id: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "PARTIAL";
  current_stage: string | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_stage: string | null;
  error_code?: string | null;
  error_message: string | null;
  is_active?: boolean;
  reused: boolean;
  stages: OrchestratorStage[];
  metadata?: Record<string, unknown>;
}

export interface DetectorConfig {
  id: number;
  detector_id: string;
  name: string;
  category: string;
  description: string | null;
  enabled: boolean;
  severity: string;
  thresholds_json: Record<string, unknown> | null;
}

export interface AnomalySummary {
  total: number;
  high: number;
  medium: number;
  low: number;
  validation_errors: number;
  unusual_patterns: number;
  investigation_required: number;
  informational: number;
  by_detector: Record<string, number>;
  detectors_available: string[];
  detectors_skipped: string[];
  skip_reasons: Record<string, string>;
}

export interface OcrRecord {
  record_id: string | null;
  name: string | null;
  age: number | null;
  gender: string | null;
  district: string | null;
  income: number | null;
  occupation: string | null;
  education: string | null;
  marital_status: string | null;
  remarks: string | null;
  page: number;
  needs_review: boolean;
  issues: string[];
  warnings: string[];
  field_confidence: Record<string, number | null>;
  field_confidence_band: Record<string, string>;
  record_confidence: number | null;
  record_confidence_band: string;
}

export interface OcrPreviewResult {
  success: boolean;
  source: string;
  filename: string;
  pages: number;
  records_detected: number;
  records: OcrRecord[];
  records_needing_review: number;
  raw_text: string;
}

export interface OcrImportResult {
  success: boolean;
  source: string;
  batch_id: string;
  rows: number;
  columns: string[];
  schema_version: string;
  records_imported: number;
  records_requiring_review: number;
  status: string;
  pipeline_run_id?: number | null;
  reused?: boolean;
}

