"use client";

type TooltipItem = {
  dataKey?: string | number;
  name?: string;
  value?: number | string | null;
};

export function ChartTooltip({
  active,
  payload,
  label,
  labelTitle = "Label",
  valueTitle,
}: {
  active?: boolean;
  payload?: TooltipItem[];
  label?: string | number;
  labelTitle?: string;
  valueTitle?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-inst-border bg-inst-surface px-3 py-2 text-xs shadow-inst">
      <p className="sv-label">{labelTitle}</p>
      <p className="mt-0.5 font-semibold text-inst-navy">{String(label ?? "—")}</p>
      {payload.map((entry) => (
        <div key={String(entry.dataKey ?? entry.name)} className="mt-2">
          <p className="sv-label">{valueTitle || entry.name || "Value"}</p>
          <p className="font-semibold tabular-nums text-inst-navy">{entry.value ?? "—"}</p>
        </div>
      ))}
    </div>
  );
}

export const chartAxis = {
  stroke: "#d5dbe3",
  tick: { fill: "#5c6775", fontSize: 12 },
};

export const chartGrid = {
  stroke: "#e8edf2",
  vertical: false,
};
