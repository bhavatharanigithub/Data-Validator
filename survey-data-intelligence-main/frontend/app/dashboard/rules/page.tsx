"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers, ShieldCheck, ShieldOff, Tags } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Kpi } from "@/components/kpi";
import { EmptyState, ErrorState, SeverityBadge } from "@/components/status";
import { ApiError, listDetectors, patchDetector } from "@/lib/api";
import type { DetectorConfig } from "@/lib/api/types";
import { readSession } from "@/lib/auth";

const GROUPS: Record<string, string> = {
  RULE: "Validation rules",
  RELATIONSHIP: "Relationship detectors",
  STATISTICAL: "Statistical detectors",
  ENUMERATOR: "Fieldwork detectors",
  PATTERN: "Fieldwork detectors",
  TEMPORAL: "Temporal detectors",
  GEOGRAPHIC: "Geographic detectors",
  HISTORICAL: "Temporal detectors",
  ML: "Statistical detectors",
};

const GROUP_ORDER = [
  "Fieldwork detectors",
  "Geographic detectors",
  "Temporal detectors",
  "Relationship detectors",
  "Statistical detectors",
  "Validation rules",
];

function groupLabel(category: string): string {
  return GROUPS[category] || category;
}

function formatThresholdValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function thresholdEntries(config: Record<string, unknown> | null | undefined): [string, unknown][] {
  if (!config) return [];
  return Object.entries(config);
}

function detectorErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 403) {
    return "Detector configuration can only be changed by an administrator.";
  }
  return "Detector configuration could not be updated.";
}

function DetectorToggle({
  detector,
  pending,
  onToggle,
}: {
  detector: DetectorConfig;
  pending: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      className="sv-switch"
      aria-checked={detector.enabled}
      aria-busy={pending}
      disabled={pending}
      aria-label={`${detector.enabled ? "Disable" : "Enable"} ${detector.name} detector`}
      onClick={() => onToggle(!detector.enabled)}
    >
      <span className="sv-switch-knob" />
      <span className="sr-only">{detector.enabled ? "Enabled" : "Disabled"}</span>
    </button>
  );
}

