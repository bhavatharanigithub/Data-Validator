"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Clock3, Layers, Plus, XCircle } from "lucide-react";
import { Kpi } from "@/components/kpi";
import { EmptyState, ErrorState, StageBadge } from "@/components/status";
import { listBatches } from "@/lib/api";
import type { BatchItem } from "@/lib/api/types";
import { queryView } from "@/lib/query-view";

const SUMMARY_STATUSES = ["COMPLETED", "RUNNING", "PENDING", "PARTIAL", "FAILED"] as const;

const SUMMARY_META: Record<
  (typeof SUMMARY_STATUSES)[number],
  { label: string; hint: string; tone: "success" | "info" | "neutral" | "warning" | "critical"; icon: typeof CheckCircle2 }
> = {
  COMPLETED: { label: "Completed", hint: "Finished pipeline runs", tone: "success", icon: CheckCircle2 },
  RUNNING: { label: "Running", hint: "Currently processing", tone: "info", icon: Clock3 },
  PENDING: { label: "Pending", hint: "Queued for processing", tone: "neutral", icon: Clock3 },
  PARTIAL: { label: "Partial", hint: "Completed with gaps", tone: "warning", icon: AlertTriangle },
  FAILED: { label: "Failed", hint: "Did not complete", tone: "critical", icon: XCircle },
};

function displayStatus(item: BatchItem): string {
  return item.pipeline_status ?? item.status ?? "UNKNOWN";
}

function percent(count: number, total: number): string | undefined {
  if (!total) return undefined;
  return `${((count / total) * 100).toFixed(1)}% of this listing`;
}

function PageHeader() {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="sv-label">Batches</p>
        <h1 className="mt-1 text-2xl font-semibold text-inst-navy">Data batches</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-inst-text-secondary">
          View and monitor survey data batches processed through the validation pipeline.
        </p>
      </div>
      <Link className="sv-btn-compact" href="/dashboard/batches/new">
        <Plus className="h-4 w-4" aria-hidden="true" />
        New batch
      </Link>
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="sv-card overflow-hidden" role="status" aria-live="polite">
      <p className="sr-only">Loading batches…</p>
      <div className="space-y-2 p-4">
        {Array.from({ length: 8 }, (_, index) => (
          <div key={index} className="sv-skeleton h-10 w-full" />
        ))}
      </div>
    </div>
  );
}

export default function BatchesPage() {
  const batches = useQuery({ queryKey: ["batches"], queryFn: listBatches, retry: false });
  const items = batches.data?.items ?? [];
  const view = queryView(batches, Boolean(items.length));
  const total = items.length;
  const statusCounts = SUMMARY_STATUSES.reduce(
    (acc, status) => {
      acc[status] = items.filter((item) => displayStatus(item) === status).length;
      return acc;
    },
    {} as Record<(typeof SUMMARY_STATUSES)[number], number>
  );

  return (
    <div className="space-y-6">
      <PageHeader />

      {view === "error" ? (
        <ErrorState message="Unable to load batches. We couldn't retrieve the batch records right now." onRetry={() => batches.refetch()} />
      ) : null}

      {view === "loading" ? <TableSkeleton /> : null}

      {view === "empty" ? (
        <EmptyState title="No survey batches found" detail="There are currently no batches in this listing. Use New batch to ingest CSV or eSIGMA data." />
      ) : null}

      {view === "ready" ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
            <Kpi
              label="Total batches"
              value={total}
              available
              hint="Batches in this listing"
              icon={Layers}
              tone="info"
            />
            {SUMMARY_STATUSES.map((status) => {
              const meta = SUMMARY_META[status];
              return (
                <Kpi
                  key={status}
                  label={meta.label}
                  value={statusCounts[status]}
                  available
                  hint={percent(statusCounts[status], total) ?? meta.hint}
                  icon={meta.icon}
                  tone={meta.tone}
                />
              );
            })}
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_18rem]">
            <div className="sv-card overflow-x-auto">
              <table className="sv-table">
                <thead>
                  <tr>
                    <th>Batch ID</th>
                    <th>Date</th>
                    <th>Status</th>
                    <th className="sv-num">Records</th>
                    <th>Pipeline</th>
                    <th className="sv-num">Issues</th>
                    <th className="sv-num">Investigation signals</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.batch_id}>
                      <td className="max-w-[22rem]">
                        <Link
                          className="break-all font-mono text-xs font-medium"
                          href={`/dashboard/batches/${item.batch_id}`}
                          title={item.batch_id}
                        >
                          {item.batch_id}
                        </Link>
                      </td>
                      <td className="whitespace-nowrap text-inst-text-secondary">
                        {item.created_at ? new Date(item.created_at).toLocaleString() : "—"}
                      </td>
                      <td>
                        <StageBadge value={displayStatus(item)} />
                      </td>
                      <td className="sv-num">{item.records ?? "—"}</td>
                      <td>{item.pipeline_version ?? "—"}</td>
                      <td className="sv-num">{item.confirmed_issues ?? "—"}</td>
                      <td className="sv-num">{item.investigation_signals ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="space-y-4">
              <section className="sv-card p-5">
                <h2 className="text-sm font-semibold text-inst-navy">Batch status summary</h2>
                <p className="mt-1 text-xs text-inst-text-secondary">Counts from the current listing.</p>
                <ul className="mt-4 space-y-3">
                  {SUMMARY_STATUSES.map((status) => (
                    <li key={status}>
                      <div className="mb-1 flex items-center justify-between text-sm">
                        <StageBadge value={status} />
                        <span className="tabular-nums font-semibold text-inst-navy">{statusCounts[status]}</span>
                      </div>
                      <div className="sv-bar" aria-hidden="true">
                        <span
                          className={
                            status === "COMPLETED"
                              ? "bg-inst-green"
                              : status === "FAILED"
                                ? "bg-inst-critical"
                                : status === "PARTIAL"
                                  ? "bg-inst-warning"
                                  : status === "RUNNING"
                                    ? "bg-inst-blue"
                                    : "bg-inst-text-secondary"
                          }
                          style={{ width: `${total ? Math.min(100, (statusCounts[status] / total) * 100) : 0}%` }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
              <section className="sv-card p-5">
                <h2 className="text-sm font-semibold text-inst-navy">About batches</h2>
                <p className="mt-2 text-sm leading-6 text-inst-text-secondary">
                  Each batch is processed through the survey validation pipeline, including ingestion, Parquet storage,
                  SIRL profiling, rules, statistical analysis, intelligence, ML and fusion / risk assessment.
                </p>
              </section>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
