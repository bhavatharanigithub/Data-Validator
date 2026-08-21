"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  AlertOctagon,
  AlertTriangle,
  Clock3,
  Database,
  MapPin,
  ShieldAlert,
  UserRound,
  Users,
} from "lucide-react";
import { Kpi } from "@/components/kpi";
import { OrchestratorPipeline } from "@/components/orchestrator-pipeline";
import { QualitySignalCard } from "@/components/QualitySignalCard";
import { BatchSelectionGate } from "@/components/shell";
import { EmptyState, ErrorState, LoadingState } from "@/components/status";
import { getOverview, getPipelineByBatch } from "@/lib/api";

const SIGNAL_ITEMS: [string, string][] = [
  ["ENUMERATOR_DEVIATION", "Enumerator deviations"],
  ["TEMPORAL_CHANGE", "Temporal changes"],
  ["CLUSTER_PATTERN", "Cluster patterns"],
  ["REL_AGE_MARITAL", "Relationship issues"],
  ["DISTRIBUTION_SHIFT", "Distribution shifts"],
  ["GEOGRAPHIC_CLUSTER", "Geographic alerts"],
];

export default function OverviewPage() {
  return (
    <BatchSelectionGate emptyDetail="Ingest a CSV or eSIGMA extract before reviewing KPIs.">
      {(batchId) => <OverviewInner batchId={batchId} />}
    </BatchSelectionGate>
  );
}

