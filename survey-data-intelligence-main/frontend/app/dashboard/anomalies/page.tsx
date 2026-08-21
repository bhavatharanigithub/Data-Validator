"use client";

import { useQuery } from "@tanstack/react-query";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { ClipboardList, FolderSearch } from "lucide-react";
import { AnomalyClassification } from "@/components/AnomalyClassification";
import { DetectorBadge } from "@/components/DetectorBadge";
import { Kpi } from "@/components/kpi";
import { BatchSelectionGate } from "@/components/shell";
import { EmptyState, ErrorState, SeverityBadge } from "@/components/status";
import { getAnomalies, listInvestigations } from "@/lib/api";
import type { AnomalyRow } from "@/lib/api/types";
import { aiStatusLabel } from "@/lib/batch-detail-state";

const helper = createColumnHelper<AnomalyRow & { investigation: string }>();

const SOURCE_LABELS: Record<string, string> = {
  rules: "Rules",
  statistics: "Statistics",
  ml: "ML",
};

const AGREEMENT_LABELS: Record<string, string> = {
  strong: "Strong",
  mixed: "Mixed",
  single_source: "Single source",
  insufficient: "Insufficient",
};

const DEFAULT_QUEUE_SCOPE = "review_and_confirmed";

const SCOPE_LABELS: Record<string, string> = {
  confirmed: "Confirmed",
  review: "Review",
  review_and_confirmed: "Review + confirmed",
  all: "All records",
};

function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  return value.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (char) => char.toUpperCase());
}

function sourceLabel(value: string): string {
  return SOURCE_LABELS[value] ?? humanize(value);
}

type QueueColumnMeta = { width: number; wrapHeader?: boolean };

function queueMeta(column: { columnDef: { meta?: unknown } }): QueueColumnMeta {
  const meta = column.columnDef.meta as QueueColumnMeta | undefined;
  return { width: meta?.width ?? 110, wrapHeader: Boolean(meta?.wrapHeader) };
}

export default function AnomaliesPage() {
  return (
    <Suspense fallback={<p className="text-sm text-inst-text-secondary">Loading queue…</p>}>
      <AnomaliesPageInner />
    </Suspense>
  );
}

function AnomaliesPageInner() {
  return (
    <BatchSelectionGate emptyDetail="Ingest data before reviewing anomalies.">
      {(batchId) => <AnomaliesQueue batchId={batchId} />}
    </BatchSelectionGate>
  );
}

