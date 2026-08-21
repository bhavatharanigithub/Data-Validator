"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltip, chartAxis, chartGrid } from "@/components/charts/chart-style";

export function TemporalTrendChart({
  items,
}: {
  items: { period: string; observed: number | null; baseline: number | null; threshold?: number | null }[];
}) {
  return (
    <div className="h-80 w-full" role="img" aria-label="Temporal trends">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={items} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
          <CartesianGrid stroke={chartGrid.stroke} vertical={chartGrid.vertical} strokeDasharray="0" />
          <XAxis dataKey="period" tick={chartAxis.tick} axisLine={{ stroke: chartAxis.stroke }} tickLine={false} />
          <YAxis tick={chartAxis.tick} axisLine={{ stroke: chartAxis.stroke }} tickLine={false} width={48} />
          <Tooltip content={<ChartTooltip labelTitle="Period" />} />
          <Line type="monotone" dataKey="observed" stroke="#1d4e89" name="actual" dot={false} strokeWidth={2} />
          <Line type="monotone" dataKey="baseline" stroke="#5c6775" name="baseline" dot={false} strokeWidth={1.5} />
          <Line type="monotone" dataKey="threshold" stroke="#b45309" name="threshold" dot={false} strokeWidth={1.5} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
