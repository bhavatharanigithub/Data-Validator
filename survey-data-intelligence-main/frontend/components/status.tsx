import type { PipelineStatus } from "@/lib/api/types";

export function SeverityBadge({ value }: { value: string | null | undefined }) {
  const label = (value || "UNKNOWN").toUpperCase();
  const tone: Record<string, string> = {
    CRITICAL: "border-red-200 bg-red-50 text-inst-critical",
    HIGH: "border-orange-200 bg-orange-50 text-orange-800",
    MEDIUM: "border-amber-200 bg-amber-50 text-inst-warning",
    LOW: "border-inst-border bg-inst-muted text-inst-text",
    NONE: "border-inst-border bg-inst-muted text-inst-text-secondary",
    CLEAN: "border-emerald-200 bg-emerald-50 text-inst-green",
  };
  return (
    <span
      className={`inline-flex items-center border px-2 py-0.5 text-[11px] font-semibold ${tone[label] ?? "border-inst-border bg-inst-muted text-inst-text"}`}
    >
      {label}
    </span>
  );
}

const INVESTIGATION_STATUS_LABEL: Record<string, string> = {
  OPEN: "OPEN",
  IN_REVIEW: "IN REVIEW",
  REQUIRES_REENUMERATION: "RE-ENUMERATION REQUIRED",
  ESCALATED: "ESCALATED",
  RESOLVED_VALID: "RESOLVED VALID",
  RESOLVED_INVALID: "RESOLVED INVALID",
};

const INVESTIGATION_STATUS_TONE: Record<string, string> = {
  OPEN: "border-[#c5d4e6] bg-[#e8eef5] text-inst-navy",
  IN_REVIEW: "border-[#9bb6d4] bg-[#dce8f4] text-inst-blue",
  REQUIRES_REENUMERATION: "border-amber-200 bg-amber-50 text-inst-warning",
  ESCALATED: "border-red-200 bg-red-50 text-inst-critical",
  RESOLVED_VALID: "border-emerald-200 bg-emerald-50 text-inst-green",
  RESOLVED_INVALID: "border-emerald-200 bg-emerald-50 text-inst-green",
};

export function InvestigationStatusBadge({ value }: { value: string | null | undefined }) {
  const key = (value || "UNKNOWN").toUpperCase();
  return (
    <span
      className={`inline-flex items-center border px-2 py-0.5 text-[11px] font-semibold ${INVESTIGATION_STATUS_TONE[key] ?? "border-inst-border bg-inst-muted text-inst-text"}`}
    >
      {INVESTIGATION_STATUS_LABEL[key] ?? key.replaceAll("_", " ")}
    </span>
  );
}

const STAGE_DOT: Record<string, string> = {
  COMPLETED: "bg-inst-green",
  PROCESSING: "bg-inst-blue",
  RUNNING: "bg-inst-blue",
  PENDING: "bg-inst-text-secondary",
  FAILED: "bg-inst-critical",
  UNAVAILABLE: "bg-inst-warning",
  READY: "bg-inst-green",
  "NOT CONFIGURED": "bg-inst-warning",
  SKIPPED: "bg-inst-warning",
  PARTIAL: "bg-inst-warning",
};

export function StageBadge({ value }: { value: PipelineStatus | string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-inst-navy">
      <span className={`h-1.5 w-1.5 rounded-full ${STAGE_DOT[value] ?? "bg-inst-text-secondary"}`} aria-hidden="true" />
      {value}
    </span>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="sv-card p-6">
      <p className="text-sm font-semibold text-inst-navy">{title}</p>
      <p className="mt-2 text-sm text-inst-text-secondary">{detail}</p>
    </div>
  );
}

export function LoadingState({ message = "Loading…" }: { message?: string }) {
  return (
    <div className="space-y-3" role="status" aria-live="polite">
      <p className="text-sm text-inst-text-secondary">{message}</p>
      <div className="sv-skeleton h-24 w-full" />
      <div className="sv-skeleton h-24 w-full" />
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="sv-alert-critical">
      <p>{message}</p>
      {onRetry ? (
        <button type="button" className="sv-btn-outline mt-3" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
