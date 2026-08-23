"use client";

/*
  Charts.

  Palette validated with the dataviz palette validator against the white chart
  surface: blue (this week) / orange (4-week average) clears the CVD, normal
  vision and contrast checks. Two-series charts always carry a legend, so
  identity never rests on colour alone. Grid and axes stay recessive; values
  live in the tooltip rather than on every mark.
*/

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { number, rupees, rupeesCompact } from "@/lib/format";
import type { HourlyDemandPoint, HourlyPoint, TrendPoint, WeekdayPoint } from "@/types";

const AXIS = {
  stroke: "var(--subtle)",
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const;

function TooltipShell({
  title,
  rows,
}: {
  title: string;
  rows: { label: string; value: string; color?: string }[];
}) {
  return (
    <div className="rounded-xl border border-border bg-surface px-3 py-2 shadow-[var(--shadow-md)]">
      <p className="text-[12px] font-semibold text-foreground">{title}</p>
      <div className="mt-1.5 space-y-1">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center gap-2 text-[12px]">
            {row.color ? (
              <span
                className="size-2 shrink-0 rounded-full"
                style={{ background: row.color }}
                aria-hidden
              />
            ) : null}
            <span className="text-muted">{row.label}</span>
            <span className="tnum ml-auto font-semibold text-foreground">{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------ 30-day revenue trend */

export function RevenueTrendChart({ data }: { data: TrendPoint[] }) {
  // Single series: the card title names it, so no legend box is needed.
  return (
    <div className="h-[180px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <defs>
            <linearGradient id="revenueFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--series-current)" stopOpacity={0.22} />
              <stop offset="100%" stopColor="var(--series-current)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis
            dataKey="label"
            {...AXIS}
            interval="preserveStartEnd"
            minTickGap={28}
          />
          <YAxis {...AXIS} width={54} tickFormatter={(v) => rupeesCompact(Number(v))} />
          <Tooltip
            cursor={{ stroke: "var(--border-strong)", strokeWidth: 1 }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const point = payload[0].payload as TrendPoint;
              return (
                <TooltipShell
                  title={point.label}
                  rows={[
                    {
                      label: "Revenue",
                      value: rupees(point.revenue),
                      color: "var(--series-current)",
                    },
                    { label: "Transactions", value: number(point.transactions) },
                  ]}
                />
              );
            }}
          />
          <Area
            type="monotone"
            dataKey="revenue"
            stroke="var(--series-current)"
            strokeWidth={2}
            fill="url(#revenueFill)"
            activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ------------------------------ hourly: this week vs 4-week baseline */

export function HourlyChart({ data }: { data: HourlyPoint[] }) {
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <LegendSwatch color="var(--series-current)" label="This week" />
        <LegendSwatch color="var(--series-baseline)" label="4-week average" />
      </div>
      <div className="h-[210px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -18 }} barGap={2}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="label" {...AXIS} interval={1} />
            <YAxis {...AXIS} width={40} />
            <Tooltip
              cursor={{ fill: "var(--surface-muted)" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const point = payload[0].payload as HourlyPoint;
                return (
                  <TooltipShell
                    title={`${point.label}: transactions per day`}
                    rows={[
                      {
                        label: "This week",
                        value: point.current.toFixed(1),
                        color: "var(--series-current)",
                      },
                      {
                        label: "4-week average",
                        value: point.baseline.toFixed(1),
                        color: "var(--series-baseline)",
                      },
                      {
                        label: "Change",
                        value: `${point.change_percent > 0 ? "+" : ""}${point.change_percent.toFixed(0)}%`,
                      },
                    ]}
                  />
                );
              }}
            />
            <Bar dataKey="baseline" fill="var(--series-baseline)" radius={[4, 4, 0, 0]} />
            <Bar dataKey="current" fill="var(--series-current)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/* --------------------------- weekday: this week vs its own history */

export function WeekdayChart({ data }: { data: WeekdayPoint[] }) {
  return (
    <div className="h-[200px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="day" {...AXIS} tickFormatter={(d: string) => d.slice(0, 3)} />
          <YAxis {...AXIS} width={54} tickFormatter={(v) => rupeesCompact(Number(v))} />
          <Tooltip
            cursor={{ fill: "var(--surface-muted)" }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const point = payload[0].payload as WeekdayPoint;
              return (
                <TooltipShell
                  title={point.day}
                  rows={[
                    { label: "This week", value: rupees(point.revenue) },
                    {
                      label: `${point.day} average`,
                      value: rupees(point.historical_average),
                    },
                    {
                      label: "Change",
                      value: `${point.change_percent > 0 ? "+" : ""}${point.change_percent.toFixed(0)}%`,
                    },
                  ]}
                />
              );
            }}
          />
          {/*
            One series coloured by state, not by identity: a day is flagged only
            when it falls meaningfully below its own historical average. The
            tooltip carries the number, so colour is never the only signal.
          */}
          <Bar dataKey="revenue" radius={[4, 4, 0, 0]}>
            {data.map((point) => (
              <Cell
                key={point.date}
                fill={
                  point.change_percent <= -20
                    ? "var(--negative)"
                    : point.change_percent <= -8
                      ? "var(--warning)"
                      : "var(--series-current)"
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function LegendSwatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] text-muted">
      <span className="size-2.5 rounded-sm" style={{ background: color }} aria-hidden />
      {label}
    </span>
  );
}

/* ------------------------------------------------------- score ring */

export function ScoreRing({
  score,
  size = 168,
  stroke = 12,
  color,
  children,
}: {
  score: number;
  size?: number;
  stroke?: number;
  color: string;
  children?: React.ReactNode;
}) {
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.max(0, Math.min(100, score)) / 100);

  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg
        width={size}
        height={size}
        className="-rotate-90"
        role="img"
        aria-label={`Business health score ${score} out of 100`}
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--grid)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: "stroke-dashoffset 900ms cubic-bezier(0.22, 1, 0.36, 1)" }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center">{children}</div>
    </div>
  );
}

/* ------------------------------------------- shop-floor demand by hour */

/*
  Requests per hour, split into filled and unfilled.

  Stacked rather than grouped on purpose: the total height is the demand the
  merchant heard, and the red portion is the part of it that walked out. The
  relationship between the two is the whole point, so they share a column.

  Red is reserved for genuine problems everywhere in this product, and an
  unfilled request is exactly that, so it keeps its meaning here.
*/
export function ShopDemandChart({ data }: { data: HourlyDemandPoint[] }) {
  if (!data.length) {
    return (
      <p className="px-4 py-8 text-center text-[13px] text-subtle">
        No shop-floor activity captured yet.
      </p>
    );
  }

  return (
    <div className="h-[190px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="label" {...AXIS} interval="preserveStartEnd" />
          <YAxis {...AXIS} allowDecimals={false} width={38} />
          <Tooltip
            cursor={{ fill: "var(--surface-muted)" }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0].payload as HourlyDemandPoint;
              return (
                <TooltipShell
                  title={String(label)}
                  rows={[
                    {
                      label: "Filled",
                      value: number(row.requests - row.unfulfilled),
                      color: "var(--series-current)",
                    },
                    {
                      label: "Unfilled",
                      value: number(row.unfulfilled),
                      color: "var(--negative)",
                    },
                    { label: "Total asked for", value: number(row.requests) },
                  ]}
                />
              );
            }}
          />
          <Legend
            verticalAlign="top"
            align="right"
            height={26}
            iconType="circle"
            iconSize={8}
            formatter={(value) => (
              <span style={{ color: "var(--muted)", fontSize: 12 }}>{value}</span>
            )}
          />
          <Bar
            dataKey="filled"
            name="Filled"
            stackId="demand"
            fill="var(--series-current)"
            radius={[0, 0, 0, 0]}
          />
          <Bar
            dataKey="unfulfilled"
            name="Unfilled"
            stackId="demand"
            fill="var(--negative)"
            radius={[4, 4, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Recharts stacks raw values, so the filled portion is derived here. */
export function withFilled(data: HourlyDemandPoint[]) {
  return data.map((d) => ({ ...d, filled: d.requests - d.unfulfilled }));
}

/* ------------------------------------------------- component meter */

export function ScoreMeter({ score, color }: { score: number; color: string }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-grid">
      <div
        className="h-full rounded-full"
        style={{
          width: `${Math.max(0, Math.min(100, score))}%`,
          background: color,
          transition: "width 700ms cubic-bezier(0.22, 1, 0.36, 1)",
        }}
      />
    </div>
  );
}
