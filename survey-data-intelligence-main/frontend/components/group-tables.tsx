"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, ClipboardList, Layers, Percent, Users } from "lucide-react";
import { ChartTooltip, chartAxis, chartGrid } from "@/components/charts/chart-style";
import { Kpi } from "@/components/kpi";
import { BatchSelectionGate } from "@/components/shell";
import { EmptyState, ErrorState } from "@/components/status";
import { getClusters, getDistricts, getEnumerators } from "@/lib/api";
import type { GroupRow } from "@/lib/api/types";
import type { DataView } from "@/lib/data-view";
import { DATA_VIEW_CURRENT, isCumulativeView } from "@/lib/data-view";

function listQueryKey(grain: string, view: DataView, batchId: string) {
  return isCumulativeView(view) ? [grain, "cumulative"] : [grain, batchId];
}

export function EnumeratorTable({ view = DATA_VIEW_CURRENT }: { view?: DataView }) {
  return (
    <BatchSelectionGate emptyDetail="Ingest data before reviewing enumerators.">
      {(batchId) => <EnumeratorTableInner batchId={batchId} view={view} />}
    </BatchSelectionGate>
  );
}

function formatRate(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function weightedRate(rows: GroupRow[], key: "anomaly_rate" | "missingness_rate"): number | null {
  let weighted = 0;
  let weight = 0;
  for (const row of rows) {
    const rate = row[key];
    if (rate == null) continue;
    weighted += rate * row.records;
    weight += row.records;
  }
  return weight ? weighted / weight : null;
}

function countClass(value: number, tone: "critical" | "warning"): string {
  if (!value) return "sv-num text-inst-text-secondary";
  return tone === "critical" ? "sv-num font-semibold text-inst-critical" : "sv-num font-semibold text-inst-warning";
}

function EnumeratorTableInner({ batchId, view }: { batchId: string; view: DataView }) {
  const query = useQuery({
    queryKey: listQueryKey("enumerators", view, batchId),
    queryFn: () => getEnumerators(batchId, view),
    retry: false,
  });
  if (query.isPending) {
    return (
      <div className="space-y-3" role="status" aria-live="polite">
        <p className="sr-only">Loading enumerators…</p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }, (_, index) => (
            <div key={index} className="sv-skeleton h-24 w-full" />
          ))}
        </div>
        <div className="sv-card space-y-2 p-4">
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} className="sv-skeleton h-10 w-full" />
          ))}
        </div>
      </div>
    );
  }
  if (query.isError) return <ErrorState message="Unable to load enumerators." onRetry={() => query.refetch()} />;
  if (query.data && !query.data.available) {
    return <EmptyState title="Unavailable" detail={query.data.message || "Enumerator summary is not available for this batch."} />;
  }
  const items = query.data?.items ?? [];
  if (!items.length) {
    return (
      <EmptyState
        title="No enumerators"
        detail={
          isCumulativeView(view)
            ? "No enumerator profiles across processed batches."
            : "No enumerator profiles for this batch."
        }
      />
    );
  }

  const records = items.reduce((sum, row) => sum + row.records, 0);
  const high = items.reduce((sum, row) => sum + row.high_risk, 0);
  const medium = items.reduce((sum, row) => sum + row.medium_risk, 0);
  const anomaly = weightedRate(items, "anomaly_rate");
  const missingness = weightedRate(items, "missingness_rate");
  const showEnumeratorCount = items.some((row) => row.enumerators != null);
  const districtMap = new Map<string, { enumerators: number; records: number; high: number; medium: number }>();
  for (const row of items) {
    if (!row.district_id) continue;
    const current = districtMap.get(row.district_id) ?? { enumerators: 0, records: 0, high: 0, medium: 0 };
    current.enumerators += 1;
    current.records += row.records;
    current.high += row.high_risk;
    current.medium += row.medium_risk;
    districtMap.set(row.district_id, current);
  }
  const districts = [...districtMap.entries()].sort((a, b) => a[0].localeCompare(b[0]));

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
        <Kpi label="Enumerators" value={items.length} available hint="Enumerators in this listing" icon={Users} tone="info" />
        <Kpi label="Total records" value={records} available hint="Sum of records in this listing" icon={Layers} tone="info" />
        <Kpi label="High risk" value={high} available hint="Sum of high-risk records in this listing" icon={AlertTriangle} tone="critical" />
        <Kpi label="Medium risk" value={medium} available hint="Sum of medium-risk records in this listing" icon={ClipboardList} tone="warning" />
        {anomaly != null ? (
          <Kpi
            label="Average anomaly rate"
            value={formatRate(anomaly)}
            available
            hint="Weighted by records in this listing"
            icon={Percent}
            tone="neutral"
          />
        ) : null}
        {missingness != null ? (
          <Kpi
            label="Missingness"
            value={formatRate(missingness)}
            available
            hint="Weighted by records in this listing"
            icon={Percent}
            tone={missingness > 0 ? "warning" : "neutral"}
          />
        ) : null}
      </div>

      <div className="sv-card overflow-x-auto">
        <table className="sv-table">
          <thead>
            <tr>
              <th>Enumerator ID</th>
              <th>District</th>
              <th className="sv-num">Records</th>
              <th className="sv-num">High risk</th>
              <th className="sv-num">Medium risk</th>
              <th className="sv-num">Anomaly rate</th>
              <th className="sv-num">Missingness</th>
              {showEnumeratorCount ? <th className="sv-num">Enumerators</th> : null}
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td>
                  <Link className="font-mono text-sm font-semibold" href={`/dashboard/enumerators/${row.id}`}>
                    {row.id}
                  </Link>
                </td>
                <td>{row.district_id ?? "—"}</td>
                <td className="sv-num tabular-nums">{row.records}</td>
                <td className={countClass(row.high_risk, "critical")}>{row.high_risk}</td>
                <td className={countClass(row.medium_risk, "warning")}>{row.medium_risk}</td>
                <td className={row.anomaly_rate ? "sv-num font-medium text-inst-navy" : "sv-num text-inst-text-secondary"}>
                  {formatRate(row.anomaly_rate)}
                </td>
                <td className={row.missingness_rate ? "sv-num font-medium text-inst-warning" : "sv-num text-inst-text-secondary"}>
                  {formatRate(row.missingness_rate)}
                </td>
                {showEnumeratorCount ? <td className="sv-num">{row.enumerators ?? "—"}</td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {districts.length ? (
        <section className="sv-card overflow-x-auto">
          <div className="border-b border-inst-border px-4 py-3">
            <h2 className="text-sm font-semibold text-inst-navy">Workload by district</h2>
            <p className="mt-1 text-xs text-inst-text-secondary">Derived from enumerator rows in this listing.</p>
          </div>
          <table className="sv-table">
            <thead>
              <tr>
                <th>District</th>
                <th className="sv-num">Enumerators</th>
                <th className="sv-num">Records</th>
                <th className="sv-num">High risk</th>
                <th className="sv-num">Medium risk</th>
              </tr>
            </thead>
            <tbody>
              {districts.map(([district, row]) => (
                <tr key={district}>
                  <td>{district}</td>
                  <td className="sv-num tabular-nums">{row.enumerators}</td>
                  <td className="sv-num tabular-nums">{row.records}</td>
                  <td className={countClass(row.high, "critical")}>{row.high}</td>
                  <td className={countClass(row.medium, "warning")}>{row.medium}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </div>
  );
}

export function ClusterTable({ view = DATA_VIEW_CURRENT }: { view?: DataView }) {
  return (
    <BatchSelectionGate emptyDetail="Ingest data before reviewing clusters.">
      {(batchId) => <ClusterTableInner batchId={batchId} view={view} />}
    </BatchSelectionGate>
  );
}

function ClusterTableInner({ batchId, view }: { batchId: string; view: DataView }) {
  const query = useQuery({
    queryKey: listQueryKey("clusters", view, batchId),
    queryFn: () => getClusters(batchId, view),
    retry: false,
  });
  if (query.isPending) {
    return (
      <div className="space-y-3" role="status" aria-live="polite">
        <p className="sr-only">Loading clusters…</p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }, (_, index) => (
            <div key={index} className="sv-skeleton h-24 w-full" />
          ))}
        </div>
        <div className="sv-card space-y-2 p-4">
          {Array.from({ length: 3 }, (_, index) => (
            <div key={index} className="sv-skeleton h-10 w-full" />
          ))}
        </div>
      </div>
    );
  }
  if (query.isError) return <ErrorState message="Unable to load clusters." onRetry={() => query.refetch()} />;
  if (query.data && !query.data.available) {
    return <EmptyState title="Unavailable" detail={query.data.message || "Cluster summary is not available for this batch."} />;
  }
  const items = query.data?.items ?? [];
  if (!items.length) {
    return (
      <EmptyState
        title="No clusters"
        detail={
          isCumulativeView(view)
            ? "No cluster profiles across processed batches."
            : "No cluster profiles for this batch."
        }
      />
    );
  }

  const records = items.reduce((sum, row) => sum + row.records, 0);
  const high = items.reduce((sum, row) => sum + row.high_risk, 0);
  const medium = items.reduce((sum, row) => sum + row.medium_risk, 0);
  const anomaly = weightedRate(items, "anomaly_rate");
  const districtMap = new Map<string, { clusters: number; records: number; high: number; medium: number }>();
  for (const row of items) {
    if (!row.district_id) continue;
    const current = districtMap.get(row.district_id) ?? { clusters: 0, records: 0, high: 0, medium: 0 };
    current.clusters += 1;
    current.records += row.records;
    current.high += row.high_risk;
    current.medium += row.medium_risk;
    districtMap.set(row.district_id, current);
  }
  const districts = [...districtMap.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  const rateChart = items
    .filter((row) => row.anomaly_rate != null)
    .map((row) => ({ id: row.id, rate: Number(((row.anomaly_rate ?? 0) * 100).toFixed(1)) }));

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
        <Kpi label="Clusters" value={items.length} available hint="Clusters in this listing" icon={Layers} tone="info" />
        <Kpi label="Total records" value={records} available hint="Sum of records in this listing" icon={ClipboardList} tone="info" />
        <Kpi label="High risk" value={high} available hint="Sum of high-risk records in this listing" icon={AlertTriangle} tone="critical" />
        <Kpi label="Medium risk" value={medium} available hint="Sum of medium-risk records in this listing" icon={AlertTriangle} tone="warning" />
        {anomaly != null ? (
          <Kpi
            label="Average anomaly rate"
            value={formatRate(anomaly)}
            available
            hint="Weighted by records in this listing"
            icon={Percent}
            tone="neutral"
          />
        ) : null}
      </div>

      <div className="sv-card overflow-x-auto">
        <table className="sv-table">
          <thead>
            <tr>
              <th>Cluster ID</th>
              <th>District</th>
              <th className="sv-num">Records</th>
              <th className="sv-num">High risk</th>
              <th className="sv-num">Medium risk</th>
              <th className="sv-num">Anomaly rate</th>
              <th className="sv-num">Missingness</th>
              <th className="sv-num">Enumerators</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td className="font-mono text-sm font-semibold text-inst-navy">{row.id}</td>
                <td>{row.district_id ?? "—"}</td>
                <td className="sv-num tabular-nums">{row.records}</td>
                <td className={countClass(row.high_risk, "critical")}>{row.high_risk}</td>
                <td className={countClass(row.medium_risk, "warning")}>{row.medium_risk}</td>
                <td className={row.anomaly_rate ? "sv-num font-medium text-inst-navy" : "sv-num text-inst-text-secondary"}>
                  {formatRate(row.anomaly_rate)}
                </td>
                <td className={row.missingness_rate ? "sv-num font-medium text-inst-warning" : "sv-num text-inst-text-secondary"}>
                  {formatRate(row.missingness_rate)}
                </td>
                <td className="sv-num tabular-nums">{row.enumerators ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-sm text-inst-text-secondary">Open Anomalies and filter by cluster ID to drill into records.</p>

      {districts.length ? (
        <section className="sv-card overflow-x-auto">
          <div className="border-b border-inst-border px-4 py-3">
            <h2 className="text-sm font-semibold text-inst-navy">Cluster workload by district</h2>
            <p className="mt-1 text-xs text-inst-text-secondary">Derived from cluster rows in this listing.</p>
          </div>
          <table className="sv-table">
            <thead>
              <tr>
                <th>District</th>
                <th className="sv-num">Clusters</th>
                <th className="sv-num">Records</th>
                <th className="sv-num">High risk</th>
                <th className="sv-num">Medium risk</th>
              </tr>
            </thead>
            <tbody>
              {districts.map(([district, row]) => (
                <tr key={district}>
                  <td>{district}</td>
                  <td className="sv-num tabular-nums">{row.clusters}</td>
                  <td className="sv-num tabular-nums">{row.records}</td>
                  <td className={countClass(row.high, "critical")}>{row.high}</td>
                  <td className={countClass(row.medium, "warning")}>{row.medium}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      {rateChart.length ? (
        <section className="sv-card p-5">
          <h2 className="text-sm font-semibold text-inst-navy">Anomaly rate by cluster</h2>
          <p className="mt-1 text-xs text-inst-text-secondary">Existing anomaly rates from this listing.</p>
          <div className="mt-3" style={{ height: Math.min(280, Math.max(160, rateChart.length * 44)) }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rateChart} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
                <CartesianGrid stroke={chartGrid.stroke} vertical={false} strokeDasharray="0" />
                <XAxis
                  type="number"
                  tick={chartAxis.tick}
                  axisLine={{ stroke: chartAxis.stroke }}
                  tickLine={false}
                  unit="%"
                />
                <YAxis
                  type="category"
                  dataKey="id"
                  width={48}
                  tick={chartAxis.tick}
                  axisLine={{ stroke: chartAxis.stroke }}
                  tickLine={false}
                />
                <Tooltip content={<ChartTooltip labelTitle="Cluster" valueTitle="Anomaly rate (%)" />} />
                <Bar dataKey="rate" fill="#1d4e89" maxBarSize={18} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      ) : null}
    </div>
  );
}

export function DistrictCharts({ view = DATA_VIEW_CURRENT }: { view?: DataView }) {
  return (
    <BatchSelectionGate emptyDetail="Ingest data before reviewing districts.">
      {(batchId) => <DistrictChartsInner batchId={batchId} view={view} />}
    </BatchSelectionGate>
  );
}

function leaders(rows: GroupRow[], valueOf: (row: GroupRow) => number | null): { ids: string[]; value: number } | null {
  const scored = rows
    .map((row) => ({ id: row.id, value: valueOf(row) }))
    .filter((row): row is { id: string; value: number } => row.value != null);
  if (!scored.length) return null;
  const max = Math.max(...scored.map((row) => row.value));
  return { ids: scored.filter((row) => row.value === max).map((row) => row.id), value: max };
}

function formatLeader(result: { ids: string[]; value: number } | null, format: (value: number) => string): string | null {
  if (!result) return null;
  const names = result.ids.join(", ");
  return `${names} (${format(result.value)})`;
}

function DistrictChartsInner({ batchId, view }: { batchId: string; view: DataView }) {
  const query = useQuery({
    queryKey: listQueryKey("districts", view, batchId),
    queryFn: () => getDistricts(batchId, view),
    retry: false,
  });
  if (query.isPending) {
    return (
      <div className="space-y-3" role="status" aria-live="polite">
        <p className="sr-only">Loading districts…</p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }, (_, index) => (
            <div key={index} className="sv-skeleton h-24 w-full" />
          ))}
        </div>
        <div className="sv-card space-y-2 p-4">
          {Array.from({ length: 3 }, (_, index) => (
            <div key={index} className="sv-skeleton h-10 w-full" />
          ))}
        </div>
      </div>
    );
  }
  if (query.isError) return <ErrorState message="Unable to load districts." onRetry={() => query.refetch()} />;
  if (query.data && !query.data.available) {
    return <EmptyState title="Unavailable" detail={query.data.message || "District summary is not available for this batch."} />;
  }
  const items = query.data?.items ?? [];
  if (!items.length) {
    return (
      <EmptyState
        title="No districts"
        detail={
          isCumulativeView(view)
            ? "No district profiles across processed batches."
            : "No district profiles for this batch."
        }
      />
    );
  }

  const records = items.reduce((sum, row) => sum + row.records, 0);
  const high = items.reduce((sum, row) => sum + row.high_risk, 0);
  const medium = items.reduce((sum, row) => sum + row.medium_risk, 0);
  const anomaly = weightedRate(items, "anomaly_rate");
  const duplicateId = items.every((row) => !row.district_id || row.district_id === row.id);
  const countChart = items.map((item) => ({
    name: item.id,
    high: item.high_risk,
    medium: item.medium_risk,
  }));
  const rateChart = items
    .filter((item) => item.anomaly_rate != null)
    .map((item) => ({ id: item.id, rate: Number(((item.anomaly_rate ?? 0) * 100).toFixed(1)) }));
  const mostRecords = formatLeader(leaders(items, (row) => row.records), (value) => String(value));
  const highestAnomaly = formatLeader(leaders(items, (row) => row.anomaly_rate), formatRate);
  const highestMedium = formatLeader(leaders(items, (row) => row.medium_risk), (value) => String(value));
  const hasInsight = Boolean(mostRecords || highestAnomaly || highestMedium);

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
        <Kpi label="Districts" value={items.length} available hint="Districts in this listing" icon={Layers} tone="info" />
        <Kpi label="Total records" value={records} available hint="Sum of records in this listing" icon={ClipboardList} tone="info" />
        <Kpi label="High risk" value={high} available hint="Sum of high-risk records in this listing" icon={AlertTriangle} tone="critical" />
        <Kpi label="Medium risk" value={medium} available hint="Sum of medium-risk records in this listing" icon={AlertTriangle} tone="warning" />
        {anomaly != null ? (
          <Kpi
            label="Average anomaly rate"
            value={formatRate(anomaly)}
            available
            hint="Weighted by records in this listing"
            icon={Percent}
            tone="neutral"
          />
        ) : null}
      </div>

      <div className="sv-card overflow-x-auto">
        <table className="sv-table">
          <thead>
            <tr>
              <th>District</th>
              {!duplicateId ? <th>ID</th> : null}
              <th className="sv-num">Records</th>
              <th className="sv-num">High risk</th>
              <th className="sv-num">Medium risk</th>
              <th className="sv-num">Anomaly rate</th>
              <th className="sv-num">Missingness</th>
              <th className="sv-num">Enumerators</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td className="font-mono text-sm font-semibold text-inst-navy">{row.district_id ?? row.id}</td>
                {!duplicateId ? <td className="font-mono text-sm">{row.id}</td> : null}
                <td className="sv-num tabular-nums">{row.records}</td>
                <td className={countClass(row.high_risk, "critical")}>{row.high_risk}</td>
                <td className={countClass(row.medium_risk, "warning")}>{row.medium_risk}</td>
                <td className={row.anomaly_rate ? "sv-num font-medium text-inst-navy" : "sv-num text-inst-text-secondary"}>
                  {formatRate(row.anomaly_rate)}
                </td>
                <td className={row.missingness_rate ? "sv-num font-medium text-inst-warning" : "sv-num text-inst-text-secondary"}>
                  {formatRate(row.missingness_rate)}
                </td>
                <td className="sv-num tabular-nums">{row.enumerators ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="sv-card p-5">
          <h2 className="text-sm font-semibold text-inst-navy">District high-risk counts</h2>
          <p className="mt-1 text-xs text-inst-text-secondary">High-risk and medium-risk record counts from this listing.</p>
          <div className="mt-3 h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={countChart} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
                <CartesianGrid stroke={chartGrid.stroke} vertical={false} strokeDasharray="0" />
                <XAxis dataKey="name" tick={chartAxis.tick} axisLine={{ stroke: chartAxis.stroke }} tickLine={false} />
                <YAxis allowDecimals={false} tick={chartAxis.tick} axisLine={{ stroke: chartAxis.stroke }} tickLine={false} width={36} />
                <Tooltip content={<ChartTooltip labelTitle="District" />} />
                <Bar dataKey="high" name="High risk" fill="#b42318" maxBarSize={28} />
                <Bar dataKey="medium" name="Medium risk" fill="#b45309" maxBarSize={28} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>

        {rateChart.length ? (
          <section className="sv-card p-5">
            <h2 className="text-sm font-semibold text-inst-navy">District anomaly rate</h2>
            <p className="mt-1 text-xs text-inst-text-secondary">Anomaly rates from this listing. Unusual is not automatically incorrect.</p>
            <div className="mt-3" style={{ height: Math.min(224, Math.max(160, rateChart.length * 48)) }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rateChart} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
                  <CartesianGrid stroke={chartGrid.stroke} vertical={false} strokeDasharray="0" />
                  <XAxis type="number" tick={chartAxis.tick} axisLine={{ stroke: chartAxis.stroke }} tickLine={false} unit="%" />
                  <YAxis
                    type="category"
                    dataKey="id"
                    width={48}
                    tick={chartAxis.tick}
                    axisLine={{ stroke: chartAxis.stroke }}
                    tickLine={false}
                  />
                  <Tooltip content={<ChartTooltip labelTitle="District" valueTitle="Anomaly rate (%)" />} />
                  <Bar dataKey="rate" fill="#1d4e89" maxBarSize={18} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        ) : null}
      </div>

      {hasInsight ? (
        <section className="sv-card p-5">
          <h2 className="text-sm font-semibold text-inst-navy">District comparison</h2>
          <p className="mt-1 text-xs text-inst-text-secondary">Descriptive comparisons from this listing only.</p>
          <dl className="mt-4 grid gap-3 sm:grid-cols-3">
            {mostRecords ? (
              <div>
                <dt className="sv-label">Most records</dt>
                <dd className="mt-1 text-sm font-medium text-inst-navy">{mostRecords}</dd>
              </div>
            ) : null}
            {highestAnomaly ? (
              <div>
                <dt className="sv-label">Highest anomaly rate</dt>
                <dd className="mt-1 text-sm font-medium text-inst-navy">{highestAnomaly}</dd>
              </div>
            ) : null}
            {highestMedium ? (
              <div>
                <dt className="sv-label">Highest medium-risk count</dt>
                <dd className="mt-1 text-sm font-medium text-inst-navy">{highestMedium}</dd>
              </div>
            ) : null}
          </dl>
        </section>
      ) : null}
    </div>
  );
}
