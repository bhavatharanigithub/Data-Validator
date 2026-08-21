"use client";

import { EnumeratorTable } from "@/components/group-tables";
import { ViewScopeBanner, ViewScopeSelect } from "@/components/view-scope-select";
import { useBatchSelection } from "@/components/shell";
import { useDataView } from "@/lib/data-view";

export default function EnumeratorsPage() {
  const [view, setView] = useDataView();
  const { batchId } = useBatchSelection();
  return (
    <div className="space-y-6">
      <div>
        <p className="sv-label">Enumerators</p>
        <h1 className="mt-1 text-2xl font-semibold text-inst-navy">Workload and risk</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-inst-text-secondary">
          Monitor enumerator workload, anomaly signals, and data-quality risk across districts.
        </p>
        <div className="mt-4">
          <ViewScopeSelect view={view} onChange={setView} />
        </div>
        <ViewScopeBanner view={view} batchId={batchId} />
      </div>
      <EnumeratorTable view={view} />
    </div>
  );
}
