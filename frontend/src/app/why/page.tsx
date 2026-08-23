"use client";

/*
  "Why did my score drop?"

  The layout enforces the honesty rule that the backend enforces in data:
  two separately-headed sections that never blend.

    DIRECTLY OBSERVED            measured in the payment ledger
    POTENTIAL DEMAND GAP         inferred from shop-floor conversation

  Different headings, different colours, different confidence labels, and the
  correlation caveat printed on the card rather than in a footnote. A merchant
  should never have to guess which kind of claim they are reading.
*/

import {
  ArrowRight,
  Calculator,
  Mic,
  Package,
  Receipt,
  ShoppingBasket,
  Sparkles,
  TrendingDown,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ScoreMeter } from "@/components/charts";
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
import { ConversationTimeline } from "@/components/conversation";
import { api } from "@/lib/api";
import { scoreColor } from "@/lib/format";
import type { ContributingFactor, DirectCause, Interaction } from "@/types";

export default function WhyPage() {
  const { rootCause, loading, error, reload } = useAppData();
  const [interactions, setInteractions] = useState<Interaction[]>([]);

  const loadInteractions = useCallback(async () => {
    try {
      const result = await api.shopInteractions(30);
      setInteractions(result.interactions);
    } catch {
      /* the analysis above is the point; the timeline is supporting detail */
    }
  }, []);

  useEffect(() => {
    void loadInteractions();
  }, [loadInteractions]);

  if (error) {
    return (
      <div className="px-4 pt-6 md:px-0">
        <ErrorState
          title="Can't load the analysis"
          message={error.message}
          hint={error.hint}
          onRetry={() => void reload()}
        />
      </div>
    );
  }

  if (loading || !rootCause) return <WhySkeleton />;

  const { score, narrative, direct_evidence, possible_contributing_factors } = rootCause;
  const demand = rootCause.demand_fulfillment;

  // The clearest single example of the gap: an exchange where a customer
  // asked and left without it.
  const lostSale = interactions.find(
    (i) => i.interaction_outcome === "unfulfilled" && i.conversation.length >= 2,
  );

  return (
    <Stagger className="space-y-4">
      <StaggerItem>
        <PageHeader
          eyebrow="Root cause analysis"
          title={score.change < 0 ? "Why your score dropped" : "What moved your score"}
          description={narrative}
        />
      </StaggerItem>

      <div className="space-y-4 px-4 md:px-0">
        {/* Score movement */}
        <StaggerItem>
          <Card>
            <div className="flex flex-wrap items-center gap-5 p-5">
              <div className="flex items-center gap-3">
                <span
                  className="tnum text-[34px] font-bold leading-none"
                  style={{ color: scoreColor(score.previous) }}
                >
                  {score.previous}
                </span>
                <TrendingDown className="size-5 text-negative" aria-hidden />
                <span
                  className="tnum text-[34px] font-bold leading-none"
                  style={{ color: scoreColor(score.current) }}
                >
                  {score.current}
                </span>
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={score.change < 0 ? "negative" : "positive"}>
                    {score.change > 0 ? "+" : ""}
                    {score.change} points this week
                  </Badge>
                  <Badge tone="neutral">{score.status}</Badge>
                </div>
                <div className="mt-3">
                  <ScoreMeter score={score.current} color={scoreColor(score.current)} />
                </div>
              </div>
            </div>
            {score.comparable_basis ? (
              <div className="border-t border-border bg-surface-muted px-5 py-2.5">
                <p className="text-[11px] text-subtle">
                  Both weeks are scored on the same basis, including shop-floor
                  data, so this change is real and not an artefact of new data
                  arriving.
                </p>
              </div>
            ) : null}
          </Card>
        </StaggerItem>

        {/* DIRECTLY OBSERVED */}
        <StaggerItem>
          <div className="flex items-center gap-2 px-1 pt-2">
            <Receipt className="size-4 text-negative" aria-hidden />
            <h2 className="text-[13px] font-bold uppercase tracking-wider text-negative">
              Directly observed
            </h2>
            <span className="text-[11px] text-subtle">measured in your payment data</span>
          </div>
        </StaggerItem>

        <StaggerItem>
          <Card className="border-negative/20">
            <ul className="divide-y divide-border">
              {direct_evidence.map((cause) => (
                <CauseRow key={cause.id} cause={cause} />
              ))}
            </ul>
          </Card>
        </StaggerItem>

        {/* POTENTIAL DEMAND GAP */}
        {possible_contributing_factors.length ? (
          <>
            <StaggerItem>
              <div className="flex items-center gap-2 px-1 pt-3">
                <Mic className="size-4 text-warning" aria-hidden />
                <h2 className="text-[13px] font-bold uppercase tracking-wider text-warning">
                  Potential demand gap
                </h2>
                <span className="text-[11px] text-subtle">
                  heard on the shop floor, not proven
                </span>
              </div>
            </StaggerItem>

            {possible_contributing_factors.map((factor) => (
              <StaggerItem key={factor.id}>
                <FactorCard factor={factor} />
              </StaggerItem>
            ))}
          </>
        ) : null}

        {/* Buyer -> seller timeline */}
        {lostSale ? (
          <StaggerItem>
            <Card>
              <CardHeader
                title="What a lost sale sounds like"
                subtitle="One captured exchange, with the roles the system read"
                icon={<ShoppingBasket className="size-4" aria-hidden />}
              />
              <div className="p-5">
                <ConversationTimeline interaction={lostSale} />
              </div>
            </Card>
          </StaggerItem>
        ) : null}

        {/* Demand fulfilment component */}
        {demand ? (
          <StaggerItem>
            <Card>
              <CardHeader
                title="Demand Fulfilment"
                subtitle={demand.summary}
                icon={<Package className="size-4" aria-hidden />}
                action={
                  <span
                    className="tnum shrink-0 text-[22px] font-bold"
                    style={{ color: scoreColor(demand.score) }}
                  >
                    {Math.round(demand.score)}
                  </span>
                }
              />
              <div className="grid grid-cols-3 divide-x divide-border border-y border-border">
                {demand.drivers.map((driver) => (
                  <div key={driver.label} className="px-3 py-3.5 text-center">
                    <p className="text-[11px] text-subtle">{driver.label}</p>
                    <p
                      className="tnum mt-1 text-[15px] font-bold"
                      style={{
                        color:
                          driver.tone === "negative"
                            ? "var(--negative)"
                            : driver.tone === "positive"
                              ? "var(--positive)"
                              : "var(--foreground)",
                      }}
                    >
                      {driver.value}
                    </p>
                  </div>
                ))}
              </div>
              <div className="px-5 py-4">
                <p className="text-[12px] leading-relaxed text-muted">{demand.method}</p>
                <p className="mt-2 text-[11px] leading-relaxed text-subtle">
                  {demand.sampling_caveat}
                </p>
              </div>
            </Card>
          </StaggerItem>
        ) : null}

        {/* Score attribution */}
        <StaggerItem>
          <Card>
            <CardHeader
              title="Where the points went"
              subtitle="Each component's change multiplied by its weight. These sum to the total."
              icon={<Calculator className="size-4" aria-hidden />}
            />
            <div className="overflow-x-auto">
              <table className="w-full min-w-[440px] text-[13px]">
                <thead>
                  <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-subtle">
                    <th className="px-5 py-2.5 font-semibold">Component</th>
                    <th className="px-3 py-2.5 text-right font-semibold">Was</th>
                    <th className="px-3 py-2.5 text-right font-semibold">Now</th>
                    <th className="px-3 py-2.5 text-right font-semibold">Weight</th>
                    <th className="px-5 py-2.5 text-right font-semibold">Points</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {rootCause.score_attribution.map((row) => (
                    <tr key={row.component}>
                      <td className="px-5 py-2.5 font-medium">{row.label}</td>
                      <td className="tnum px-3 py-2.5 text-right text-subtle">{row.before}</td>
                      <td className="tnum px-3 py-2.5 text-right">{row.after}</td>
                      <td className="tnum px-3 py-2.5 text-right text-subtle">
                        {(row.weight * 100).toFixed(0)}%
                      </td>
                      <td
                        className="tnum px-5 py-2.5 text-right font-semibold"
                        style={{
                          color:
                            row.points_contributed < 0
                              ? "var(--negative)"
                              : row.points_contributed > 0
                                ? "var(--positive)"
                                : "var(--subtle)",
                        }}
                      >
                        {row.points_contributed > 0 ? "+" : ""}
                        {row.points_contributed.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                  <tr className="bg-surface-muted font-bold">
                    <td className="px-5 py-2.5" colSpan={4}>
                      Total
                    </td>
                    <td className="tnum px-5 py-2.5 text-right text-negative">
                      {score.change > 0 ? "+" : ""}
                      {score.change}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div className="border-t border-border px-5 py-3">
              <p className="text-[11px] leading-relaxed text-subtle">
                {rootCause.methodology.separation}
              </p>
            </div>
          </Card>
        </StaggerItem>

        {/* Next step */}
        <StaggerItem>
          <Link href="/actions" className="block">
            <Card className="border-brand/25 bg-brand-soft/50 transition-colors hover:bg-brand-soft">
              <div className="flex items-center gap-3 p-5">
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand text-white">
                  <Sparkles className="size-5" strokeWidth={2.2} aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] font-semibold text-brand-strong">
                    How can I improve?
                  </p>
                  <p className="mt-0.5 text-[13px] text-muted">
                    Restock and campaign actions, sized from these same numbers.
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

function CauseRow({ cause }: { cause: DirectCause }) {
  return (
    <li className="flex items-start gap-3 px-5 py-4">
      <span
        className="mt-1.5 size-2 shrink-0 rounded-full"
        style={{ background: "var(--negative)" }}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[14px] font-semibold">{cause.title}</p>
          <DeltaPill value={cause.change_percent} tone="negative" />
          <Badge tone="negative">-{cause.points_lost.toFixed(1)} pts</Badge>
        </div>
        <p className="mt-1 text-[13px] leading-relaxed text-muted">{cause.detail}</p>
        <p className="mt-1.5 text-[11px] text-subtle">
          {cause.evidence_type} · {Math.round(cause.confidence * 100)}% confidence
        </p>
      </div>
    </li>
  );
}

function FactorCard({ factor }: { factor: ContributingFactor }) {
  return (
    <Card className="border-warning/30">
      <div className="flex items-start gap-3 p-5">
        <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl bg-warning-soft text-warning">
          <Mic className="size-4" strokeWidth={2.2} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[15px] font-semibold tracking-tight">{factor.title}</h3>
            <Badge tone="warning">
              {Math.round(factor.confidence * 100)}% confidence
            </Badge>
          </div>

          {factor.product ? (
            <div className="mt-3 flex flex-wrap gap-2">
              <Stat label="Requests" value={String(factor.requests)} />
              <Stat
                label="Unfilled"
                value={String(factor.unfulfilled_requests)}
                tone="negative"
              />
              {factor.requests_in_declining_window ? (
                <Stat
                  label="In the declining window"
                  value={String(factor.requests_in_declining_window)}
                  tone="negative"
                />
              ) : null}
            </div>
          ) : null}

          <p className="mt-3 text-[14px] leading-relaxed text-foreground">{factor.detail}</p>
          <p className="mt-2 text-[11px] leading-relaxed text-subtle">
            {factor.correlation_note}
          </p>
        </div>
      </div>
    </Card>
  );
}

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "negative";
}) {
  return (
    <div className="rounded-lg bg-surface-muted px-3 py-1.5">
      <span className="text-[11px] text-subtle">{label} </span>
      <span
        className="tnum text-[14px] font-bold"
        style={{ color: tone === "negative" ? "var(--negative)" : "var(--foreground)" }}
      >
        {value}
      </span>
    </div>
  );
}

function WhySkeleton() {
  return (
    <div className="space-y-4 px-4 pt-6 md:px-0 md:pt-0">
      <Skeleton className="h-7 w-64" />
      <SkeletonCard lines={3} />
      <SkeletonCard lines={5} />
      <SkeletonCard lines={4} />
    </div>
  );
}
