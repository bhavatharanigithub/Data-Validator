import Link from "next/link";
import {
  Brain,
  Cpu,
  Database,
  FileSpreadsheet,
  GitMerge,
  Layers,
  MessageSquare,
  Scale,
  Table2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { OrchestratorStage } from "@/lib/api/types";
import { StageBadge } from "./status";

const LABELS: Record<string, string> = {
  INGESTION: "Ingestion",
  PARQUET: "Parquet",
  SIRL: "SIRL",
  RULES: "Rules",
  STATISTICS: "Statistics",
  INTELLIGENCE: "Intelligence",
  ML: "ML",
  FUSION: "Fusion / Risk",
  EXPLANATION: "Explanation",
};

const ICONS: Record<string, LucideIcon> = {
  INGESTION: FileSpreadsheet,
  PARQUET: Table2,
  SIRL: Database,
  RULES: Scale,
  STATISTICS: Layers,
  INTELLIGENCE: Brain,
  ML: Cpu,
  FUSION: GitMerge,
  EXPLANATION: MessageSquare,
};

const HREF: Record<string, (batchId: string) => string> = {
  FUSION: () => `/dashboard/anomalies`,
  EXPLANATION: () => `/dashboard/anomalies`,
  RULES: () => `/dashboard/anomalies`,
  STATISTICS: () => `/dashboard/anomalies`,
  INTELLIGENCE: () => `/dashboard/anomalies`,
  ML: () => `/dashboard/anomalies`,
  SIRL: () => `/dashboard`,
};

export function OrchestratorPipeline({
  batchId,
  stages,
}: {
  batchId: string;
  stages: OrchestratorStage[] | null | undefined;
}) {
  const list = Array.isArray(stages) ? stages.filter((stage) => stage && stage.stage) : [];
  return (
    <ol className="sv-pipeline">
      {list.map((stage, index) => {
        const href = stage.status === "COMPLETED" ? HREF[stage.stage]?.(batchId) : undefined;
        const base = LABELS[stage.stage] ?? stage.stage;
        const label =
          stage.stage === "EXPLANATION" && stage.status === "UNAVAILABLE"
            ? "AI Explanation unavailable"
            : stage.status === "SKIPPED"
              ? `${base} skipped`
              : stage.status === "PROCESSING"
                ? `${base} processing`
                : base;
        const Icon = ICONS[stage.stage] ?? Layers;
        const inner = (
          <div className="sv-card flex h-full w-full flex-col items-center gap-2 px-3 py-4">
            <span className="sv-metric-icon bg-inst-muted text-inst-navy" aria-hidden="true">
              <Icon className="h-4 w-4" />
            </span>
            <p className="text-sm font-semibold text-inst-navy">{label}</p>
            <StageBadge value={stage.status} />
            {stage.error ? <p className="mt-1 text-xs text-inst-critical">{stage.error}</p> : null}
          </div>
        );
        return (
          <li key={stage.stage} className="flex min-w-0 flex-1 items-start">
            <div className="sv-pipeline-stage">
              {href ? (
                <Link href={href} className="block w-full hover:border-inst-blue">
                  {inner}
                </Link>
              ) : (
                inner
              )}
            </div>
            {index < list.length - 1 ? <div className="sv-pipeline-line" aria-hidden="true" /> : null}
          </li>
        );
      })}
    </ol>
  );
}
