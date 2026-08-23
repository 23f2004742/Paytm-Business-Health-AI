"use client";

/*
  Munim AI: the shop's own books, on the home screen.

  The order is the argument, and it is deliberately not the old one:

    1. talk to it      one voice command, before anything else
    2. the money       in, stuck, out: the three columns a munim keeps
    3. the verdict     one line, plus the money that never arrived
    4. health          how the shop is doing, scored
    5. both sources    what the ledger saw, and what it could not
    6. Munim's read    the two joined
    7. act             the thing to do about it

  A payments dashboard has to open with a chart because a chart is all it has.
  This opens with the microphone, because the point of the product is that the
  merchant can just say it, and two of the three money columns below exist only
  because they did.
*/

import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  Mic,
  Package,
  Receipt,
  Sparkles,
} from "lucide-react";
import Link from "next/link";

import { RevenueTrendChart, ScoreRing } from "@/components/charts";
import { MoneyColumns, MoneyVerdict } from "@/components/money";
import { useAppData } from "@/components/providers";
import { VoiceCommand } from "@/components/voice-command";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  DeltaPill,
  ErrorState,
  Skeleton,
  SkeletonCard,
  Stagger,
  StaggerItem,
} from "@/components/ui";
import { greeting, number, rupees, scoreColor, toneFor } from "@/lib/format";

