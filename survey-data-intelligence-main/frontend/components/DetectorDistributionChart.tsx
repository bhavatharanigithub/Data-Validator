"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltip, chartAxis, chartGrid } from "@/components/charts/chart-style";

export function DetectorDistributionChart({ items }: { items: { detector: string; count: number }[] }) {
  const rotate = items.length > 4;
  return (
    <div className="h-80 w-full" role="img" aria-label="Anomalies by detector">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={items} margin={{ top: 8, right: 8, left: 0, bottom: rotate ? 48 : 8 }}>
          <CartesianGrid stroke={chartGrid.stroke} vertical={chartGrid.vertical} strokeDasharray="0" />
          <XAxis
            dataKey="detector"
            tick={chartAxis.tick}
            axisLine={{ stroke: chartAxis.stroke }}
            tickLine={false}
            interval={0}
            angle={rotate ? -20 : 0}
            textAnchor={rotate ? "end" : "middle"}
            height={rotate ? 70 : 36}
          />
          <YAxis allowDecimals={false} tick={chartAxis.tick} axisLine={{ stroke: chartAxis.stroke }} tickLine={false} width={36} />
          <Tooltip content={<ChartTooltip labelTitle="Detector" valueTitle="Count" />} />
          <Bar dataKey="count" fill="#1d4e89" maxBarSize={56} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
