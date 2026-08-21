import type { LucideIcon } from "lucide-react";

const TONE: Record<string, string> = {
  info: "bg-[#e8eef5] text-inst-blue",
  success: "bg-[#e7f3ec] text-inst-green",
  warning: "bg-[#f8eedf] text-inst-warning",
  critical: "bg-[#f8e8e6] text-inst-critical",
  neutral: "bg-inst-muted text-inst-navy",
};

export function Kpi({
  label,
  value,
  available,
  hint,
  icon: Icon,
  tone = "neutral",
}: {
  label: string;
  value: string | number | null | undefined;
  available: boolean;
  hint?: string;
  icon?: LucideIcon;
  tone?: keyof typeof TONE;
}) {
  return (
    <div className="sv-card p-4">
      <div className="flex items-start gap-3">
        {Icon ? (
          <span className={`sv-metric-icon ${TONE[tone]}`} aria-hidden="true">
            <Icon className="h-4 w-4" />
          </span>
        ) : null}
        <div className="min-w-0">
          <p className="sv-label">{label}</p>
          <p className="mt-1.5 text-2xl font-semibold tabular-nums text-inst-navy">
            {available ? (value ?? "—") : "—"}
          </p>
          {hint ? <p className="mt-1 text-xs leading-5 text-inst-text-secondary">{hint}</p> : null}
        </div>
      </div>
    </div>
  );
}