export default function OverviewPage() {
  const { dashboard, loading, error, reload } = useAppData();

  if (error) {
    return (
      <div className="px-4 pt-6 md:px-0">
        <ErrorState
          title="Can't load your dukaan"
          message={error.message}
          hint={error.hint}
          onRetry={() => void reload()}
        />
      </div>
    );
  }

  if (loading || !dashboard) return <OverviewSkeleton />;

  const {
    merchant,
    health,
    money,
    revenue_trend,
    what_changed,
    shop_floor,
    ai_summary,
    unified_insights,
    active_campaign,
    open_restock_alerts,
  } = dashboard;

  const color = scoreColor(health.overall_score);
  const lead = unified_insights[0];
  const shortage = shop_floor.out_of_stock[0] ?? null;

  return (
    <Stagger className="space-y-4 px-4 pt-6 md:px-0 md:pt-0">
      {/* Greeting */}
      <StaggerItem>
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[14px] text-muted">
              {greeting()}, {merchant.owner_name} 👋
            </p>
            <h1 className="text-[22px] font-bold tracking-tight md:text-[26px]">
              {merchant.name}
            </h1>
            <p className="mt-0.5 text-[12px] text-subtle">
              {merchant.category} · {merchant.location}
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1.5">
            {active_campaign ? (
              <Badge tone="positive">
                <BadgeCheck className="size-3.5" aria-hidden />
                Campaign live
              </Badge>
            ) : null}
            {open_restock_alerts.length ? (
              <Badge tone="warning">
                <Package className="size-3.5" aria-hidden />
                {open_restock_alerts.length} restock
              </Badge>
            ) : null}
          </div>
        </div>
      </StaggerItem>

      {/* 1. The promise: say it, and the books keep themselves. */}
      <StaggerItem>
        <VoiceCommand onAction={() => void reload()} />
      </StaggerItem>

      {/* 2 + 3. The three columns, then the one-line verdict. */}
      {money ? (
        <>
          <StaggerItem>
            <MoneyColumns money={money} />
          </StaggerItem>
          <StaggerItem>
            <MoneyVerdict money={money} />
          </StaggerItem>
        </>
      ) : null}

      {/* 4. Health */}
      <StaggerItem>
        <Card className="overflow-hidden">
          <div className="flex flex-col items-center gap-5 p-6 sm:flex-row sm:items-center sm:gap-7">
            <ScoreRing score={health.overall_score} color={color}>
              <div className="text-center">
                <motion.p
                  className="tnum text-[40px] font-bold leading-none tracking-tight"
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: 0.45, delay: 0.15 }}
                  style={{ color }}
                >
                  {health.overall_score}
                </motion.p>
                <p className="mt-1 text-[12px] font-medium text-subtle">out of 100</p>
              </div>
            </ScoreRing>

            <div className="min-w-0 flex-1 text-center sm:text-left">
              <p className="text-[11px] font-semibold uppercase tracking-widest text-subtle">
                Dukaan health
              </p>
              <div className="mt-2 flex flex-wrap items-center justify-center gap-2 sm:justify-start">
                <Badge tone={health.overall_score >= 80 ? "positive" : "brand"}>
                  {health.status}
                </Badge>
                {health.needs_attention ? (
                  <Badge tone="warning">Needs attention</Badge>
                ) : null}
                <DeltaPill
                  value={health.change}
                  tone={toneFor(health.change)}
                  suffix=" pts this week"
                />
              </div>
              <p className="mt-3 text-[14px] leading-relaxed text-muted">
                Was {health.previous_score} last week, now {health.overall_score}.
              </p>

              <Link href="/why" className="mt-4 inline-block">
                <Button size="md">
                  Why did my score {health.change < 0 ? "drop" : "change"}?
                  <ArrowRight className="size-4" aria-hidden />
                </Button>
              </Link>
            </div>
          </div>
        </Card>
      </StaggerItem>

      {/* 5. The two intelligence sources, side by side */}
      <StaggerItem>
        <div className="grid gap-3 lg:grid-cols-2">
          <Card>
            <CardHeader
              title="What changed"
              subtitle="From your payment data"
              icon={<Receipt className="size-4" aria-hidden />}
            />
            <ul className="divide-y divide-border px-5 pb-3 pt-2">
              {what_changed.map((insight) => (
                <li key={insight.id} className="flex items-start gap-3 py-3">
                  <span
                    className="mt-1.5 size-2 shrink-0 rounded-full"
                    style={{
                      background:
                        insight.kind === "negative"
                          ? "var(--negative)"
                          : insight.kind === "positive"
                            ? "var(--positive)"
                            : "var(--warning)",
                    }}
                    aria-hidden
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-[14px] font-semibold">{insight.title}</p>
                      <DeltaPill
                        value={insight.change_percent}
                        tone={insight.kind === "positive" ? "positive" : "negative"}
                      />
                    </div>
                    <p className="mt-1 text-[13px] leading-relaxed text-muted">
                      {insight.description}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </Card>

          <Card>
            <CardHeader
              title="What the shop floor said"
              subtitle="Asked for out loud, never banked"
              icon={<Mic className="size-4" aria-hidden />}
              action={
                shop_floor.demo_mode ? (
                  <Badge tone="neutral" className="shrink-0">
                    Demo data
                  </Badge>
                ) : null
              }
            />

            <div className="grid grid-cols-2 gap-3 px-5 pt-4">
              <div className="rounded-xl bg-surface-muted p-3">
                <p className="text-[12px] text-subtle">Customer requests</p>
                <p className="tnum mt-1 text-[22px] font-bold leading-none">
                  {number(shop_floor.total_requests)}
                </p>
                <p className="mt-1 text-[11px] text-subtle">
                  across {shop_floor.conversations_captured} conversations
                </p>
              </div>
              <div className="rounded-xl bg-surface-muted p-3">
                <p className="text-[12px] text-subtle">Went unfilled</p>
                <p
                  className="tnum mt-1 text-[22px] font-bold leading-none"
                  style={{
                    color: shop_floor.unfulfilled_requests
                      ? "var(--negative)"
                      : "var(--positive)",
                  }}
                >
                  {number(shop_floor.unfulfilled_requests)}
                </p>
                <p className="mt-1 text-[11px] text-subtle">potential missed sales</p>
              </div>
            </div>

            {shop_floor.top_demand ? (
              <div className="px-5 pt-3">
                <p className="text-[12px] font-semibold text-subtle">🔥 Highest demand</p>
                <div className="mt-1.5 flex items-center gap-2">
                  <p className="text-[15px] font-bold">{shop_floor.top_demand.product}</p>
                  <span className="tnum text-[13px] text-muted">
                    {shop_floor.top_demand.requests} requests
                  </span>
                </div>
              </div>
            ) : null}

            {shortage ? (
              <div className="mx-5 mb-5 mt-3 rounded-xl border border-negative/25 bg-negative-soft p-3.5">
                <div className="flex items-start gap-2.5">
                  <AlertTriangle
                    className="mt-0.5 size-4 shrink-0 text-negative"
                    strokeWidth={2.3}
                    aria-hidden
                  />
                  <div className="min-w-0">
                    <p className="text-[13px] font-bold text-negative">
                      Out of stock: {shortage.product}
                    </p>
                    <p className="mt-1 text-[12px] leading-relaxed text-foreground">
                      Asked for {shortage.requests} times this week and unavailable
                      every time. None of this reaches your payment data.
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="px-5 pb-5 pt-3">
                <p className="text-[13px] text-muted">
                  Nothing reported out of stock this week.
                </p>
              </div>
            )}
          </Card>
        </div>
      </StaggerItem>

      {/* 6. The joined narrative */}
      <StaggerItem>
        <Card className="overflow-hidden border-brand/25">
          <div className="flex items-center gap-2.5 border-b border-border bg-brand-soft/60 px-5 py-3">
            <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-brand text-white">
              <Sparkles className="size-4" strokeWidth={2.2} aria-hidden />
            </span>
            <p className="text-[13px] font-bold text-brand-strong">Munim&rsquo;s read</p>
            {lead ? (
              <span className="ml-auto text-[11px] font-medium text-muted">
                confidence {Math.round(lead.confidence * 100)}%
              </span>
            ) : null}
          </div>

          <div className="p-5">
            <p className="text-[15px] leading-relaxed text-foreground">{ai_summary}</p>

            {lead?.kind === "unified" ? (
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                <SignalChip
                  label="Payment signal"
                  value={`${lead.transaction_signal?.metric} ${lead.transaction_signal?.change_percent}%`}
                  tone="negative"
                />
                <SignalChip
                  label="Shop-floor signal"
                  value={`${lead.shop_signal?.product}: ${lead.shop_signal?.requests} requests, out of stock`}
                  tone="warning"
                />
              </div>
            ) : null}

            <p className="mt-3 text-[11px] leading-relaxed text-subtle">
              {lead?.correlation_note ??
                "Signals are measured independently; no causal link is claimed."}
            </p>

            <div className="mt-4 flex flex-wrap gap-2">
              <Link href="/why">
                <Button size="sm">
                  Root cause analysis
                  <ArrowRight className="size-4" aria-hidden />
                </Button>
              </Link>
              <Link href="/insights">
                <Button size="sm" variant="secondary">
                  All insights
                </Button>
              </Link>
            </div>
          </div>
        </Card>
      </StaggerItem>

      {/* Trend */}
      <StaggerItem>
        <Card>
          <CardHeader
            title="Money in, last 30 days"
            subtitle="Daily takings across the period"
          />
          <div className="px-2 pb-4 pt-3">
            <RevenueTrendChart data={revenue_trend} />
          </div>
        </Card>
      </StaggerItem>

      {/* 7. Act */}
      <StaggerItem>
        <Link href="/actions" className="block">
          <Card className="border-brand/25 bg-brand-soft/50 transition-colors hover:bg-brand-soft">
            <div className="flex items-center gap-3 p-5">
              <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand text-white">
                <Sparkles className="size-5" strokeWidth={2.2} aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[14px] font-semibold text-brand-strong">
                  {active_campaign
                    ? "Your campaign is running"
                    : "Munim has actions ready"}
                </p>
                <p className="mt-0.5 text-[13px] text-muted">
                  {shortage
                    ? `Restock ${shortage.product}, then rebuild your evening window.`
                    : "One action could recover most of this week's lost revenue."}
                </p>
              </div>
              <ArrowRight className="size-5 shrink-0 text-brand" aria-hidden />
            </div>
          </Card>
        </Link>
      </StaggerItem>
    </Stagger>
  );
}

function SignalChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "negative" | "warning";
}) {
  return (
    <div className="rounded-xl bg-surface-muted px-3 py-2.5">
      <p
        className="text-[11px] font-semibold uppercase tracking-wide"
        style={{ color: tone === "negative" ? "var(--negative)" : "var(--warning)" }}
      >
        {label}
      </p>
      <p className="mt-0.5 text-[13px] font-medium text-foreground">{value}</p>
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-4 px-4 pt-6 md:px-0 md:pt-0">
      <div>
        <Skeleton className="h-4 w-40" />
        <Skeleton className="mt-2 h-6 w-56" />
      </div>
      <Card className="p-4">
        <Skeleton className="h-11 w-full rounded-xl" />
      </Card>
      <div className="grid gap-3 sm:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Card key={i} className="p-4">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="mt-3 h-7 w-28" />
            <Skeleton className="mt-3 h-3 w-full" />
          </Card>
        ))}
      </div>
      <Card className="p-6">
        <div className="flex flex-col items-center gap-6 sm:flex-row">
          <Skeleton className="size-[168px] rounded-full" />
          <div className="w-full flex-1 space-y-3">
            <Skeleton className="h-3 w-28" />
            <Skeleton className="h-7 w-40" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        </div>
      </Card>
      <div className="grid gap-3 lg:grid-cols-2">
        <SkeletonCard lines={5} />
        <SkeletonCard lines={5} />
      </div>
    </div>
  );
}
