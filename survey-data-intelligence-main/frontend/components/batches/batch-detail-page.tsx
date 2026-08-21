"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { OrchestratorPipeline } from "@/components/orchestrator-pipeline";
import { EmptyState, ErrorState } from "@/components/status";
import { ApiError } from "@/lib/api/client";
import { getAnomalies, getBatch, getOverview, getPipelineByBatch, getPipelineRun, runPipeline } from "@/lib/api";
import {
  aiBatchLabel,
  aiStatusLabel,
  apiErrorMessage,
  asStages,
  explanationStage,
  pipelineShouldKeepPolling,
} from "@/lib/batch-detail-state";
import { pipelineHeadline } from "@/lib/query-view";
import { readPipelineRun, writePipelineRun, writeSelectedBatch } from "@/lib/session-state";

function skippedDetectors(run: { stages?: { stage: string; detail?: Record<string, unknown> }[] } | undefined) {
  const intel = run?.stages?.find((stage) => stage.stage === "INTELLIGENCE");
  const skipped = intel?.detail?.skipped;
  return Array.isArray(skipped) ? skipped.map(String) : [];
}

export default function BatchDetailPage({
  batchId,
  pipelineRunId,
}: {
  batchId: string;
  pipelineRunId?: number | null;
}) {
  const queryClient = useQueryClient();
  const [queueTimedOut, setQueueTimedOut] = useState(false);
  const [activeRunId, setActiveRunId] = useState<number | null>(pipelineRunId ?? null);
  const knownRunId = activeRunId ?? (batchId ? readPipelineRun(batchId) : null);
  const batch = useQuery({
    queryKey: ["batch", batchId],
    queryFn: () => {
      if (typeof window !== "undefined") writeSelectedBatch(batchId);
      return getBatch(batchId);
    },
    enabled: Boolean(batchId),
    retry: false,
  });
  const pipeline = useQuery({
    queryKey: ["orchestrator", batchId, knownRunId],
    queryFn: async () => {
      if (knownRunId) {
        try {
          const run = await getPipelineRun(knownRunId);
          writePipelineRun(batchId, run.pipeline_run_id);
          setActiveRunId(run.pipeline_run_id);
          return run;
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 404) throw error;
        }
      }
      const byBatch = await getPipelineByBatch(batchId);
      writePipelineRun(batchId, byBatch.pipeline_run_id);
      setActiveRunId(byBatch.pipeline_run_id);
      return byBatch;
    },
    enabled: Boolean(batchId),
    retry: (count, error) => error instanceof ApiError && error.status === 404 && count < 40,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      const errorStatus = query.state.error instanceof ApiError ? query.state.error.status : null;
      return pipelineShouldKeepPolling(status, errorStatus) ? 1800 : false;
    },
  });
  useEffect(() => {
    setQueueTimedOut(false);
    if (!(pipeline.error instanceof ApiError) || pipeline.error.status !== 404) return;
    const timer = window.setTimeout(() => setQueueTimedOut(true), 45000);
    return () => window.clearTimeout(timer);
  }, [pipeline.error, batchId]);
  const overview = useQuery({
    queryKey: ["overview", batchId],
    queryFn: () => getOverview(batchId),
    enabled: Boolean(batchId),
    retry: false,
    refetchInterval: () => {
      const status = pipeline.data?.status;
      return status === "RUNNING" || status === "PENDING" ? 1800 : false;
    },
  });
  const anomalies = useQuery({
    queryKey: ["anomalies", batchId, "batch-detail"],
    queryFn: () => getAnomalies({ batch_id: batchId, page: 1, page_size: 50, classification_scope: "all" }),
    enabled: Boolean(batchId) && (pipeline.data?.status === "COMPLETED" || pipeline.data?.status === "PARTIAL"),
    retry: false,
  });
  const retry = useMutation({
    mutationFn: () => runPipeline(batchId, true),
    onSuccess: (data) => {
      writePipelineRun(batchId, data.pipeline_run_id);
      setActiveRunId(data.pipeline_run_id);
      queryClient.invalidateQueries({ queryKey: ["orchestrator", batchId] });
      queryClient.invalidateQueries({ queryKey: ["overview", batchId] });
      queryClient.invalidateQueries({ queryKey: ["anomalies"] });
    },
  });

  const missing = pipeline.error instanceof ApiError && pipeline.error.status === 404;
  const run = pipeline.data;
  const stages = asStages(run);
  const explain = explanationStage(run);
  const items = anomalies.data?.items ?? [];
  const aiLabel = aiBatchLabel(run, items);
  const busy = run?.status === "RUNNING" || run?.status === "PENDING";
  const skipped = skippedDetectors(run);

  if (!batchId) {
    return <ErrorState message="Batch id is missing from the route." />;
  }
  if (batch.isError) {
    return <ErrorState message={apiErrorMessage(batch.error, "Batch could not be loaded.")} />;
  }
  if (batch.isLoading || !batch.data) {
    return <p className="text-sm text-slate-400">Loading batch…</p>;
  }

  return (
    <div className="space-y-4">
      <div>
        <p className="sv-label">Survey analysis</p>
        <h1 className="text-xl font-semibold">{batch.data.batch_id}</h1>
        <p className="text-sm text-slate-400">
          {batch.data.source} · {batch.data.records ?? "—"} records
        </p>
        <p className="mt-1 text-sm text-emerald-300">
          {run?.status === "COMPLETED"
            ? "Analysis completed."
            : run?.status === "PARTIAL"
              ? "Analysis completed with limitations."
              : run?.status === "FAILED"
                ? "Analysis failed."
                : run?.status === "RUNNING"
                  ? "RUNNING"
                  : run?.status === "PENDING"
                    ? "PENDING"
                    : missing
                      ? "PENDING"
                      : "Batch created. Analysis started automatically."}
        </p>
      </div>

      {run?.status === "PENDING" || missing ? (
        <div className="rounded border border-slate-700 bg-slate-900/40 p-3 text-sm">
          <p className="font-semibold text-slate-200">PENDING</p>
          <p className="mt-1">
            {knownRunId ? `Pipeline ${knownRunId} is queued for this batch.` : "The pipeline is being queued for this batch."}
          </p>
        </div>
      ) : null}

      {busy && run?.status === "RUNNING" ? (
        <div className="rounded border border-sky-800 bg-sky-950/40 p-3 text-sm">
          <p className="font-semibold text-sky-200">RUNNING</p>
          <p className="mt-1">Current stage: {run?.current_stage || "PENDING"}</p>
        </div>
      ) : null}

      {run?.status === "COMPLETED" ? (
        <div className="rounded border border-emerald-800 bg-emerald-950/40 p-3 text-sm text-emerald-200">
          ✓ Analysis complete
        </div>
      ) : null}

      {run?.status === "PARTIAL" ? (
        <div className="rounded border border-amber-800 bg-amber-950/40 p-3 text-sm text-amber-100">
          ⚠ Analysis completed with limitations
          {explain?.status === "UNAVAILABLE" ? <p className="mt-1">AI explanation unavailable.</p> : null}
          {skipped.length ? <p className="mt-1">Optional stages unavailable: {skipped.join(", ")}</p> : null}
        </div>
      ) : null}

      {run?.status === "FAILED" ? (
        <div className="rounded border border-red-800 bg-red-950/40 p-3 text-sm">
          <p className="font-semibold text-red-200">✕ Analysis failed</p>
          <p className="mt-1">Stage: {run.error_stage || run.current_stage}</p>
          <p className="mt-1">Reason: {run.error_message || "See stage details."}</p>
        </div>
      ) : null}

      <div className="flex gap-2">
        {run?.status === "FAILED" ? (
          <button
            className="rounded border border-red-700 px-3 py-2 text-sm text-red-200"
            disabled={retry.isPending}
            onClick={() => retry.mutate()}
          >
            Retry
          </button>
        ) : (
          <button
            className="rounded border border-slate-600 px-3 py-2 text-sm"
            disabled={retry.isPending || busy}
            onClick={() => retry.mutate()}
          >
            Reprocess
          </button>
        )}
        {run && (run.status === "COMPLETED" || run.status === "PARTIAL") ? (
          <Link className="rounded bg-sky-700 px-3 py-2 text-sm font-semibold text-white" href="/dashboard">
            View results
          </Link>
        ) : null}
      </div>

      {missing && !queueTimedOut ? (
        <EmptyState title="Starting analysis" detail="Waiting for the queued pipeline to start." />
      ) : null}
      {missing && queueTimedOut ? (
        <ErrorState
          message="The pipeline stayed queued and never started. Use Retry to start a new run."
          onRetry={() => retry.mutate()}
        />
      ) : null}
      {pipeline.isError && !missing ? (
        <ErrorState
          message={apiErrorMessage(pipeline.error, "Pipeline status could not be loaded.")}
          onRetry={() => pipeline.refetch()}
        />
      ) : null}
      {overview.isError ? (
        <ErrorState message="Overview metrics could not be loaded." onRetry={() => overview.refetch()} />
      ) : null}

      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <div className="sv-card p-3">
          <p className="sv-label">Total records</p>
          <p className="mt-1 text-lg">{overview.isError ? "Unavailable" : (overview.data?.processed ?? batch.data.records ?? "—")}</p>
        </div>
        <div className="sv-card p-3">
          <p className="sv-label">Normal</p>
          <p className="mt-1 text-lg">{overview.isError ? "Unavailable" : (overview.data?.clean ?? "—")}</p>
        </div>
        <div className="sv-card p-3">
          <p className="sv-label">Confirmed validation issues</p>
          <p className="mt-1 text-lg">{overview.isError ? "Unavailable" : (overview.data?.confirmed_anomalies ?? "—")}</p>
        </div>
        <div className="sv-card p-3">
          <p className="sv-label">Investigation required</p>
          <p className="mt-1 text-lg">
            {overview.isError ? "Unavailable" : (overview.data?.investigation_required ?? overview.data?.review_signals ?? "—")}
          </p>
        </div>
        <div className="sv-card p-3">
          <p className="sv-label">High risk</p>
          <p className="mt-1 text-lg">{overview.isError ? "Unavailable" : (overview.data?.high_risk ?? "—")}</p>
        </div>
        <div className="sv-card p-3">
          <p className="sv-label">AI explanations</p>
          <p className="mt-1 text-lg">{aiLabel}</p>
        </div>
      </div>

      {run ? (
        <div className="space-y-3">
          <p className="text-sm">
            Status: <span className="font-semibold">{pipelineHeadline(run.status)}</span>
            {run.current_stage ? ` · current stage ${run.current_stage}` : ""}
          </p>
          {stages.length ? <OrchestratorPipeline batchId={batchId} stages={stages} /> : null}
          {items.length ? (
            <div className="sv-card overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="border-b border-slate-800 text-xs uppercase text-slate-400">
                  <tr>
                    <th className="px-3 py-2">Record</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Severity</th>
                    <th className="px-3 py-2">Risk</th>
                    <th className="px-3 py-2">AI explanation</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.record_id} className="border-b border-slate-800/80">
                      <td className="px-3 py-2">
                        <Link
                          className="text-sky-300 underline"
                          href={`/dashboard/records/${encodeURIComponent(item.record_id)}?batchId=${encodeURIComponent(item.batch_id)}`}
                        >
                          {item.record_id}
                        </Link>
                      </td>
                      <td className="px-3 py-2">{item.anomaly_status ?? "—"}</td>
                      <td className="px-3 py-2">{item.severity ?? "—"}</td>
                      <td className="px-3 py-2">{item.risk_score != null ? item.risk_score.toFixed(0) : "—"}</td>
                      <td className="px-3 py-2">{aiStatusLabel(item.ai_explanation_status)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
