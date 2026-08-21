"use client";

import { DistrictCharts } from "@/components/group-tables";
import { ViewScopeBanner, ViewScopeSelect } from "@/components/view-scope-select";
import { useBatchSelection } from "@/components/shell";
import { useDataView } from "@/lib/data-view";

export default function DistrictsPage() {
  const [view, setView] = useDataView();
  const { batchId } = useBatchSelection();
  return (
    <div className="space-y-6">
      <div>
        <p className="sv-label">Districts</p>
        <h1 className="mt-1 text-2xl font-semibold text-inst-navy">Comparison</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-inst-text-secondary">
          Compare survey coverage, quality signals, and risk across districts.
        </p>
        <div className="mt-4">
          <ViewScopeSelect view={view} onChange={setView} />
        </div>
        <ViewScopeBanner view={view} batchId={batchId} />
      </div>
      <DistrictCharts view={view} />
    </div>
  );
}
