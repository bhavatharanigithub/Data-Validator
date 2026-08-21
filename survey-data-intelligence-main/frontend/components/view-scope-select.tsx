"use client";

import type { DataView } from "@/lib/data-view";
import { DATA_VIEW_CUMULATIVE, DATA_VIEW_CURRENT } from "@/lib/data-view";

export function ViewScopeSelect({
  view,
  onChange,
}: {
  view: DataView;
  onChange: (next: DataView) => void;
}) {
  return (
    <label className="block max-w-xs">
      <span className="sv-label">View</span>
      <select
        className="sv-control mt-1 w-full"
        value={view}
        aria-label="View"
        onChange={(event) => onChange(event.target.value as DataView)}
      >
        <option value={DATA_VIEW_CURRENT}>Current Batch</option>
        <option value={DATA_VIEW_CUMULATIVE}>Cumulative Records</option>
      </select>
    </label>
  );
}

export function ViewScopeBanner({ view, batchId }: { view: DataView; batchId?: string | null }) {
  if (view === DATA_VIEW_CUMULATIVE) {
    return (
      <p className="mt-3 text-sm text-inst-text">
        Scope <span className="font-semibold text-inst-navy">Cumulative — All Batches</span>
        {batchId ? (
          <span className="text-inst-text-secondary">
            {" "}
            (header batch {batchId} does not limit this view)
          </span>
        ) : null}
      </p>
    );
  }
  if (!batchId) return null;
  return (
    <p className="mt-3 text-sm text-inst-text">
      Batch <span className="font-mono text-xs font-semibold text-inst-navy">{batchId}</span>
    </p>
  );
}
