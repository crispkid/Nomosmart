"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type ReportChartRow = {
  label: string;
  imports: number;
  approvals: number;
  validation: number;
};

export function ReportChart({ data = [] }: { data?: ReportChartRow[] }) {
  return (
    <div className="chart-frame">
      <ResponsiveContainer height={260} width="100%">
        <BarChart data={data}>
          <CartesianGrid stroke="#E6EBEF" vertical={false} />
          <XAxis dataKey="label" stroke="#5F6B72" />
          <YAxis stroke="#5F6B72" />
          <Tooltip />
          <Bar dataKey="imports" fill="#5FAE88" radius={[4, 4, 0, 0]} />
          <Bar dataKey="approvals" fill="#BFDCCE" radius={[4, 4, 0, 0]} />
          <Bar dataKey="validation" fill="#D8C77A" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
