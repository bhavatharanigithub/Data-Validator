"use client";

const KEY = "sv.selected.batch";

export function readSelectedBatch(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(KEY);
}

export function writeSelectedBatch(batchId: string): void {
  window.localStorage.setItem(KEY, batchId);
}

function pipelineKey(batchId: string): string {
  return `sv.pipeline.${batchId}`;
}

export function writePipelineRun(batchId: string, pipelineRunId: number): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(pipelineKey(batchId), String(pipelineRunId));
}

export function readPipelineRun(batchId: string): number | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(pipelineKey(batchId));
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

const INVEST = "sv.investigation";

export type InvestigationStatus = "OPEN" | "IN_REVIEW" | "CLEARED" | "ESCALATED";

export function investigationKey(batchId: string, recordId: string): string {
  return `${batchId}:${recordId}`;
}

export function readInvestigations(): Record<string, InvestigationStatus> {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(window.localStorage.getItem(INVEST) || "{}") as Record<string, InvestigationStatus>;
  } catch {
    return {};
  }
}

export function writeInvestigation(batchId: string, recordId: string, status: InvestigationStatus): void {
  const all = readInvestigations();
  all[investigationKey(batchId, recordId)] = status;
  window.localStorage.setItem(INVEST, JSON.stringify(all));
}
