"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { BatchSelectionGate } from "@/components/shell";
import { EmptyState, ErrorState, LoadingState, SeverityBadge } from "@/components/status";
import { getEnumerator } from "@/lib/api";
import { resolveRouteParam } from "@/lib/batch-detail-state";

export default function EnumeratorDetailPage() {
  const params = useParams<{ id: string }>();
  const enumeratorId = resolveRouteParam(params.id);
  return (
    <BatchSelectionGate emptyDetail="Select a batch first.">
      {(batchId) => <EnumeratorDetailInner batchId={batchId} enumeratorId={enumeratorId} />}
    </BatchSelectionGate>
  );
}

function EnumeratorDetailInner({ batchId, enumeratorId }: { batchId: string; enumeratorId: string }) {
  const query = useQuery({
    queryKey: ["enumerator", batchId, enumeratorId],
    queryFn: () => getEnumerator(enumeratorId, batchId),
    enabled: Boolean(enumeratorId),
    retry: false,
  });
  if (!enumeratorId) return <EmptyState title="Enumerator not found" detail="Missing enumerator id." />;
  if (query.isPending) return <LoadingState message="Loading enumerator…" />;
  if (query.isError) return <ErrorState message="Enumerator detail is unavailable." onRetry={() => query.refetch()} />;
  const row = query.data?.items[0];
  if (query.data && !query.data.available) {
    return <EmptyState title="Enumerator not found" detail={query.data.message || ""} />;
  }
  if (!row) return <EmptyState title="Enumerator not found" detail="No profile for this enumerator in the selected batch." />;
  return (
    <div className="space-y-4">
      <div>
        <p className="sv-label">Enumerator</p>
        <h1 className="text-xl font-semibold">{row.id}</h1>
        <p className="text-sm text-slate-400">District {row.district_id ?? "—"} · Cluster {row.cluster_id ?? "—"}</p>
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        <div className="sv-card p-4"><p className="sv-label">Records</p><p className="text-2xl">{row.records}</p></div>
        <div className="sv-card p-4"><p className="sv-label">High risk</p><p className="text-2xl">{row.high_risk}</p></div>
        <div className="sv-card p-4"><p className="sv-label">Anomaly rate</p><p className="text-2xl">{row.anomaly_rate == null ? "—" : `${(row.anomaly_rate * 100).toFixed(1)}%`}</p></div>
        <div className="sv-card p-4"><p className="sv-label">Missingness</p><p className="text-2xl">{row.missingness_rate == null ? "—" : `${(row.missingness_rate * 100).toFixed(1)}%`}</p></div>
      </div>
      <div className="sv-card p-4">
        <p className="sv-label">Common evidence sources</p>
        <p className="mt-2 text-sm">{query.data?.common_sources.join(", ") || "None recorded"}</p>
      </div>
      <div className="sv-card overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="text-xs uppercase text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left">Record</th>
              <th className="px-3 py-2 text-left">Risk</th>
              <th className="px-3 py-2 text-left">Severity</th>
            </tr>
          </thead>
          <tbody>
            {(query.data?.high_risk_records ?? []).map((item) => (
              <tr key={item.record_id} className="border-t border-slate-800">
                <td className="px-3 py-2">
                  <Link className="text-sky-300 underline" href={`/dashboard/records/${item.record_id}?batchId=${item.batch_id}`}>
                    {item.record_id}
                  </Link>
                </td>
                <td className="px-3 py-2">{item.risk_score != null ? item.risk_score.toFixed(1) : "—"}</td>
                <td className="px-3 py-2"><SeverityBadge value={item.severity} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
