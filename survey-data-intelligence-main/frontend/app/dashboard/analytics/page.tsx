"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ClipboardList, Clock3 } from "lucide-react";
import { DetectorDistributionChart } from "@/components/DetectorDistributionChart";
import { EnumeratorComparisonChart } from "@/components/EnumeratorComparisonChart";
import { GeographicComparisonChart } from "@/components/GeographicComparisonChart";
import { TemporalTrendChart } from "@/components/TemporalTrendChart";
import { Kpi } from "@/components/kpi";
import { BatchSelectionGate } from "@/components/shell";
import { EmptyState, ErrorState } from "@/components/status";
import { ViewScopeBanner, ViewScopeSelect } from "@/components/view-scope-select";
import { getDetectorAnalytics, getExplorer, getTemporalAnalytics } from "@/lib/api";
import type { DataView } from "@/lib/data-view";
import { isCumulativeView, useDataView } from "@/lib/data-view";

export default function AnalyticsPage() {
  const [view, setView] = useDataView();
  return (
    <BatchSelectionGate emptyDetail="Ingest data before analytics.">
      {(batchId) => <AnalyticsInner batchId={batchId} view={view} onViewChange={setView} />}
    </BatchSelectionGate>
  );
}

function ChartSkeleton() {
  return (
    <div className="space-y-2" role="status" aria-live="polite">
      <div className="sv-skeleton h-80 w-full" />
    </div>
  );
}

