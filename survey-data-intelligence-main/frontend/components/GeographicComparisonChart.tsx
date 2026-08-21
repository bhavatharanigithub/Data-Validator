"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltip, chartAxis, chartGrid } from "@/components/charts/chart-style";

export function GeographicComparisonChart({ items }: { items: { id: string; value: number | null }[] }) {
  return (
    <div className="h-80 w-full" role="img" aria-label="District employment rates">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={items} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
          <CartesianGrid stroke={chartGrid.stroke} vertical={chartGrid.vertical} strokeDasharray="0" />
          <XAxis dataKey="id" tick={chartAxis.tick} axisLine={{ stroke: chartAxis.stroke }} tickLine={false} />
          <YAxis tick={chartAxis.tick} axisLine={{ stroke: chartAxis.stroke }} tickLine={false} width={48} />
          <Tooltip content={<ChartTooltip labelTitle="District" valueTitle="Employment rate" />} />
          <Bar dataKey="value" fill="#1d4e89" maxBarSize={56} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
