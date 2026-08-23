"use client";

/*
  Shop Intelligence.

  What customers asked for, whether they got it, and the raw conversation
  behind every number. The transcript feed matters more than it looks: it is
  the audit trail. A merchant who can read the line that produced a claim
  will trust the claim, and a system that hides its inputs deserves less.
*/

import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  CheckCircle2,
  Mic,
  Package,
  Radio,
  Send,
  ShieldAlert,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ShopDemandChart, withFilled } from "@/components/charts";
import { ConversationTimeline } from "@/components/conversation";
import { useAppData } from "@/components/providers";
import { PageHeader } from "@/components/shell";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ErrorState,
  Skeleton,
  SkeletonCard,
  Stagger,
  StaggerItem,
} from "@/components/ui";
import { api } from "@/lib/api";
import { number, rupees } from "@/lib/format";
import type { Interaction, OutcomeSummary } from "@/types";


export default function ShopIntelligencePage() {
  const { shop, loading, error, reload, createRestock, busy, restockAlerts } = useAppData();

  const [interactions, setInteractions] = useState<Interaction[]>([]);
  const [outcomes, setOutcomes] = useState<OutcomeSummary | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const loadEvents = useCallback(async () => {
    try {
      const result = await api.shopInteractions(30);
      setInteractions(result.interactions);
      setOutcomes(result.outcomes);
    } catch {
      /* the summary above is the important part; the feed is supporting detail */
    }
  }, []);

  useEffect(() => {
    void loadEvents();
  }, [loadEvents]);

  async function submitTranscript() {
    const text = draft.trim();
    if (!text || sending) return;

    setSending(true);
    setFeedback(null);
    try {
      const result = await api.sendTranscript(text);
      setDraft("");
      setFeedback(
        result.event_count
          ? `Extracted ${result.event_count} event${result.event_count === 1 ? "" : "s"}.`
          : "No product request found in that line.",
      );
      await Promise.all([loadEvents(), reload()]);
    } catch {
      setFeedback("Could not reach the backend.");
    } finally {
      setSending(false);
    }
  }

  if (error) {
    return (
      <div className="px-4 pt-6 md:px-0">
        <ErrorState
          title="Can't load shop intelligence"
          message={error.message}
          hint={error.hint}
          onRetry={() => void reload()}
        />
      </div>
    );
  }

  if (loading || !shop) return <ShopSkeleton />;

  const alerted = new Set(restockAlerts.map((a) => a.product.toLowerCase()));

  return (
    <Stagger className="space-y-4">
      <StaggerItem>
        <PageHeader
          eyebrow="Shop Intelligence"
          title="What customers asked for"
          description="Captured from conversation at the counter. None of this appears in your payment data, because a sale that does not happen leaves no record."
          action={
            <Badge tone={shop.demo_mode ? "neutral" : "positive"} className="shrink-0">
              <Radio className="size-3.5" aria-hidden />
              {shop.demo_mode ? "Demo data" : "Live"}
            </Badge>
          }
        />
      </StaggerItem>

      <div className="space-y-4 px-4 md:px-0">
        {/* Headline numbers */}
        <StaggerItem>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat
              label="Customer requests"
              value={number(shop.total_requests)}
              hint={`${shop.conversations_captured} conversations`}
              icon={<Mic className="size-4" aria-hidden />}
            />
            <Stat
              label="Products asked for"
              value={number(shop.unique_products)}
              hint="distinct items"
              icon={<Package className="size-4" aria-hidden />}
            />
            <Stat
              label="Went unfilled"
              value={number(shop.unfulfilled_requests)}
              hint="potential missed sales"
              tone={shop.unfulfilled_requests ? "negative" : "positive"}
              icon={<AlertTriangle className="size-4" aria-hidden />}
            />
            <Stat
              label="Estimated value"
              value={shop.estimated_lost_revenue ? rupees(shop.estimated_lost_revenue) : "—"}
              hint="rough order of magnitude"
              tone={shop.estimated_lost_revenue ? "negative" : "neutral"}
              icon={<ShieldAlert className="size-4" aria-hidden />}
            />
          </div>
          <p className="mt-2 px-1 text-[11px] leading-relaxed text-subtle">
            {shop.lost_revenue_basis}
          </p>
        </StaggerItem>

        {/* Out of stock */}
        {shop.out_of_stock_requests.length ? (
          <StaggerItem>
            <Card className="border-negative/25">
              <CardHeader
                title="High demand, out of stock"
                subtitle="Asked for repeatedly and unavailable"
                icon={<AlertTriangle className="size-4" aria-hidden />}
              />
              <ul className="divide-y divide-border px-5 pb-2 pt-3">
                {shop.out_of_stock_requests.map((item) => {
                  const done = alerted.has(item.product.toLowerCase());
                  return (
                    <li
                      key={item.product}
                      className="flex flex-wrap items-center gap-3 py-3.5"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <p className="text-[15px] font-bold">{item.product}</p>
                          <Badge tone="negative">Out of stock</Badge>
                        </div>
                        <p className="mt-1 text-[13px] text-muted">
                          {item.requests} requests ·{" "}
                          <span className="font-semibold text-negative">
                            {item.unfulfilled_requests} unfilled
                          </span>
                          {item.estimated_lost_revenue
                            ? ` · about ${rupees(item.estimated_lost_revenue)} of potential sales`
                            : null}
                        </p>
                      </div>
                      {done ? (
                        <Badge tone="positive" className="shrink-0">
                          <CheckCircle2 className="size-3.5" aria-hidden />
                          Restock alert raised
                        </Badge>
                      ) : (
                        <Button
                          size="sm"
                          loading={busy}
                          onClick={() => void createRestock(item.product)}
                          className="shrink-0"
                        >
                          Restock {item.product}
                        </Button>
                      )}
                    </li>
                  );
                })}
              </ul>
            </Card>
          </StaggerItem>
        ) : null}

        {/* Outcome breakdown */}
        {outcomes ? (
          <StaggerItem>
            <Card>
              <CardHeader
                title="What happened to each request"
                subtitle={
                  outcomes.fulfillment_rate !== null
                    ? `${outcomes.fulfillment_rate.toFixed(0)}% of decided exchanges ended in a sale`
                    : "Not enough decided exchanges to rate yet"
                }
                icon={<CheckCircle2 className="size-4" aria-hidden />}
              />
              <div className="grid grid-cols-2 gap-px bg-border sm:grid-cols-5">
                {(
                  [
                    ["fulfilled", "Fulfilled", "var(--positive)"],
                    ["unfulfilled", "Unfulfilled", "var(--negative)"],
                    ["alternative_offered", "Alternative", "var(--warning)"],
                    ["abandoned", "Abandoned", "var(--subtle)"],
                    ["uncertain", "Uncertain", "var(--subtle)"],
                  ] as const
                ).map(([key, label, color]) => (
                  <div key={key} className="bg-surface px-3 py-3.5 text-center">
                    <p
                      className="tnum text-[20px] font-bold leading-none"
                      style={{ color }}
                    >
                      {outcomes.counts[key] ?? 0}
                    </p>
                    <p className="mt-1 text-[11px] text-subtle">{label}</p>
                  </div>
                ))}
              </div>
              <div className="border-t border-border px-5 py-3">
                <p className="text-[11px] leading-relaxed text-subtle">
                  Only decided exchanges count toward the rate. Uncertain ones are
                  excluded so poor audio does not read as poor service.
                </p>
              </div>
            </Card>
          </StaggerItem>
        ) : null}

        {/* Demand by hour */}
        <StaggerItem>
          <Card>
            <CardHeader
              title="Demand through the day"
              subtitle="Requests heard per hour, and how many went unfilled"
            />
            <div className="px-3 pb-4 pt-3">
              <ShopDemandChart data={withFilled(shop.hourly_demand)} />
            </div>
          </Card>
        </StaggerItem>

        {/* Ranked demand */}
        <StaggerItem>
          <Card>
            <CardHeader title="Most requested" subtitle="Ranked by unfilled demand, then volume" />
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-[13px]">
                <thead>
                  <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-subtle">
                    <th className="px-5 py-2.5 font-semibold">Product</th>
                    <th className="px-3 py-2.5 text-right font-semibold">Asked</th>
                    <th className="px-3 py-2.5 text-right font-semibold">Unfilled</th>
                    <th className="px-5 py-2.5 text-right font-semibold">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {shop.products.map((product) => (
                    <tr key={product.family}>
                      <td className="px-5 py-2.5">
                        <span className="font-semibold">{product.product}</span>
                        {product.high_demand ? (
                          <span className="ml-2 text-[11px] text-warning">🔥 high demand</span>
                        ) : null}
                      </td>
                      <td className="tnum px-3 py-2.5 text-right">{product.requests}</td>
                      <td
                        className="tnum px-3 py-2.5 text-right font-semibold"
                        style={{
                          color: product.unfulfilled_requests
                            ? "var(--negative)"
                            : "var(--subtle)",
                        }}
                      >
                        {product.unfulfilled_requests || "—"}
                      </td>
                      <td className="px-5 py-2.5 text-right">
                        <Badge
                          tone={
                            product.availability === "out_of_stock"
                              ? "negative"
                              : product.availability === "intermittent"
                                ? "warning"
                                : "positive"
                          }
                        >
                          {product.availability.replace(/_/g, " ")}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </StaggerItem>

        {/* Fraud signals */}
        {shop.fraud_signals.length ? (
          <StaggerItem>
            <Card className="border-warning/30">
              <CardHeader
                title="Signals worth a look"
                subtitle="Phrases flagged in conversation. Not accusations: context matters."
                icon={<ShieldAlert className="size-4" aria-hidden />}
              />
              <ul className="space-y-2 px-5 pb-5 pt-3">
                {shop.fraud_signals.slice(0, 5).map((signal) => (
                  <li key={signal.event_id} className="rounded-xl bg-warning-soft/60 p-3">
                    <p className="text-[12px] font-semibold text-warning">{signal.reason}</p>
                    <p className="mt-1 text-[13px] italic text-foreground">
                      &ldquo;{signal.transcript}&rdquo;
                    </p>
                  </li>
                ))}
              </ul>
            </Card>
          </StaggerItem>
        ) : null}

        {/* Live feed + manual input */}
        <StaggerItem>
          <Card>
            <CardHeader
              title="Conversation feed"
              subtitle="Every number above traces back to one of these lines"
              icon={<Mic className="size-4" aria-hidden />}
            />

            {/* Test the pipeline without a microphone. */}
            <div className="px-5 pt-4">
              <label
                htmlFor="transcript"
                className="text-[12px] font-semibold text-subtle"
              >
                Try it: type what a customer might say
              </label>
              <div className="mt-1.5 flex gap-2">
                <input
                  id="transcript"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void submitTranscript();
                  }}
                  placeholder="Bhaiya Maggi hai? Nahi khatam ho gaya"
                  className="h-11 min-w-0 flex-1 rounded-xl border border-border-strong bg-surface px-3 text-[14px] outline-none focus-visible:ring-2 focus-visible:ring-brand"
                />
                <Button
                  onClick={() => void submitTranscript()}
                  loading={sending}
                  className="shrink-0"
                >
                  <Send className="size-4" aria-hidden />
                  Send
                </Button>
              </div>
              <AnimatePresence>
                {feedback ? (
                  <motion.p
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    className="mt-2 text-[12px] text-brand"
                  >
                    {feedback}
                  </motion.p>
                ) : null}
              </AnimatePresence>
            </div>

            <ul className="divide-y divide-border px-5 pb-3 pt-4">
              {interactions.length === 0 ? (
                <li className="py-6 text-center text-[13px] text-subtle">
                  No conversations captured yet.
                </li>
              ) : (
                interactions.map((interaction) => (
                  <li key={interaction.interaction_id} className="py-4">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <span className="tnum text-[11px] text-subtle">
                        {new Date(interaction.timestamp).toLocaleString("en-IN", {
                          day: "numeric",
                          month: "short",
                          hour: "numeric",
                          minute: "2-digit",
                        })}
                      </span>
                      {interaction.product ? (
                        <Badge
                          tone={
                            interaction.potential_lost_sale ? "negative" : "brand"
                          }
                        >
                          {interaction.product}
                          {interaction.quantity && interaction.quantity > 1
                            ? ` x${interaction.quantity}`
                            : ""}
                        </Badge>
                      ) : null}
                      <span className="ml-auto text-[11px] text-subtle">
                        {Math.round(interaction.confidence * 100)}% · {interaction.extractor}
                      </span>
                    </div>
                    <ConversationTimeline interaction={interaction} />
                  </li>
                ))
              )}
            </ul>
          </Card>
        </StaggerItem>

        <StaggerItem>
          <p className="px-1 pb-2 text-[11px] leading-relaxed text-subtle">
            Audio is captured by a Raspberry Pi at the counter, transcribed, and
            reduced to structured events. Product names are matched against a
            292-item catalogue by a deterministic matcher, never invented by a
            model.{" "}
            {shop.transcription.available
              ? "Backend transcription is available."
              : "Backend transcription is not installed; clients send text."}
          </p>
        </StaggerItem>
      </div>
    </Stagger>
  );
}

function Stat({
  label,
  value,
  hint,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint: string;
  icon: React.ReactNode;
  tone?: "neutral" | "negative" | "positive";
}) {
  const color =
    tone === "negative"
      ? "var(--negative)"
      : tone === "positive"
        ? "var(--positive)"
        : "var(--foreground)";
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-subtle">
        {icon}
        <p className="text-[12px] font-medium">{label}</p>
      </div>
      <p className="tnum mt-2 text-[20px] font-bold tracking-tight" style={{ color }}>
        {value}
      </p>
      <p className="mt-1 text-[11px] text-subtle">{hint}</p>
    </Card>
  );
}

function ShopSkeleton() {
  return (
    <div className="space-y-4 px-4 pt-6 md:px-0 md:pt-0">
      <Skeleton className="h-7 w-56" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i} className="p-4">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="mt-3 h-6 w-16" />
          </Card>
        ))}
      </div>
      <SkeletonCard lines={4} />
      <SkeletonCard lines={6} />
    </div>
  );
}
