"use client";

/*
  AI Insights.

  The unified list leads: findings that pair a payment signal with a
  shop-floor signal, which is the only thing here neither source could have
  produced alone. Each one shows both signals separately before the joined
  reading, so the merchant can check the reasoning rather than take it.

  Confidence is on the card, not buried. A temporal correlation is worth
  something and it is worth saying how much.
*/

import {
  ArrowRight,
  Layers,
  Mic,
  Receipt,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { HourlyChart } from "@/components/charts";
import { useAppData } from "@/components/providers";
import { PageHeader } from "@/components/shell";
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
import { api } from "@/lib/api";
import type { UnifiedInsight, UnifiedKind } from "@/types";

const KIND_META: Record<
  UnifiedKind,
  { label: string; icon: typeof Layers; accent: string }
> = {
  unified: { label: "Payments + shop floor", icon: Layers, accent: "var(--brand)" },
  transaction: { label: "Payment data", icon: Receipt, accent: "var(--negative)" },
  shop: { label: "Shop floor", icon: Mic, accent: "var(--warning)" },
};

const PRIMARY_QUESTION = "Why did my score drop?";

export default function InsightsPage() {
  const { unified, dashboard, loading, error, reload } = useAppData();

  const [answer, setAnswer] = useState<string | null>(null);
  const [provider, setProvider] = useState<string | null>(null);
  const [thinking, setThinking] = useState(true);

  const runAnalysis = useCallback(async () => {
    try {
      const result = await api.ask(PRIMARY_QUESTION);
      setAnswer(result.answer);
      setProvider(result.provider);
    } catch {
      setAnswer(null);
    } finally {
      setThinking(false);
    }
  }, []);

  useEffect(() => {
    void runAnalysis();
  }, [runAnalysis]);

  if (error) {
    return (
      <div className="px-4 pt-6 md:px-0">
        <ErrorState
          title="Can't load your insights"
          message={error.message}
          hint={error.hint}
          onRetry={() => void reload()}
        />
      </div>
    );
  }

  if (loading || !unified) return <InsightsSkeleton />;

  const { insights, counts, positive_signals, methodology } = unified;

  return (
    <Stagger className="space-y-4">
      <StaggerItem>
        <PageHeader
          eyebrow="AI Insights"
          title="Why your score moved"
          description={`${counts.unified} finding${counts.unified === 1 ? "" : "s"} combine payment and shop-floor evidence. ${counts.transaction_only + counts.shop_only} come from one source alone.`}
        />
      </StaggerItem>

      <div className="space-y-4 px-4 md:px-0">
        {/* AI narrative */}
        <StaggerItem>
          <Card className="overflow-hidden border-brand/25">
            <div className="flex items-center gap-2.5 border-b border-border bg-brand-soft/60 px-5 py-3">
              <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-brand text-white">
                <Sparkles className="size-4" strokeWidth={2.2} aria-hidden />
              </span>
              <p className="text-[13px] font-bold text-brand-strong">
                Paytm Vyapaar AI
              </p>
              {provider ? (
                <span className="ml-auto text-[11px] text-muted">
                  {provider === "template" ? "built-in engine" : provider}
                </span>
              ) : null}
            </div>
            <div className="p-5">
              {thinking ? (
                <div className="space-y-2.5">
                  <Skeleton className="h-3 w-full" />
                  <Skeleton className="h-3 w-11/12" />
                  <Skeleton className="h-3 w-3/4" />
                </div>
              ) : answer ? (
                <div className="space-y-3">
                  {answer.split("\n\n").map((para, i) => (
                    <p key={i} className="text-[14px] leading-relaxed text-foreground">
                      {para}
                    </p>
                  ))}
                </div>
              ) : (
                <p className="text-[14px] text-muted">
                  The AI narrative could not load. The findings below are unaffected.
                </p>
              )}
              <Link href="/chat" className="mt-4 inline-block">
                <Button size="sm" variant="secondary">
                  Ask a follow-up
                  <ArrowRight className="size-4" aria-hidden />
                </Button>
              </Link>
            </div>
          </Card>
        </StaggerItem>

        {/* Ranked findings */}
        <StaggerItem>
          <h2 className="px-1 pb-1 pt-2 text-[15px] font-semibold tracking-tight">
            Findings, ranked
          </h2>
        </StaggerItem>

        {insights.map((insight) => (
          <StaggerItem key={insight.id}>
            <InsightCard insight={insight} />
          </StaggerItem>
        ))}

        {/* Positives */}
        {positive_signals.length ? (
          <StaggerItem>
            <Card className="border-positive/25">
              <CardHeader
                title="Working well"
                subtitle="Worth protecting while you fix the rest"
                icon={<TrendingUp className="size-4" aria-hidden />}
              />
              <ul className="divide-y divide-border px-5 pb-3 pt-2">
                {positive_signals.map((signal) => (
                  <li key={signal.id} className="flex items-start gap-3 py-3">
                    <span
                      className="mt-1.5 size-2 shrink-0 rounded-full"
                      style={{ background: "var(--positive)" }}
                      aria-hidden
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-[14px] font-semibold">{signal.metric}</p>
                        <DeltaPill value={signal.change_percent} tone="positive" />
                      </div>
                      <p className="mt-1 text-[13px] leading-relaxed text-muted">
                        {signal.description}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          </StaggerItem>
        ) : null}

        {/* Hourly distribution */}
        <StaggerItem>
          <Card>
            <CardHeader
              title="Transactions through the day"
              subtitle="This week against your 4-week average"
            />
            <div className="px-4 pb-5 pt-4">
              <HourlyChart data={unified.hourly_distribution} />
            </div>
          </Card>
        </StaggerItem>

        {/* Methodology */}
        <StaggerItem>
          <Card className="bg-surface-muted">
            <div className="p-5">
              <p className="text-[12px] font-semibold text-subtle">How this is worked out</p>
              <p className="mt-1.5 text-[13px] leading-relaxed text-muted">
                {methodology.join}
              </p>
              <p className="mt-2 text-[13px] leading-relaxed text-muted">
                {methodology.causation}
              </p>
            </div>
          </Card>
        </StaggerItem>

        <StaggerItem>
          <Link href="/actions" className="block">
            <Card className="border-brand/25 bg-brand-soft/50 transition-colors hover:bg-brand-soft">
              <div className="flex items-center gap-3 p-5">
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand text-white">
                  <Sparkles className="size-5" strokeWidth={2.2} aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] font-semibold text-brand-strong">
                    See what to do about it
                  </p>
                  <p className="mt-0.5 text-[13px] text-muted">
                    {dashboard?.active_campaign
                      ? "Your campaign is already running."
                      : "Restock and campaign actions, sized from your own data."}
                  </p>
                </div>
                <ArrowRight className="size-5 shrink-0 text-brand" aria-hidden />
              </div>
            </Card>
          </Link>
        </StaggerItem>
      </div>
    </Stagger>
  );
}

function InsightCard({ insight }: { insight: UnifiedInsight }) {
  const meta = KIND_META[insight.kind];
  const Icon = meta.icon;

  return (
    <Card className={insight.kind === "unified" ? "border-brand/30" : undefined}>
      <div className="flex flex-wrap items-start gap-3 px-5 pt-5">
        <span
          className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl"
          style={{ background: `color-mix(in srgb, ${meta.accent} 12%, white)`, color: meta.accent }}
        >
          <Icon className="size-4" strokeWidth={2.2} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[15px] font-semibold tracking-tight">{insight.title}</h3>
            <Badge
              tone={
                insight.severity === "high"
                  ? "negative"
                  : insight.severity === "medium"
                    ? "warning"
                    : "neutral"
              }
            >
              {insight.severity}
            </Badge>
          </div>
          <p className="mt-0.5 text-[11px] font-semibold uppercase tracking-wide text-subtle">
            {meta.label} · {Math.round(insight.confidence * 100)}% confidence
          </p>
        </div>
      </div>

      {/* The two signals, shown separately before they are read together */}
      {insight.kind === "unified" ? (
        <div className="mt-4 grid gap-2 px-5 sm:grid-cols-2">
          <SignalBox
            icon={<Receipt className="size-3.5" aria-hidden />}
            label="Payment signal"
            primary={`${insight.transaction_signal?.metric} ${insight.transaction_signal?.change_percent}%`}
            secondary={insight.transaction_signal?.window ?? ""}
            accent="var(--negative)"
          />
          <SignalBox
            icon={<Mic className="size-3.5" aria-hidden />}
            label="Shop-floor signal"
            primary={`${insight.shop_signal?.product}: ${insight.shop_signal?.requests} requests`}
            secondary={`${insight.shop_signal?.unfulfilled_requests} unfilled · out of stock`}
            accent="var(--warning)"
          />
        </div>
      ) : null}

      <div className="px-5 py-4">
        <p className="text-[14px] leading-relaxed text-foreground">{insight.explanation}</p>
        <p className="mt-2.5 text-[11px] leading-relaxed text-subtle">
          {insight.correlation_note}
        </p>
      </div>

      {insight.recommended_actions.length ? (
        <div className="border-t border-border bg-surface-muted px-5 py-3.5">
          <p className="text-[12px] font-semibold text-subtle">Recommended</p>
          <ul className="mt-1.5 space-y-1">
            {insight.recommended_actions.map((action) => (
              <li key={action} className="flex items-center gap-2 text-[13px] text-foreground">
                <ArrowRight className="size-3.5 shrink-0 text-brand" aria-hidden />
                {action}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}

function SignalBox({
  icon,
  label,
  primary,
  secondary,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  primary: string;
  secondary: string;
  accent: string;
}) {
  return (
    <div className="rounded-xl bg-surface-muted p-3">
      <p
        className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide"
        style={{ color: accent }}
      >
        {icon}
        {label}
      </p>
      <p className="mt-1 text-[13px] font-semibold text-foreground">{primary}</p>
      {secondary ? <p className="text-[12px] text-muted">{secondary}</p> : null}
    </div>
  );
}

function InsightsSkeleton() {
  return (
    <div className="space-y-4 px-4 pt-6 md:px-0 md:pt-0">
      <Skeleton className="h-7 w-56" />
      <SkeletonCard lines={4} />
      <SkeletonCard lines={5} />
      <SkeletonCard lines={4} />
    </div>
  );
}
