import type { PipelineStage } from "@/lib/api/types";
import { StageBadge } from "./status";

export function Pipeline({ stages }: { stages: PipelineStage[] }) {
  return (
    <ol className="grid gap-2 md:grid-cols-2 xl:grid-cols-5">
      {stages.map((stage, index) => (
        <li key={stage.id} className="sv-card p-3">
          <p className="sv-label">
            {index + 1}. {stage.label}
          </p>
          <div className="mt-2 flex items-center justify-between">
            <StageBadge value={stage.status} />
            {stage.record_count != null ? (
              <span className="text-xs tabular-nums text-slate-400">{stage.record_count} rec.</span>
            ) : null}
          </div>
          {stage.timestamp ? (
            <p className="mt-2 text-[11px] text-slate-500">{new Date(stage.timestamp).toLocaleString()}</p>
          ) : (
            <p className="mt-2 text-[11px] text-slate-600">No timestamp</p>
          )}
          {stage.detail ? <p className="mt-1 truncate text-[11px] text-slate-500">{stage.detail}</p> : null}
        </li>
      ))}
    </ol>
  );
}