function DetectorItem({
  detector,
  canToggle,
  pending,
  onToggle,
}: {
  detector: DetectorConfig;
  canToggle: boolean;
  pending: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  const entries = thresholdEntries(detector.thresholds_json);
  return (
    <article className="px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-inst-navy">{detector.name}</h3>
          {detector.description ? (
            <p className="mt-1 max-w-3xl text-sm leading-6 text-inst-text-secondary">{detector.description}</p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {canToggle ? (
            <>
              <DetectorToggle detector={detector} pending={pending} onToggle={onToggle} />
              <span className="text-xs font-semibold uppercase tracking-wide text-inst-navy">
                {pending ? "Saving" : detector.enabled ? "Enabled" : "Disabled"}
              </span>
            </>
          ) : (
            <span
              className={`inline-flex items-center border px-2 py-0.5 text-[11px] font-semibold ${
                detector.enabled
                  ? "border-emerald-200 bg-emerald-50 text-inst-green"
                  : "border-inst-border bg-inst-muted text-inst-text-secondary"
              }`}
            >
              {detector.enabled ? "Enabled" : "Disabled"}
            </span>
          )}
        </div>
      </div>
      <dl className="mt-3 flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <div>
          <dt className="sv-label">Severity</dt>
          <dd className="mt-1">
            <SeverityBadge value={detector.severity} />
          </dd>
        </div>
        {entries.map(([key, value]) => (
          <div key={key}>
            <dt className="sv-label">{key}</dt>
            <dd className="mt-1 font-medium tabular-nums text-inst-navy">{formatThresholdValue(value)}</dd>
          </div>
        ))}
      </dl>
      {detector.thresholds_json ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-semibold text-inst-blue">View configuration</summary>
          <pre className="mt-2 overflow-x-auto rounded border border-inst-border bg-inst-muted p-3 text-xs text-inst-text">
            {JSON.stringify(detector.thresholds_json, null, 2)}
          </pre>
        </details>
      ) : null}
    </article>
  );
}

export default function RulesPage() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["detectors"], queryFn: listDetectors, retry: false });
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "enabled" | "disabled">("all");
  const [updateError, setUpdateError] = useState<string | null>(null);
  const [canToggle, setCanToggle] = useState(false);

  useEffect(() => {
    setCanToggle(readSession()?.role === "SURVEY_ADMIN");
  }, []);

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => patchDetector(id, { enabled }),
    onMutate: () => setUpdateError(null),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["detectors"] }),
    onError: (error) => setUpdateError(detectorErrorMessage(error)),
  });

  const items = query.data ?? [];
  const categories = useMemo(() => {
    const labels = new Set(items.map((item) => groupLabel(item.category)));
    return [...labels].sort((a, b) => {
      const ai = GROUP_ORDER.indexOf(a);
      const bi = GROUP_ORDER.indexOf(b);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi) || a.localeCompare(b);
    });
  }, [items]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter((item) => {
      if (statusFilter === "enabled" && !item.enabled) return false;
      if (statusFilter === "disabled" && item.enabled) return false;
      const label = groupLabel(item.category);
      if (categoryFilter && label !== categoryFilter) return false;
      if (!q) return true;
      return (
        item.name.toLowerCase().includes(q) ||
        (item.description ?? "").toLowerCase().includes(q) ||
        item.category.toLowerCase().includes(q) ||
        label.toLowerCase().includes(q)
      );
    });
  }, [items, search, categoryFilter, statusFilter]);

  const grouped = useMemo(() => {
    const next: Record<string, DetectorConfig[]> = {};
    for (const item of filtered) {
      const label = groupLabel(item.category);
      next[label] = next[label] || [];
      next[label].push(item);
    }
    return categories.filter((label) => next[label]?.length).map((label) => [label, next[label]] as const);
  }, [filtered, categories]);

  const total = items.length;
  const enabledCount = items.filter((item) => item.enabled).length;
  const disabledCount = total - enabledCount;
  const categoryCount = new Set(items.map((item) => groupLabel(item.category))).size;
  const filtering = Boolean(search.trim() || categoryFilter || statusFilter !== "all");

  return (
    <div className="space-y-6">
      <div>
        <p className="sv-label">Detectors</p>
        <h1 className="mt-1 text-2xl font-semibold text-inst-navy">Validation and intelligence detectors</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-inst-text-secondary">
          Configure the quality detectors used to identify unusual patterns and validation signals in survey data.
        </p>
      </div>

      <div className="rounded border border-inst-border bg-inst-muted px-4 py-3 text-sm leading-6 text-inst-text">
        Enable or disable detectors. Thresholds remain JSON-based. Unusual detections are investigation candidates, not
        automatic proof of error.
      </div>

      {query.isError ? (
        <ErrorState message="Unable to load detector configuration." onRetry={() => query.refetch()} />
      ) : null}

      {query.isPending ? (
        <div className="space-y-3" role="status" aria-live="polite">
          <p className="sr-only">Loading detectors…</p>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }, (_, index) => (
              <div key={index} className="sv-skeleton h-24 w-full" />
            ))}
          </div>
          <div className="sv-card space-y-2 p-4">
            {Array.from({ length: 6 }, (_, index) => (
              <div key={index} className="sv-skeleton h-16 w-full" />
            ))}
          </div>
        </div>
      ) : null}

      {query.isSuccess && !items.length ? (
        <EmptyState title="No detectors" detail="Start the backend so the detector registry can seed." />
      ) : null}

      {query.isSuccess && items.length ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi label="Total detectors" value={total} available icon={Layers} tone="info" />
            <Kpi label="Enabled" value={enabledCount} available icon={ShieldCheck} tone="success" />
            <Kpi label="Disabled" value={disabledCount} available icon={ShieldOff} tone="neutral" />
            <Kpi label="Categories" value={categoryCount} available icon={Tags} tone="info" />
          </div>

          <div className="sv-card p-4">
            <div className="grid gap-2 md:grid-cols-4">
              <input
                className="sv-control md:col-span-2"
                placeholder="Search detectors…"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                aria-label="Search detectors"
              />
              <select
                className="sv-control"
                value={categoryFilter}
                onChange={(event) => setCategoryFilter(event.target.value)}
                aria-label="Category"
              >
                <option value="">All categories</option>
                {categories.map((label) => (
                  <option key={label} value={label}>
                    {label}
                  </option>
                ))}
              </select>
              <select
                className="sv-control"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as "all" | "enabled" | "disabled")}
                aria-label="Status"
              >
                <option value="all">All</option>
                <option value="enabled">Enabled</option>
                <option value="disabled">Disabled</option>
              </select>
            </div>
            {filtering ? (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className="text-sm text-inst-text-secondary">{filtered.length} detectors</span>
                <button
                  type="button"
                  className="sv-btn-outline px-2 py-1 text-xs"
                  onClick={() => {
                    setSearch("");
                    setCategoryFilter("");
                    setStatusFilter("all");
                  }}
                >
                  Clear
                </button>
              </div>
            ) : null}
          </div>

          {updateError ? <div className="sv-alert-critical">{updateError}</div> : null}

          {filtered.length ? (
            grouped.map(([label, rows]) => (
              <section key={label} className="sv-card overflow-hidden">
                <div className="border-b border-inst-border bg-inst-muted px-4 py-3">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-inst-navy">{label}</h2>
                  <p className="mt-1 text-xs text-inst-text-secondary">
                    {rows.length === 1 ? "1 detector" : `${rows.length} detectors`}
                  </p>
                </div>
                <div className="divide-y divide-[var(--sv-border)]">
                  {rows.map((row) => (
                    <DetectorItem
                      key={row.detector_id}
                      detector={row}
                      canToggle={canToggle}
                      pending={toggle.isPending && toggle.variables?.id === row.detector_id}
                      onToggle={(enabled) => toggle.mutate({ id: row.detector_id, enabled })}
                    />
                  ))}
                </div>
              </section>
            ))
          ) : (
            <EmptyState title="No matching detectors" detail="No detectors in this configuration match the current search or filters." />
          )}
        </>
      ) : null}
    </div>
  );
}
