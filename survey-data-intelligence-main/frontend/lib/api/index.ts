import { apiGet, apiPatch, apiPost, apiPostForm } from "./client";
import type {
  AIHealth,
  AnomalyList,
  AnomalySummary,
  AuditEvent,
  AuthStatus,
  AuthUser,
  BatchItem,
  DetectorConfig,
  GroupDetail,
  GroupList,
  InvestigationItem,
  InvestigationList,
  OcrImportResult,
  OcrPreviewResult,
  OcrRecord,
  OrchestratorRun,
  Overview,
  PipelineStage,
  RecordDetail,
} from "./types";

export async function getHealth(): Promise<{ status: string }> {
  return apiGet("/api/health");
}

export async function getAiHealth(): Promise<AIHealth> {
  return apiGet("/api/ai/health");
}

export async function getAuthStatus(): Promise<AuthStatus> {
  return apiGet("/api/auth/status");
}

export async function register(username: string, password: string, display_name: string) {
  return apiPost<{ success: boolean; username: string; role: string; message: string }>(
    "/api/auth/register",
    { username, password, display_name }
  );
}

export async function login(username: string, password: string) {
  return apiPost<{ success: boolean; demo: boolean; notice: string; username: string; role: string }>(
    "/api/auth/login",
    { username, password }
  );
}

export async function logout(): Promise<{ success: boolean }> {
  return apiPost("/api/auth/logout");
}

export async function getMe(): Promise<AuthUser> {
  return apiGet("/api/auth/me");
}

export async function listBatches(): Promise<{ items: BatchItem[] }> {
  return apiGet("/api/batches");
}

export async function getBatch(batchId: string): Promise<BatchItem> {
  return apiGet(`/api/batches/${encodeURIComponent(batchId)}`);
}

export async function getOverview(batchId?: string | null): Promise<Overview> {
  const suffix = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : "";
  return apiGet(`/api/dashboard/overview${suffix}`);
}

export async function getPipeline(batchId: string): Promise<{
  batch_id: string;
  source: string;
  stages: PipelineStage[];
}> {
  return apiGet(`/api/dashboard/pipeline/${encodeURIComponent(batchId)}`);
}

export async function getAnomalies(params: Record<string, string | number | undefined>): Promise<AnomalyList> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  return apiGet(`/api/dashboard/anomalies?${search.toString()}`);
}

export async function getRecordDetail(batchId: string, recordId: string): Promise<RecordDetail> {
  return apiGet(
    `/api/dashboard/records/${encodeURIComponent(batchId)}/${encodeURIComponent(recordId)}`
  );
}

export async function runRecordExplanation(batchId: string, recordId: string) {
  return apiPost(`/api/validation/explanations/${encodeURIComponent(batchId)}/${encodeURIComponent(recordId)}`);
}

export async function runBatchExplanations(
  batchId: string,
  body?: { scope?: "all" | "priority" | "detected"; limit?: number; min_risk_score?: number; severity?: string }
) {
  return apiPost(`/api/validation/explanations/run/${encodeURIComponent(batchId)}`, body ?? {});
}

export async function getEnumerators(batchId?: string | null, view: string = "current_batch"): Promise<GroupList> {
  const search = new URLSearchParams();
  if (view === "cumulative") search.set("view", "cumulative");
  else if (batchId) search.set("batch_id", batchId);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet(`/api/dashboard/enumerators${suffix}`);
}

export async function getEnumerator(id: string, batchId?: string | null): Promise<GroupDetail> {
  const suffix = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : "";
  return apiGet(`/api/dashboard/enumerators/${encodeURIComponent(id)}${suffix}`);
}

export async function getClusters(batchId?: string | null, view: string = "current_batch"): Promise<GroupList> {
  const search = new URLSearchParams();
  if (view === "cumulative") search.set("view", "cumulative");
  else if (batchId) search.set("batch_id", batchId);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet(`/api/dashboard/clusters${suffix}`);
}

export async function getDistricts(batchId?: string | null, view: string = "current_batch"): Promise<GroupList> {
  const search = new URLSearchParams();
  if (view === "cumulative") search.set("view", "cumulative");
  else if (batchId) search.set("batch_id", batchId);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet(`/api/dashboard/districts${suffix}`);
}

