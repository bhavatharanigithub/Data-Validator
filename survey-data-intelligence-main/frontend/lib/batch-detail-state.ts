import type { AnomalyRow, OrchestratorRun, OrchestratorStage } from "./api/types";
import { ApiError } from "./api/client";

export function resolveRouteParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return String(value[0] ?? "");
  return typeof value === "string" ? value : "";
}

export function pipelineShouldKeepPolling(
  status: string | null | undefined,
  errorStatus: number | null | undefined
): boolean {
  if (status === "RUNNING" || status === "PENDING") return true;
  if (errorStatus === 404) return true;
  return false;
}

export function asStages(run: OrchestratorRun | null | undefined): OrchestratorStage[] {
  const stages = run?.stages;
  return Array.isArray(stages) ? stages.filter((stage) => stage && typeof stage.stage === "string") : [];
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "You are not signed in.";
    if (error.status === 403) return "You do not have access to this batch.";
    if (error.status === 404) return "This batch was not found.";
    if (error.status === 0 || error.status >= 500) return "The validation service is unavailable.";
    return `${fallback} (HTTP ${error.status})`;
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

export function explanationStage(run: OrchestratorRun | null | undefined): OrchestratorStage | undefined {
  return asStages(run).find((stage) => stage.stage === "EXPLANATION");
}

export function aiBatchLabel(
  run: OrchestratorRun | null | undefined,
  items: AnomalyRow[] | null | undefined
): "Generating" | "Complete" | "Partial" | "Unavailable" | "Not required" {
  const stage = explanationStage(run);
  if (run?.status === "RUNNING" || stage?.status === "PROCESSING") return "Generating";
  const rows = Array.isArray(items) ? items : [];
  const needed = rows.filter((row) => row.ai_explanation_status !== "not_required");
  const available = needed.filter((row) => row.ai_explanation_status === "available").length;
  const unavailable = needed.filter((row) => row.ai_explanation_status === "unavailable").length;
  if (stage?.status === "UNAVAILABLE" && available === 0) return "Unavailable";
  if (!needed.length) return "Not required";
  if (available === needed.length) return "Complete";
  if (available > 0 && unavailable > 0) return "Partial";
  if (unavailable === needed.length) return "Unavailable";
  if (available > 0 && available < needed.length) return "Partial";
  return "Generating";
}

export function aiStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case "available":
      return "Available";
    case "generating":
      return "Generating";
    case "unavailable":
      return "Unavailable";
    case "not_required":
      return "Not required";
    case "not_generated":
      return "Generating";
    default:
      return status || "—";
  }
}

export function explanationConfidenceLabel(value: number | null | undefined): string | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  if (value >= 0.85) return "Very high";
  if (value >= 0.7) return "High";
  if (value >= 0.4) return "Moderate";
  return "Low";
}
