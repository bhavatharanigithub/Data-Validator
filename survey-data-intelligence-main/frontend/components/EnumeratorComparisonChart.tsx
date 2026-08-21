"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltip, chartAxis, chartGrid } from "@/components/charts/chart-style";

export function EnumeratorComparisonChart({
  items,
}: {
  items: { enumerator_id: string; employment_rate?: number | null; highlight?: boolean }[];
}) {
  return (
    <div className="h-80 w-full" role="img" aria-label="Enumerator comparison">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={items} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
          <CartesianGrid stroke={chartGrid.stroke} vertical={chartGrid.vertical} strokeDasharray="0" />
          <XAxis dataKey="enumerator_id" tick={chartAxis.tick} axisLine={{ stroke: chartAxis.stroke }} tickLine={false} />
          <YAxis tick={chartAxis.tick} axisLine={{ stroke: chartAxis.stroke }} tickLine={false} width={48} />
          <Tooltip content={<ChartTooltip labelTitle="Enumerator" valueTitle="Employment rate" />} />
          <Bar dataKey="employment_rate" maxBarSize={56}>
            {items.map((item) => (
              <Cell key={item.enumerator_id} fill={item.highlight ? "#c45c26" : "#1d4e89"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