function AnomaliesQueue({ batchId }: { batchId: string }) {
  const search = useSearchParams();
  const [page, setPage] = useState(1);
  const [severity, setSeverity] = useState("");
  const [agreement, setAgreement] = useState("");
  const [minRisk, setMinRisk] = useState("");
  const [source, setSource] = useState("");
  const [aiStatus, setAiStatus] = useState("");
  const [q, setQ] = useState("");
  const [investigation, setInvestigation] = useState("");
  const [classification, setClassification] = useState("");
  const [detector, setDetector] = useState(search.get("detector") ?? "");
  const [scope, setScope] = useState(search.get("scope") ?? DEFAULT_QUEUE_SCOPE);
  const [moreFilters, setMoreFilters] = useState(false);

  const query = useQuery({
    queryKey: ["anomalies", batchId, page, severity, agreement, minRisk, source, aiStatus, q, detector, classification, scope],
    queryFn: () =>
      getAnomalies({
        batch_id: batchId ?? undefined,
        page,
        page_size: 25,
        severity: severity || undefined,
        agreement: agreement || undefined,
        min_risk_score: minRisk ? Number(minRisk) : undefined,
        evidence_source: source || undefined,
        ai_status: aiStatus || undefined,
        q: q || undefined,
        detector_type: detector || undefined,
        classification: classification || undefined,
        classification_scope: scope || DEFAULT_QUEUE_SCOPE,
      }),
    enabled: Boolean(batchId),
    retry: false,
  });

  const cases = useQuery({
    queryKey: ["investigations", batchId],
    queryFn: () => listInvestigations({ batch_id: batchId! }),
    enabled: Boolean(batchId),
    retry: false,
  });

  useEffect(() => {
    setPage(1);
  }, [severity, agreement, minRisk, source, aiStatus, q, detector, classification, scope, investigation]);

  const statusByRecord = useMemo(() => {
    const mapped: Record<string, string> = {};
    for (const item of cases.data?.items ?? []) {
      mapped[`${item.batch_id}:${item.record_id}`] = item.status;
    }
    return mapped;
  }, [cases.data]);

  const rows = useMemo(() => {
    const items = (query.data?.items ?? []).map((item) => ({
      ...item,
      investigation: statusByRecord[`${item.batch_id}:${item.record_id}`] ?? "—",
    }));
    if (!investigation) return items;
    return items.filter((item) => item.investigation === investigation);
  }, [query.data, investigation, statusByRecord]);

  const columns = useMemo(
    () => [
      helper.accessor("record_id", {
        header: "ID",
        meta: { width: 70 } satisfies QueueColumnMeta,
        cell: (info) => (
          <Link
            className="font-semibold text-inst-blue hover:underline"
            href={`/dashboard/records/${info.getValue()}?batchId=${info.row.original.batch_id}`}
          >
            {info.getValue()}
          </Link>
        ),
      }),
      helper.accessor("risk_score", {
        header: "Risk",
        meta: { width: 100 } satisfies QueueColumnMeta,
        cell: (info) => {
          const score = info.getValue();
          return (
            <div>
              <p className="text-base font-semibold tabular-nums text-inst-navy">
                {score != null ? score.toFixed(0) : "—"}
              </p>
              {info.row.original.severity ? <SeverityBadge value={info.row.original.severity} /> : null}
            </div>
          );
        },
      }),
      helper.accessor("intelligence_classification", {
        header: "Classification",
        meta: { width: 150, wrapHeader: true } satisfies QueueColumnMeta,
        cell: (info) => <AnomalyClassification value={info.getValue()} />,
      }),
      helper.accessor("primary_detector", {
        header: "Primary signal",
        meta: { width: 150, wrapHeader: true } satisfies QueueColumnMeta,
        cell: (info) => <DetectorBadge value={info.getValue()} />,
      }),
      helper.accessor("anomaly_status", {
        header: "Status",
        meta: { width: 110 } satisfies QueueColumnMeta,
        cell: (info) => <span className="text-sm font-medium text-inst-navy">{humanize(info.getValue())}</span>,
      }),
      helper.accessor("available_sources", {
        id: "evidence",
        header: "Evidence",
        meta: { width: 150 } satisfies QueueColumnMeta,
        cell: (info) => {
          const sources = info.getValue() ?? [];
          if (!sources.length) return <span className="text-inst-text-secondary">—</span>;
          return (
            <div className="flex flex-wrap gap-1">
              {sources.map((item) => (
                <span key={item} className="sv-chip">
                  {sourceLabel(item)}
                </span>
              ))}
            </div>
          );
        },
      }),
      helper.accessor("investigation", {
        header: "Investigation",
        meta: { width: 120, wrapHeader: true } satisfies QueueColumnMeta,
      }),
      helper.display({
        id: "location",
        header: "Location",
        meta: { width: 100 } satisfies QueueColumnMeta,
        cell: (info) => {
          const district = info.row.original.district_id;
          const cluster = info.row.original.cluster_id;
          if (!district && !cluster) return "—";
          return [district, cluster].filter(Boolean).join(" · ");
        },
      }),
      helper.accessor("enumerator_id", {
        header: "Enumerator",
        meta: { width: 110, wrapHeader: true } satisfies QueueColumnMeta,
        cell: (info) => info.getValue() ?? "—",
      }),
      helper.accessor("cluster_id", {
        header: "Cluster",
        meta: { width: 100 } satisfies QueueColumnMeta,
        cell: (info) => info.getValue() ?? "—",
      }),
      helper.accessor("district_id", {
        id: "district",
        header: "District",
        meta: { width: 100 } satisfies QueueColumnMeta,
        cell: (info) => info.getValue() ?? "—",
      }),
      helper.accessor("detectors", {
        id: "detected_by",
        header: "Detected by",
        meta: { width: 110, wrapHeader: true } satisfies QueueColumnMeta,
        cell: (info) => {
          const detectors = info.getValue() ?? [];
          if (!detectors.length) return <span className="text-inst-text-secondary">—</span>;
          return (
            <div className="flex flex-wrap gap-1">
              {detectors.map((item) => (
                <DetectorBadge key={item} value={item} />
              ))}
            </div>
          );
        },
      }),
      helper.accessor("agreement", {
        header: "Agreement",
        meta: { width: 100 } satisfies QueueColumnMeta,
        cell: (info) => AGREEMENT_LABELS[info.getValue()] ?? humanize(info.getValue()),
      }),
      helper.accessor("ai_explanation_status", {
        header: "AI status",
        meta: { width: 110, wrapHeader: true } satisfies QueueColumnMeta,
        cell: (info) => <span className="text-xs text-inst-text-secondary">{aiStatusLabel(info.getValue())}</span>,
      }),
    ],
    []
  );

  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() });
  const filtersActive = Boolean(
    severity || agreement || minRisk || source || aiStatus || q || detector || classification || investigation || (scope && scope !== DEFAULT_QUEUE_SCOPE)
  );

  function clearFilters() {
    setSeverity("");
    setAgreement("");
    setMinRisk("");
    setSource("");
    setAiStatus("");
    setQ("");
    setInvestigation("");
    setClassification("");
    setDetector("");
    setScope(DEFAULT_QUEUE_SCOPE);
    setPage(1);
  }

  const viewTotal = query.data?.total;
  const openInvestigations = cases.isSuccess ? cases.data?.kpis?.OPEN : null;

  return (
    <div className="space-y-6">
      <div>
        <p className="sv-label">Review queue</p>
        <h1 className="mt-1 text-2xl font-semibold text-inst-navy">Quality investigation queue</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-inst-text-secondary">
          Confirmed validation issues and REVIEW records that still need human attention. Each record includes the
          signals and evidence that led to the review. AI can explain findings; it does not make the final decision.
        </p>
      </div>

      {query.isError ? (
        <ErrorState
          message="Unable to load review queue. We couldn't retrieve the current review records."
          onRetry={() => query.refetch()}
        />
      ) : null}

      {!query.isError && query.data && !query.data.available ? (
        <EmptyState title="No fused assessments" detail={query.data.message || "Run fusion before listing anomalies."} />
      ) : null}

      {query.isSuccess && query.data?.available ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <Kpi
            label={scope === "confirmed" ? "Confirmed issues" : "Records in this view"}
            value={viewTotal ?? null}
            available={viewTotal != null}
            hint={SCOPE_LABELS[scope] ? `Scope: ${SCOPE_LABELS[scope]}` : "Matching current filters"}
            icon={FolderSearch}
            tone="info"
          />
          <Kpi
            label="Open investigations"
            value={openInvestigations ?? null}
            available={openInvestigations != null}
            hint="From investigation records for this batch"
            icon={ClipboardList}
            tone="warning"
          />
        </div>
      ) : null}

      <div className="sv-card space-y-3 p-4">
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-6">
          <input
            className="sv-control md:col-span-2"
            placeholder="Search record ID"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            aria-label="Search record ID"
          />
          <select className="sv-control" value={scope} onChange={(event) => setScope(event.target.value)} aria-label="Queue scope">
            <option value="review_and_confirmed">Review + confirmed</option>
            <option value="confirmed">Confirmed</option>
            <option value="review">Review</option>
            <option value="all">All records</option>
          </select>
          <select className="sv-control" value={classification} onChange={(event) => setClassification(event.target.value)} aria-label="Classification">
            <option value="">All classifications</option>
            {["VALIDATION_ERROR", "UNUSUAL_PATTERN", "INVESTIGATION_REQUIRED", "INFORMATIONAL"].map((item) => (
              <option key={item} value={item}>
                {humanize(item)}
              </option>
            ))}
          </select>
          <input
            className="sv-control"
            placeholder="Detector"
            value={detector}
            onChange={(event) => setDetector(event.target.value)}
            aria-label="Detector"
          />
          <select className="sv-control" value={severity} onChange={(event) => setSeverity(event.target.value)} aria-label="Severity">
            <option value="">All severities</option>
            {["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select className="sv-control" value={investigation} onChange={(event) => setInvestigation(event.target.value)} aria-label="Investigation">
            <option value="">All investigations</option>
            {["OPEN", "IN_REVIEW", "REQUIRES_REENUMERATION", "ESCALATED", "RESOLVED_VALID", "RESOLVED_INVALID"].map((item) => (
              <option key={item} value={item}>
                {humanize(item)}
              </option>
            ))}
          </select>
          <button type="button" className="sv-btn-outline" onClick={() => setMoreFilters((value) => !value)}>
            {moreFilters ? "Fewer filters" : "More filters"}
          </button>
          {filtersActive ? (
            <button type="button" className="sv-btn-outline" onClick={clearFilters}>
              Clear filters
            </button>
          ) : null}
        </div>
        {moreFilters ? (
          <div className="grid gap-2 md:grid-cols-4">
            <input
              className="sv-control"
              placeholder="Min risk"
              value={minRisk}
              onChange={(event) => setMinRisk(event.target.value)}
              aria-label="Minimum risk"
            />
            <select className="sv-control" value={agreement} onChange={(event) => setAgreement(event.target.value)} aria-label="Agreement">
              <option value="">All agreement</option>
              {["strong", "mixed", "single_source", "insufficient"].map((item) => (
                <option key={item} value={item}>
                  {AGREEMENT_LABELS[item]}
                </option>
              ))}
            </select>
            <select className="sv-control" value={source} onChange={(event) => setSource(event.target.value)} aria-label="Evidence source">
              <option value="">All sources</option>
              {["rules", "statistics", "ml"].map((item) => (
                <option key={item} value={item}>
                  {sourceLabel(item)}
                </option>
              ))}
            </select>
            <select className="sv-control" value={aiStatus} onChange={(event) => setAiStatus(event.target.value)} aria-label="AI status">
              <option value="">All AI statuses</option>
              {["available", "generating", "unavailable", "not_required"].map((item) => (
                <option key={item} value={item}>
                  {aiStatusLabel(item)}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        {filtersActive ? (
          <div className="flex flex-wrap gap-2">
            {scope !== DEFAULT_QUEUE_SCOPE ? <span className="sv-chip-active">Scope: {SCOPE_LABELS[scope] ?? scope}</span> : null}
            {classification ? <span className="sv-chip-active">Classification: {humanize(classification)}</span> : null}
            {detector ? <span className="sv-chip-active">Detector: {detector}</span> : null}
            {severity ? <span className="sv-chip-active">Severity: {severity}</span> : null}
            {q ? <span className="sv-chip-active">Search: {q}</span> : null}
            {investigation ? <span className="sv-chip-active">Investigation: {humanize(investigation)}</span> : null}
            {minRisk ? <span className="sv-chip-active">Min risk: {minRisk}</span> : null}
            {agreement ? <span className="sv-chip-active">Agreement: {AGREEMENT_LABELS[agreement] ?? agreement}</span> : null}
            {source ? <span className="sv-chip-active">Source: {sourceLabel(source)}</span> : null}
            {aiStatus ? <span className="sv-chip-active">AI: {aiStatusLabel(aiStatus)}</span> : null}
          </div>
        ) : null}
      </div>

      {query.isPending ? (
        <div className="sv-card overflow-hidden p-4" role="status" aria-live="polite">
          <p className="sr-only">Loading review queue…</p>
          <div className="space-y-2">
            {Array.from({ length: 8 }, (_, index) => (
              <div key={index} className="sv-skeleton h-10 w-full" />
            ))}
          </div>
        </div>
      ) : null}

      {query.isSuccess && query.data?.available ? (
        <>
          <div className="sv-card overflow-x-auto">
            <table className="sv-table w-max !min-w-[1680px]">
              <colgroup>
                {table.getAllLeafColumns().map((column) => {
                  const { width } = queueMeta(column);
                  return <col key={column.id} style={{ width: `${width}px`, minWidth: `${width}px` }} />;
                })}
              </colgroup>
              <thead>
                {table.getHeaderGroups().map((group) => (
                  <tr key={group.id}>
                    {group.headers.map((header) => {
                      const meta = queueMeta(header.column);
                      return (
                        <th
                          key={header.id}
                          style={{ width: `${meta.width}px`, minWidth: `${meta.width}px` }}
                          className={
                            meta.wrapHeader
                              ? "box-border whitespace-normal break-words leading-tight"
                              : "box-border whitespace-nowrap"
                          }
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                        </th>
                      );
                    })}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.length === 0 ? (
                  <tr>
                    <td className="px-3 py-6 text-inst-text-secondary" colSpan={columns.length}>
                      {filtersActive
                        ? "No records match the current filters."
                        : "No records require review. All records currently meet the configured review criteria."}
                    </td>
                  </tr>
                ) : (
                  table.getRowModel().rows.map((row) => (
                    <tr key={row.id}>
                      {row.getVisibleCells().map((cell) => {
                        const meta = queueMeta(cell.column);
                        return (
                          <td
                            key={cell.id}
                            style={{ width: `${meta.width}px`, minWidth: `${meta.width}px` }}
                            className="box-border overflow-hidden text-ellipsis whitespace-nowrap"
                          >
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        );
                      })}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-inst-text-secondary">
            <span>
              {query.data?.total ?? 0} records · page {query.data?.page ?? page}
            </span>
            <div className="flex gap-2">
              <button className="sv-btn-outline" disabled={page <= 1} onClick={() => setPage((n) => n - 1)}>
                Previous
              </button>
              <button
                className="sv-btn-outline"
                disabled={(query.data?.page ?? 1) * (query.data?.page_size ?? 25) >= (query.data?.total ?? 0)}
                onClick={() => setPage((n) => n + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