export async function ingestCsv(file: File) {
  const form = new FormData();
  form.append("file", file);
  return apiPostForm<{
    batch_id: string;
    rows: number;
    columns: string[];
    success: boolean;
    status?: string;
    pipeline_run_id?: number | null;
    reused?: boolean;
  }>("/api/ingest/csv", form);
}

export async function ingestEsigma() {
  return apiPost<{
    batch_id: string;
    rows: number;
    success: boolean;
    source: string;
    pipeline_run_id?: number | null;
  }>("/api/ingest/esigma");
}

export async function previewOcr(file: File): Promise<OcrPreviewResult> {
  const form = new FormData();
  form.append("file", file);
  return apiPostForm<OcrPreviewResult>("/api/ingest/ocr/preview", form);
}

export async function importOcr(filename: string, records: OcrRecord[]): Promise<OcrImportResult> {
  return apiPost<OcrImportResult>("/api/ingest/ocr/import", { filename, records });
}

export async function getEsigmaStatus(): Promise<{
  mock_mode: boolean;
  configured: boolean;
  status: string;
  notice: string;
}> {
  return apiGet("/api/esigma/status");
}

export async function runPipeline(batchId: string, rerun = false): Promise<OrchestratorRun> {
  return apiPost(`/api/pipeline/run/${encodeURIComponent(batchId)}`, { rerun });
}

export async function getPipelineRun(runId: number): Promise<OrchestratorRun> {
  return apiGet(`/api/pipeline/${runId}`);
}

export async function getPipelineByBatch(batchId: string): Promise<OrchestratorRun> {
  return apiGet(`/api/pipeline/batch/${encodeURIComponent(batchId)}`);
}

export async function getPipelineBatchStatus(batchId: string): Promise<{
  batch_id: string;
  status: string;
  current_stage: string | null;
  progress: number | null;
  pipeline_run_id: number | null;
}> {
  return apiGet(`/api/pipeline/batch/${encodeURIComponent(batchId)}/status`);
}

export async function listInvestigations(params: Record<string, string | undefined>): Promise<InvestigationList> {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) search.set(key, value);
  });
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet(`/api/investigations${suffix}`);
}

export async function createInvestigation(batchId: string, recordId: string): Promise<InvestigationItem> {
  return apiPost("/api/investigations", { batch_id: batchId, record_id: recordId });
}

export async function getAnomalySummary(batchId?: string | null): Promise<AnomalySummary> {
  const suffix = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : "";
  return apiGet(`/api/anomalies/summary${suffix}`);
}

export async function listDetectors(): Promise<DetectorConfig[]> {
  return apiGet("/api/detectors");
}

export async function patchDetector(detectorId: string, body: { enabled?: boolean; severity?: string }) {
  return apiPatch(`/api/detectors/${encodeURIComponent(detectorId)}`, body);
}

export async function getTemporalAnalytics(batchId?: string | null, view: string = "current_batch") {
  const search = new URLSearchParams();
  if (view === "cumulative") search.set("view", "cumulative");
  else if (batchId) search.set("batch_id", batchId);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet(`/api/analytics/temporal${suffix}`);
}

export async function getDetectorAnalytics(batchId?: string | null, view: string = "current_batch") {
  const search = new URLSearchParams();
  if (view === "cumulative") search.set("view", "cumulative");
  else if (batchId) search.set("batch_id", batchId);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiGet(`/api/analytics/detectors${suffix}`);
}

export async function getExplorer(params: {
  batch_id?: string;
  variable?: string;
  level?: string;
  view?: string;
}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) search.set(key, value);
  });
  return apiGet(`/api/analytics/explorer?${search.toString()}`);
}

export async function getEnumeratorAnalytics(id: string, batchId?: string | null) {
  const suffix = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : "";
  return apiGet(`/api/analytics/enumerators/${encodeURIComponent(id)}${suffix}`);
}

export async function patchInvestigation(
  id: number,
  body: {
    action?: string;
    status?: string;
    assigned_to?: string;
    priority?: string;
    finding?: string;
    action_taken?: string;
    final_classification?: string;
  }
): Promise<InvestigationItem> {
  return apiPatch(`/api/investigations/${id}`, body);
}

export async function addInvestigationNote(id: number, note: string): Promise<InvestigationItem> {
  return apiPost(`/api/investigations/${id}/notes`, { note });
}

export async function getInvestigationAudit(id: number): Promise<AuditEvent[]> {
  return apiGet(`/api/investigations/${id}/audit`);
}

export * from "./types";
export { reportUrl, ApiError } from "./client";