function AnalyticsInner({
  batchId,
  view,
  onViewChange,
}: {
  batchId: string;
  view: DataView;
  onViewChange: (next: DataView) => void;
}) {
  const cumulative = isCumulativeView(view);
  const scopeKey = cumulative ? "cumulative" : batchId;
  const temporal = useQuery({
    queryKey: ["temporal", scopeKey],
    queryFn: () => getTemporalAnalytics(batchId, view),
    retry: false,
  });
  const detectors = useQuery({
    queryKey: ["detector-analytics", scopeKey],
    queryFn: () => getDetectorAnalytics(batchId, view),
    retry: false,
  });
  const explorer = useQuery({
    queryKey: ["explorer", scopeKey],
    queryFn: () =>
      getExplorer({
        batch_id: cumulative ? undefined : batchId,
        variable: "employment_rate",
        level: "district",
        view,
      }),
    retry: false,
  });
  const enumerators = useQuery({
    queryKey: ["explorer-enumerators", scopeKey],
    queryFn: () =>
      getExplorer({
        batch_id: cumulative ? undefined : batchId,
        variable: "employment_rate",
        level: "enumerator",
        view,
      }),
    retry: false,
  });

  if (temporal.isPending && detectors.isPending) {
    return (
      <div className="space-y-6">
        <PageHeader batchId={batchId} view={view} onViewChange={onViewChange} />
        <ChartSkeleton />
        <ChartSkeleton />
      </div>
    );
  }
  if (temporal.isError && detectors.isError && explorer.isError) {
    return (
      <ErrorState
        message="Analytics could not be loaded."
        onRetry={() => {
          temporal.refetch();
          detectors.refetch();
          explorer.refetch();
          enumerators.refetch();
        }}
      />
    );
  }

  const detectorPayload = detectors.data as
    | {
        available?: boolean;
        items?: { detector: string; count: number }[];
        message?: string;
        records_processed?: number;
        confirmed_anomalies?: number;
        review_signals?: number;
        risk_distribution?: Record<string, number>;
        classification_distribution?: Record<string, number>;
      }
    | undefined;
  const temporalPayload = temporal.data as {
    available?: boolean;
    items?: { period: string; observed: number | null; baseline: number | null; threshold?: number | null }[];
    message?: string;
  } | undefined;
  const geoPayload = explorer.data as { available?: boolean; items?: { id: string; employment_rate?: number | null }[]; message?: string } | undefined;
  const enumPayload = enumerators.data as {
    available?: boolean;
    items?: { id: string; employment_rate?: number | null }[];
    message?: string;
  } | undefined;

  const detectorItems = detectorPayload?.items ?? [];
  const temporalItems = temporalPayload?.items ?? [];
  const geoItems = (geoPayload?.items ?? []).map((item) => ({
    id: item.id,
    value: item.employment_rate ?? null,
  }));
  const comparison = (enumPayload?.items ?? []).map((item) => ({
    enumerator_id: String(item.id),
    employment_rate: item.employment_rate ?? null,
  }));
  const cumulativeUnavailable = cumulative && detectorPayload?.available === false;
  const temporalUnavailable =
    !temporalItems.length &&
    Boolean(temporalPayload?.message && /not available for cumulative/i.test(temporalPayload.message));

  return (
    <div className="space-y-6">
      <PageHeader batchId={batchId} view={view} onViewChange={onViewChange} />

      {cumulativeUnavailable ? (
        <EmptyState
          title="No processed batches available for cumulative analysis."
          detail={detectorPayload?.message || "Upload and process at least one survey batch first."}
        />
      ) : null}

      {cumulative && detectorPayload?.available !== false && !detectors.isPending && !detectors.isError ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi
            label="Total records processed"
            value={detectorPayload?.records_processed ?? null}
            available={detectorPayload?.records_processed != null}
            hint="Fused assessments across all processed batches"
            icon={ClipboardList}
            tone="info"
          />
          <Kpi
            label="Total anomalies"
            value={detectorPayload?.confirmed_anomalies ?? null}
            available={detectorPayload?.confirmed_anomalies != null}
            hint="Confirmed anomalies from persisted fusion evidence"
            icon={AlertTriangle}
            tone="critical"
          />
          <Kpi
            label="Review signals"
            value={detectorPayload?.review_signals ?? null}
            available={detectorPayload?.review_signals != null}
            hint="Persisted REVIEW classifications"
            icon={AlertTriangle}
            tone="warning"
          />
        </div>
      ) : null}

      {cumulative && detectorPayload?.risk_distribution ? (
        <section className="sv-card p-5">
          <h2 className="text-sm font-semibold text-inst-navy">Risk distribution</h2>
          <p className="mt-1 text-sm text-inst-text-secondary">Persisted severity counts across all processed batches.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((key) => (
              <Kpi
                key={key}
                label={key}
                value={detectorPayload.risk_distribution?.[key] ?? 0}
                available
                tone={key === "CRITICAL" || key === "HIGH" ? "critical" : key === "MEDIUM" ? "warning" : "neutral"}
              />
            ))}
          </div>
        </section>
      ) : null}

      {cumulative && detectorPayload?.classification_distribution ? (
        <section className="sv-card p-5">
          <h2 className="text-sm font-semibold text-inst-navy">Classification distribution</h2>
          <p className="mt-1 text-sm text-inst-text-secondary">Persisted anomaly status across all processed batches.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {Object.entries(detectorPayload.classification_distribution).map(([key, count]) => (
              <Kpi key={key} label={key} value={count} available tone="info" />
            ))}
          </div>
        </section>
      ) : null}

      <section className="sv-card p-5">
        <h2 className="text-sm font-semibold text-inst-navy">Temporal trends</h2>
        {temporal.isError ? (
          <div className="mt-4">
            <ErrorState message="Temporal analytics could not be loaded." onRetry={() => temporal.refetch()} />
          </div>
        ) : temporal.isPending ? (
          <div className="mt-4">
            <ChartSkeleton />
          </div>
        ) : temporalItems.length ? (
          <div className="mt-4">
            <TemporalTrendChart items={temporalItems} />
          </div>
        ) : temporalUnavailable ? (
          <div className="mt-4">
            <EmptyState title="Not available for cumulative view" detail={temporalPayload?.message || ""} />
          </div>
        ) : (
          <div className="mt-4 flex items-start gap-3 rounded border border-inst-border bg-inst-muted px-4 py-5">
            <Clock3 className="mt-0.5 h-5 w-5 shrink-0 text-inst-blue" aria-hidden="true" />
            <div>
              <p className="font-semibold text-inst-navy">No previous survey period available</p>
              <p className="mt-1 text-sm leading-6 text-inst-text-secondary">
                Historical comparison will appear when a comparable previous survey period is available.
              </p>
              {temporalPayload?.message &&
              !/no previous survey period/i.test(temporalPayload.message) ? (
                <p className="mt-2 text-xs text-inst-text-secondary">{temporalPayload.message}</p>
              ) : null}
            </div>
          </div>
        )}
      </section>

      <section className="sv-card p-5">
        <h2 className="text-sm font-semibold text-inst-navy">Anomalies by detector</h2>
        <p className="mt-1 text-sm text-inst-text-secondary">Detected quality signals grouped by detector.</p>
        {detectors.isError ? (
          <div className="mt-4">
            <ErrorState message="Detector analytics could not be loaded." onRetry={() => detectors.refetch()} />
          </div>
        ) : detectors.isPending ? (
          <div className="mt-4">
            <ChartSkeleton />
          </div>
        ) : detectorItems.length ? (
          <div className="mt-4">
            <DetectorDistributionChart items={detectorItems} />
          </div>
        ) : (
          <div className="mt-4">
            <EmptyState
              title="No data available"
              detail={
                detectorPayload?.message ||
                (cumulative
                  ? "There is not enough data across processed batches to display this analysis."
                  : "There is not enough data in this batch to display this analysis.")
              }
            />
          </div>
        )}
      </section>

      <section className="sv-card p-5">
        <h2 className="text-sm font-semibold text-inst-navy">District employment rates</h2>
        <p className="mt-1 text-sm text-inst-text-secondary">
          {cumulative
            ? "Weighted employment rate distribution across districts in all processed batches."
            : "Employment rate distribution across districts in the selected batch."}
        </p>
        {explorer.isError ? (
          <div className="mt-4">
            <ErrorState message="District analytics could not be loaded." onRetry={() => explorer.refetch()} />
          </div>
        ) : explorer.isPending ? (
          <div className="mt-4">
            <ChartSkeleton />
          </div>
        ) : geoItems.length ? (
          <div className="mt-4">
            <GeographicComparisonChart items={geoItems} />
          </div>
        ) : (
          <div className="mt-4">
            <EmptyState
              title="No data available"
              detail={geoPayload?.message || "There is not enough data in this batch to display this analysis."}
            />
          </div>
        )}
      </section>

      <section className="sv-card p-5">
        <h2 className="text-sm font-semibold text-inst-navy">Enumerator comparison</h2>
        <p className="mt-1 text-sm text-inst-text-secondary">
          {cumulative
            ? "Weighted employment rate comparison across enumerators in all processed batches."
            : "Employment rate comparison across enumerators in the selected batch."}
        </p>
        {enumerators.isError ? (
          <div className="mt-4">
            <ErrorState message="Enumerator analytics could not be loaded." onRetry={() => enumerators.refetch()} />
          </div>
        ) : enumerators.isPending ? (
          <div className="mt-4">
            <ChartSkeleton />
          </div>
        ) : comparison.length ? (
          <div className="mt-4">
            <EnumeratorComparisonChart items={comparison} />
          </div>
        ) : (
          <div className="mt-4">
            <EmptyState
              title="No data available"
              detail={enumPayload?.message || "There is not enough data in this batch to display this analysis."}
            />
          </div>
        )}
      </section>
    </div>
  );
}

function PageHeader({
  batchId,
  view,
  onViewChange,
}: {
  batchId: string;
  view: DataView;
  onViewChange: (next: DataView) => void;
}) {
  return (
    <div>
      <p className="sv-label">Analytics</p>
      <h1 className="mt-1 text-2xl font-semibold text-inst-navy">Quality explorer</h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-inst-text-secondary">
        Explore statistical patterns, anomalies and quality signals across the selected survey batch.
      </p>
      <div className="mt-4">
        <ViewScopeSelect view={view} onChange={onViewChange} />
      </div>
      <ViewScopeBanner view={view} batchId={batchId} />
    </div>
  );
}