function OverviewInner({ batchId }: { batchId: string }) {
  const router = useRouter();
  const pipeline = useQuery({
    queryKey: ["orchestrator", batchId],
    queryFn: () => getPipelineByBatch(batchId),
    retry: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "RUNNING" || status === "PENDING" ? 1800 : false;
    },
  });
  const processing = pipeline.data?.status === "RUNNING" || pipeline.data?.status === "PENDING";
  const overview = useQuery({
    queryKey: ["overview", batchId, processing ? "stable" : "selected"],
    queryFn: () => getOverview(processing ? null : batchId),
    retry: false,
    refetchInterval: () => (processing ? 1800 : false),
  });

  if (overview.isPending) return <LoadingState message="Loading overview…" />;
  if (overview.isError) {
    return (
      <ErrorState
        message="Overview metrics could not be loaded. Values are not shown as zero."
        onRetry={() => overview.refetch()}
      />
    );
  }

  const data = overview.data;
  const ready = Boolean(data?.available);
  const signals = data?.quality_signals ?? {};
  const signalValues = SIGNAL_ITEMS.map(([key]) => (ready ? (signals[key] ?? 0) : 0));
  const signalMax = Math.max(1, ...signalValues);
  const processed = data?.processed ?? data?.total_records;
  const processedCount = processed ?? 0;
  const riskRows = [
    { label: "High risk", value: data?.high_risk, color: "bg-inst-critical" },
    { label: "Critical risk", value: data?.critical, color: "bg-[#8f1d16]" },
    { label: "Investigation required", value: data?.investigation_required, color: "bg-inst-warning" },
    {
      label: "Confirmed issues",
      value: data?.validation_errors ?? data?.confirmed_anomalies,
      color: "bg-orange-700",
    },
    { label: "Normal", value: data?.clean, color: "bg-inst-green" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="sv-label">Overview</p>
          <h1 className="mt-1 text-2xl font-semibold text-inst-navy">Survey data quality intelligence</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-inst-text-secondary">
            Real-time overview of survey quality, validation signals and pipeline status
          </p>
          {processing ? (
            <p className="mt-2 text-sm text-inst-blue">
              Latest batch {pipeline.data?.status}
              {pipeline.data?.current_stage ? ` · ${pipeline.data.current_stage}` : ""}. Stable results remain visible
              until the new run is active.
            </p>
          ) : null}
          {!ready && data?.message ? <p className="mt-2 text-sm text-inst-warning">{data.message}</p> : null}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
        <Kpi
          label="Records processed"
          value={data?.processed ?? data?.total_records ?? null}
          available={ready}
          hint="Total records analyzed"
          icon={Database}
          tone="info"
        />
        <Kpi
          label="Normal"
          value={data?.clean ?? null}
          available={ready}
          hint="Records within thresholds"
          icon={Users}
          tone="success"
        />
        <Kpi
          label="Investigation required"
          value={data?.investigation_required ?? null}
          available={ready}
          hint="Requires supervisor review"
          icon={AlertTriangle}
          tone="warning"
        />
        <Kpi
          label="High risk"
          value={data?.high_risk ?? null}
          available={ready}
          hint="Critical attention needed"
          icon={ShieldAlert}
          tone="critical"
        />
        <Kpi
          label="Confirmed validation issues"
          value={data?.validation_errors ?? data?.confirmed_anomalies ?? null}
          available={ready}
          hint="Confirmed validation findings"
          icon={AlertOctagon}
          tone="critical"
        />
        <Kpi
          label="Enumerator signals"
          value={data?.enumerator_alerts ?? null}
          available={ready}
          hint="Enumerator-level detections"
          icon={UserRound}
          tone="info"
        />
        <Kpi
          label="Temporal signals"
          value={data?.temporal_alerts ?? null}
          available={ready}
          hint="Time-pattern detections"
          icon={Clock3}
          tone="info"
        />
        <Kpi
          label="Geographic signals"
          value={data?.geographic_alerts ?? null}
          available={ready}
          hint="Location-pattern detections"
          icon={MapPin}
          tone="info"
        />
        <Kpi
          label="Relationship signals"
          value={data?.relationship_alerts ?? null}
          available={ready}
          hint="Relationship-rule detections"
          icon={Users}
          tone="info"
        />
      </div>

      <section className="sv-card p-5">
        <h2 className="text-sm font-semibold text-inst-navy">Quality signal distribution</h2>
        <p className="mt-1 text-xs text-inst-text-secondary">Counts from existing detector results for this batch.</p>
        {!ready ? (
          <div className="mt-4">
            <EmptyState title="Quality signals not ready" detail={data?.message || "Signals appear when fusion assessment is available."} />
          </div>
        ) : (
          <div className="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
            {SIGNAL_ITEMS.map(([key, label]) => (
              <QualitySignalCard
                key={key}
                label={label}
                value={signals[key] ?? 0}
                max={signalMax}
                onClick={() => router.push(`/dashboard/anomalies?detector=${encodeURIComponent(key)}&scope=all`)}
              />
            ))}
          </div>
        )}
      </section>

      <section className="sv-card p-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-inst-navy">Risk distribution</h2>
            <p className="mt-1 text-xs text-inst-text-secondary">
              Separate backend measures. They are not combined into a new total.
            </p>
          </div>
          <p className="text-sm text-inst-text">
            Records processed{" "}
            <span className="font-semibold tabular-nums text-inst-navy">{ready ? (processed ?? "—") : "—"}</span>
          </p>
        </div>
        {!ready ? (
          <div className="mt-4">
            <EmptyState title="Risk distribution not ready" detail={data?.message || "Risk measures appear when fusion assessment is available."} />
          </div>
        ) : (
          <ul className="mt-4 space-y-3">
            {riskRows.map((row) => {
              const numeric = row.value ?? null;
              const width = numeric != null && processedCount > 0 ? Math.min(100, (numeric / processedCount) * 100) : 0;
              return (
                <li key={row.label}>
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span className="text-inst-text">{row.label}</span>
                    <span className="tabular-nums font-semibold text-inst-navy">{numeric ?? "—"}</span>
                  </div>
                  <div className="sv-bar" aria-hidden="true">
                    <span className={row.color} style={{ width: `${width}%` }} />
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="sv-card p-5">
        <h2 className="text-sm font-semibold text-inst-navy">Processing pipeline</h2>
        <p className="mt-1 text-xs text-inst-text-secondary">
          Ingestion → Parquet → SIRL → Rules → Statistics → Intelligence → ML → Fusion / Risk
        </p>
        <div className="mt-4">
          {pipeline.isPending ? <LoadingState message="Loading pipeline…" /> : null}
          {pipeline.isError ? (
            <ErrorState message="Pipeline status could not be loaded." onRetry={() => pipeline.refetch()} />
          ) : null}
          {pipeline.data?.stages?.length ? (
            <OrchestratorPipeline batchId={batchId} stages={pipeline.data.stages} />
          ) : pipeline.isSuccess ? (
            <EmptyState title="No pipeline stages" detail="No pipeline stages for this batch." />
          ) : null}
        </div>
      </section>
    </div>
  );
}
