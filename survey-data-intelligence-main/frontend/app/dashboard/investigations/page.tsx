"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, ClipboardList, FolderSearch, ShieldAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { Kpi } from "@/components/kpi";
import { EmptyState, ErrorState, InvestigationStatusBadge, SeverityBadge } from "@/components/status";
import { listInvestigations } from "@/lib/api";

const STATUS_FILTERS = ["OPEN", "IN_REVIEW", "REQUIRES_REENUMERATION", "ESCALATED", "RESOLVED_VALID", "RESOLVED_INVALID"] as const;
const PRIORITY_FILTERS = ["CRITICAL", "HIGH", "MEDIUM", "LOW"] as const;

const STATUS_FILTER_LABEL: Record<(typeof STATUS_FILTERS)[number], string> = {
  OPEN: "OPEN",
  IN_REVIEW: "IN REVIEW",
  REQUIRES_REENUMERATION: "RE-ENUMERATION REQUIRED",
  ESCALATED: "ESCALATED",
  RESOLVED_VALID: "RESOLVED VALID",
  RESOLVED_INVALID: "RESOLVED INVALID",
};

export default function InvestigationsPage() {
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [district, setDistrict] = useState("");
  const [enumerator, setEnumerator] = useState("");
  const [assigned, setAssigned] = useState("");
  const query = useQuery({
    queryKey: ["investigations", status, priority, district, enumerator, assigned],
    queryFn: () =>
      listInvestigations({
        status: status || undefined,
        priority: priority || undefined,
        district: district || undefined,
        enumerator: enumerator || undefined,
        assigned_to: assigned || undefined,
      }),
  });

  const kpis = query.data?.kpis;
  const items = query.data?.items ?? [];
  const kpiReady = Boolean(query.data);
  const filtersActive = Boolean(status || priority || district || enumerator || assigned);
  const districts = useMemo(() => Array.from(new Set(items.map((item) => item.district_id).filter(Boolean))), [items]);
  const enumerators = useMemo(
    () => Array.from(new Set(items.map((item) => item.enumerator_id).filter(Boolean))),
    [items]
  );

  function clearFilters() {
    setStatus("");
    setPriority("");
    setDistrict("");
    setEnumerator("");
    setAssigned("");
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="sv-label">Investigations</p>
        <h1 className="mt-1 text-2xl font-semibold text-inst-navy">Supervisor workflow</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-inst-text-secondary">
          Review automated quality signals and record the appropriate supervisory decision.
        </p>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-inst-text">
          Human decisions after automated validation. Risk scores are not changed here.
        </p>
      </div>

      {query.isError ? (
        <ErrorState message="Unable to load investigations." onRetry={() => query.refetch()} />
      ) : null}

      {query.isPending ? (
        <div className="space-y-3" role="status" aria-live="polite">
          <p className="sr-only">Loading investigations…</p>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {Array.from({ length: 5 }, (_, index) => (
              <div key={index} className="sv-skeleton h-24 w-full" />
            ))}
          </div>
          <div className="sv-card space-y-2 p-4">
            {Array.from({ length: 6 }, (_, index) => (
              <div key={index} className="sv-skeleton h-10 w-full" />
            ))}
          </div>
        </div>
      ) : null}

      {query.isSuccess ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <Kpi
              label="Open"
              value={kpis?.OPEN ?? null}
              available={kpiReady}
              hint="Open for supervisor review"
              icon={ClipboardList}
              tone="info"
            />
            <Kpi
              label="In review"
              value={kpis?.IN_REVIEW ?? null}
              available={kpiReady}
              hint="Under supervisor review"
              icon={FolderSearch}
              tone="info"
            />
            <Kpi
              label="Re-enumeration required"
              value={kpis?.REQUIRES_REENUMERATION ?? null}
              available={kpiReady}
              hint="Marked as requiring re-enumeration"
              icon={AlertTriangle}
              tone="warning"
            />
            <Kpi
              label="Escalated"
              value={kpis?.ESCALATED ?? null}
              available={kpiReady}
              hint="Escalated for further review"
              icon={ShieldAlert}
              tone="critical"
            />
            <Kpi
              label="Resolved"
              value={kpis?.resolved ?? null}
              available={kpiReady}
              hint="Closed as valid or invalid"
              icon={CheckCircle2}
              tone="success"
            />
          </div>

          <div className="sv-card space-y-3 p-4">
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-5">
              <label className="block">
                <span className="sv-label">Status</span>
                <select
                  className="sv-control mt-1 w-full"
                  value={status}
                  onChange={(event) => setStatus(event.target.value)}
                  aria-label="Status"
                >
                  <option value="">All statuses</option>
                  {STATUS_FILTERS.map((item) => (
                    <option key={item} value={item}>
                      {STATUS_FILTER_LABEL[item]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="sv-label">Priority</span>
                <select
                  className="sv-control mt-1 w-full"
                  value={priority}
                  onChange={(event) => setPriority(event.target.value)}
                  aria-label="Priority"
                >
                  <option value="">All priorities</option>
                  {PRIORITY_FILTERS.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="sv-label">District</span>
                <select
                  className="sv-control mt-1 w-full"
                  value={district}
                  onChange={(event) => setDistrict(event.target.value)}
                  aria-label="District"
                >
                  <option value="">All districts</option>
                  {districts.map((item) => (
                    <option key={item!} value={item!}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="sv-label">Enumerator</span>
                <select
                  className="sv-control mt-1 w-full"
                  value={enumerator}
                  onChange={(event) => setEnumerator(event.target.value)}
                  aria-label="Enumerator"
                >
                  <option value="">All enumerators</option>
                  {enumerators.map((item) => (
                    <option key={item!} value={item!}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="sv-label">Assigned supervisor</span>
                <input
                  className="sv-control mt-1 w-full"
                  placeholder="Assigned supervisor"
                  value={assigned}
                  onChange={(event) => setAssigned(event.target.value)}
                  aria-label="Assigned supervisor"
                />
              </label>
            </div>
            {filtersActive ? (
              <button type="button" className="sv-btn-outline px-2 py-1 text-xs" onClick={clearFilters}>
                Clear filters
              </button>
            ) : null}
          </div>

          {!items.length ? (
            <EmptyState
              title={filtersActive ? "No investigations match the selected filters." : "No investigation records found."}
              detail={
                filtersActive
                  ? "Change or clear the filters to see other investigation records."
                  : "Open a high-risk record and start a review to create a case."
              }
            />
          ) : (
            <div className="sv-card overflow-x-auto">
              <table className="sv-table">
                <thead>
                  <tr>
                    <th>Record</th>
                    <th className="sv-num">Risk</th>
                    <th>Severity</th>
                    <th>Enumerator</th>
                    <th>District</th>
                    <th>Priority</th>
                    <th>Status</th>
                    <th>Assigned</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <Link
                          className="font-mono text-sm font-semibold"
                          href={`/dashboard/records/${item.record_id}?batchId=${item.batch_id}`}
                          title={`Open investigation for ${item.record_id}`}
                        >
                          {item.record_id}
                        </Link>
                      </td>
                      <td className="sv-num tabular-nums font-medium text-inst-navy">{item.risk_score ?? "—"}</td>
                      <td>
                        {item.severity ? <SeverityBadge value={item.severity} /> : <span className="text-inst-text-secondary">—</span>}
                      </td>
                      <td>{item.enumerator_id ?? "—"}</td>
                      <td>{item.district_id ?? "—"}</td>
                      <td>
                        <SeverityBadge value={item.priority} />
                      </td>
                      <td>
                        <InvestigationStatusBadge value={item.status} />
                      </td>
                      <td>{item.assigned_to ?? "—"}</td>
                      <td className="whitespace-nowrap text-inst-text-secondary">
                        {item.updated_at ? new Date(item.updated_at).toLocaleString() : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
