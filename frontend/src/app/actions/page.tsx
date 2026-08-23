"use client";

/*
  Actions.

  Three kinds, and the ordering is the recommendation. When there is both a
  shortage and a weak trading window, the combined action leads and the
  campaign is explicitly sequenced behind the restock, because driving
  traffic at an empty shelf spends cashback to reproduce the original
  disappointment.

  Every projected figure on this page is labelled Simulated / Projected and
  carries the assumptions it rests on.
*/

import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  Check,
  Clock,
  Info,
  Package,
  PartyPopper,
  Target,
  TrendingUp,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ScoreMeter } from "@/components/charts";
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
import { rupees, scoreColor } from "@/lib/format";
import type { ActionProjection, MerchantAction } from "@/types";

export default function ActionsPage() {
  const {
    plan,
    activeCampaign,
    restockAlerts,
    launchedProjection,
    restockProjection,
    busy,
    actionError,
    launchCampaign,
    createRestock,
    resetDemo,
    loading,
    error,
    reload,
  } = useAppData();

  const [confirming, setConfirming] = useState(false);
  const [celebrate, setCelebrate] = useState<string | null>(null);

  if (error) {
    return (
      <div className="px-4 pt-6 md:px-0">
        <ErrorState
          title="Can't load your actions"
          message={error.message}
          hint={error.hint}
          onRetry={() => void reload()}
        />
      </div>
    );
  }

  if (loading || !plan) return <ActionsSkeleton />;

  const campaign = plan.actions.find((a) => a.type === "campaign");
  const combined = plan.actions.find((a) => a.type === "combined");
  const restocks = plan.actions.filter((a) => a.type === "restock");
  const isCampaignActive = Boolean(activeCampaign);
  const alerted = new Set(restockAlerts.map((a) => a.product.toLowerCase()));

  const bothDone = isCampaignActive && restocks.every((r) => alerted.has((r.product ?? "").toLowerCase()));

  async function onLaunch() {
    const ok = await launchCampaign();
    if (ok) {
      setConfirming(false);
      setCelebrate("campaign");
    }
  }

  async function onRestock(product: string) {
    const ok = await createRestock(product);
    if (ok) setCelebrate("restock");
  }

  return (
    <Stagger className="space-y-4">
      <StaggerItem>
        <PageHeader
          eyebrow="Recommended actions"
          title={bothDone ? "Both actions are live" : "What to do this week"}
          description={
            combined?.sequencing_note ??
            "Chosen because they target the biggest gaps in your week."
          }
          action={
            isCampaignActive || restockAlerts.length ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setCelebrate(null);
                  void resetDemo();
                }}
              >
                Reset demo
              </Button>
            ) : null
          }
        />
      </StaggerItem>

      <div className="space-y-4 px-4 md:px-0">
        <AnimatePresence>
          {celebrate ? (
            <motion.div
              initial={{ opacity: 0, y: -8, height: 0 }}
              animate={{ opacity: 1, y: 0, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            >
              <Card className="border-positive/30 bg-positive-soft">
                <div className="flex items-start gap-3 p-5">
                  <motion.span
                    className="grid size-10 shrink-0 place-items-center rounded-full bg-positive text-white"
                    initial={{ scale: 0.5, rotate: -20 }}
                    animate={{ scale: 1, rotate: 0 }}
                    transition={{ type: "spring", stiffness: 320, damping: 16 }}
                  >
                    <PartyPopper className="size-5" strokeWidth={2.2} aria-hidden />
                  </motion.span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[15px] font-bold text-positive">
                      {celebrate === "campaign"
                        ? "Campaign active"
                        : "Restock alert created"}
                    </p>
                    <p className="mt-1 text-[13px] leading-relaxed text-foreground">
                      {celebrate === "campaign"
                        ? "Evening Boost is live. Paytm Vyapaar AI will track its impact on your Business Health Score."
                        : "Your restock list is updated. Vyapaar AI will keep counting requests until the product is back."}
                    </p>
                  </div>
                </div>
              </Card>
            </motion.div>
          ) : null}
        </AnimatePresence>

        {/* Combined plan */}
        {combined ? (
          <StaggerItem>
            <Card className="overflow-hidden border-brand/30">
              <div className="bg-brand px-5 py-5 text-white">
                <p className="text-[12px] font-semibold uppercase tracking-widest text-white/70">
                  Recommended · do both, in this order
                </p>
                <h2 className="mt-1 text-[20px] font-bold tracking-tight">
                  {combined.name}
                </h2>
                <p className="mt-1.5 text-[14px] text-white/85">{combined.headline}</p>
              </div>

              <ol className="divide-y divide-border">
                {combined.steps?.map((step) => (
                  <li key={step.order} className="flex gap-3 p-5">
                    <span className="grid size-7 shrink-0 place-items-center rounded-full bg-brand-soft text-[13px] font-bold text-brand">
                      {step.order}
                    </span>
                    <div className="min-w-0">
                      <p className="text-[14px] font-semibold">{step.title}</p>
                      <p className="mt-0.5 text-[13px] leading-relaxed text-muted">
                        {step.detail}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>

              <div className="border-t border-border bg-warning-soft/40 px-5 py-3.5">
                <div className="flex gap-2.5">
                  <Info className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
                  <p className="text-[12px] leading-relaxed text-muted">
                    {combined.sequencing_note}
                  </p>
                </div>
              </div>
            </Card>
          </StaggerItem>
        ) : null}

        {/* Restock actions */}
        {restocks.map((action) => {
          const done = alerted.has((action.product ?? "").toLowerCase());
          return (
            <StaggerItem key={action.id}>
              <Card>
                <CardHeader
                  title={action.name}
                  subtitle={action.headline}
                  icon={<Package className="size-4" aria-hidden />}
                  action={
                    <Badge tone={action.priority === "high" ? "negative" : "warning"}>
                      {action.priority} priority
                    </Badge>
                  }
                />

                <div className="grid grid-cols-3 divide-x divide-border border-y border-border">
                  <Facet
                    label="Asked for"
                    value={`${action.evidence?.requests ?? 0}x`}
                    icon={<Users className="size-4" aria-hidden />}
                  />
                  <Facet
                    label="Unfilled"
                    value={`${action.evidence?.unfulfilled_requests ?? 0}x`}
                    icon={<X className="size-4" aria-hidden />}
                  />
                  <Facet
                    label="Peak hour"
                    value={
                      action.evidence?.peak_hour != null
                        ? `${action.evidence.peak_hour}:00`
                        : "—"
                    }
                    icon={<Clock className="size-4" aria-hidden />}
                  />
                </div>

                <div className="p-5">
                  <ul className="space-y-2">
                    {action.rationale?.map((reason, i) => (
                      <li
                        key={i}
                        className="flex gap-2.5 text-[13px] leading-relaxed text-muted"
                      >
                        <Check
                          className="mt-0.5 size-4 shrink-0 text-positive"
                          strokeWidth={2.4}
                          aria-hidden
                        />
                        {reason}
                      </li>
                    ))}
                  </ul>

                  {action.projection.recovered_revenue_per_week ? (
                    <div className="mt-4 rounded-xl bg-surface-muted p-4">
                      <p className="text-[12px] font-medium text-subtle">
                        Simulated / Projected Impact
                      </p>
                      <p className="tnum mt-1.5 text-[24px] font-bold leading-none text-positive">
                        {rupees(action.projection.recovered_revenue_per_week)}
                        <span className="ml-1.5 text-[13px] font-medium text-muted">
                          per week
                        </span>
                      </p>
                      <p className="mt-2 text-[12px] leading-relaxed text-muted">
                        About {action.projection.recovered_transactions_per_week} recovered
                        sales a week. That is real revenue but only{" "}
                        {action.projection.delta === 0
                          ? "a fraction of a point"
                          : `${action.projection.delta} points`}{" "}
                        of Business Health Score, because the score is dominated by your
                        overall transaction volume.
                      </p>
                    </div>
                  ) : null}
                </div>

                <div className="border-t border-border px-5 py-4">
                  {done ? (
                    <Badge tone="positive">
                      <Check className="size-3.5" aria-hidden />
                      Restock alert created
                    </Badge>
                  ) : (
                    <Button
                      size="lg"
                      className="w-full"
                      loading={busy}
                      onClick={() => void onRestock(action.product ?? "")}
                    >
                      {action.cta}
                      <ArrowRight className="size-4" aria-hidden />
                    </Button>
                  )}
                </div>
              </Card>
            </StaggerItem>
          );
        })}

        {/* Campaign action */}
        {campaign ? (
          <StaggerItem>
            <Card className="overflow-hidden">
              <div className="bg-brand-strong px-5 py-5 text-white">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[12px] font-semibold uppercase tracking-widest text-white/70">
                      Campaign
                    </p>
                    <h2 className="mt-1 text-[24px] font-bold tracking-tight">
                      {campaign.name}
                    </h2>
                  </div>
                  {isCampaignActive ? (
                    <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-white/15 px-2.5 py-1 text-[12px] font-semibold">
                      <span className="size-1.5 rounded-full bg-white" aria-hidden />
                      Active
                    </span>
                  ) : null}
                </div>

                <div className="mt-5 flex flex-wrap items-baseline gap-x-2">
                  <span className="tnum text-[38px] font-bold leading-none">
                    ₹{campaign.config?.cashback_amount}
                  </span>
                  <span className="text-[15px] font-medium text-white/85">cashback</span>
                </div>
                <p className="mt-2 text-[14px] text-white/85">
                  on orders above ₹{campaign.config?.minimum_transaction},{" "}
                  {campaign.config?.window_label}
                </p>
              </div>

              <dl className="grid grid-cols-3 divide-x divide-border border-b border-border">
                <Facet
                  icon={<Clock className="size-4" aria-hidden />}
                  label="Window"
                  value={campaign.config?.window_label ?? "—"}
                />
                <Facet
                  icon={<Target className="size-4" aria-hidden />}
                  label="Minimum"
                  value={`₹${campaign.config?.minimum_transaction}`}
                />
                <Facet
                  icon={<Users className="size-4" aria-hidden />}
                  label="Audience"
                  value="Returning"
                />
              </dl>

              <div className="p-5">
                <p className="text-[14px] font-semibold">Why this, why now</p>
                <p className="mt-1.5 text-[14px] leading-relaxed text-foreground">
                  {campaign.why_now}
                </p>
                <ul className="mt-3 space-y-2">
                  {campaign.rationale?.map((reason, i) => (
                    <li
                      key={i}
                      className="flex gap-2.5 text-[13px] leading-relaxed text-muted"
                    >
                      <Check
                        className="mt-0.5 size-4 shrink-0 text-positive"
                        strokeWidth={2.4}
                        aria-hidden
                      />
                      {reason}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="border-t border-border px-5 py-4">
                {isCampaignActive ? (
                  <Badge tone="positive">
                    <Check className="size-3.5" aria-hidden />
                    Campaign running
                  </Badge>
                ) : (
                  <>
                    <Button size="lg" className="w-full" onClick={() => setConfirming(true)}>
                      {campaign.cta}
                      <ArrowRight className="size-4" aria-hidden />
                    </Button>
                    {actionError ? (
                      <p className="mt-2 text-center text-[13px] text-negative">
                        {actionError}
                      </p>
                    ) : null}
                  </>
                )}
              </div>
            </Card>
          </StaggerItem>
        ) : null}

        {/* Projected impact */}
        {campaign ? (
          <StaggerItem>
            <ProjectionCard
              projection={launchedProjection ?? campaign.projection}
              revenuePerWeek={campaign.campaign_projection?.revenue_per_week ?? 0}
              costPerWeek={
                campaign.campaign_projection?.estimated_cashback_cost_per_week ?? 0
              }
              lift={campaign.campaign_projection?.evening_transaction_lift_percent ?? 0}
              restockRevenue={
                restockProjection?.recovered_revenue_per_week ??
                restocks[0]?.projection.recovered_revenue_per_week ??
                null
              }
              revealed={isCampaignActive}
            />
          </StaggerItem>
        ) : null}

        {bothDone ? (
          <StaggerItem>
            <Link href="/" className="block">
              <Card className="p-4 transition-colors hover:bg-surface-muted">
                <div className="flex items-center gap-3">
                  <p className="flex-1 text-[14px] font-medium">Back to your dashboard</p>
                  <ArrowRight className="size-4 text-subtle" aria-hidden />
                </div>
              </Card>
            </Link>
          </StaggerItem>
        ) : null}
      </div>

      <AnimatePresence>
        {confirming && campaign ? (
          <ConfirmModal
            action={campaign}
            launching={busy}
            onCancel={() => setConfirming(false)}
            onConfirm={onLaunch}
          />
        ) : null}
      </AnimatePresence>
    </Stagger>
  );
}

function Facet({
  icon,
  label,
  value,
}: {
  icon?: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="px-3 py-3.5 text-center">
      <dt className="flex items-center justify-center gap-1.5 text-[11px] text-subtle">
        {icon}
        {label}
      </dt>
      <dd className="tnum mt-1 text-[13px] font-semibold">{value}</dd>
    </div>
  );
}

function ProjectionCard({
  projection,
  revenuePerWeek,
  costPerWeek,
  lift,
  restockRevenue,
  revealed,
}: {
  projection: ActionProjection;
  revenuePerWeek: number;
  costPerWeek: number;
  lift: number;
  restockRevenue: number | null;
  revealed: boolean;
}) {
  return (
    <Card>
      <CardHeader
        title="Simulated / Projected Impact"
        subtitle="A projection from your own history, not a guarantee"
        icon={<TrendingUp className="size-4" aria-hidden />}
      />

      <div className="grid gap-4 p-5 sm:grid-cols-2">
        <div className="rounded-xl bg-surface-muted p-4">
          <p className="text-[12px] font-medium text-subtle">Business Health Score</p>
          <div className="mt-2 flex items-center gap-3">
            <span
              className="tnum text-[28px] font-bold leading-none"
              style={{ color: scoreColor(projection.current_score) }}
            >
              {projection.current_score}
            </span>
            <ArrowRight className="size-4 text-subtle" aria-hidden />
            <motion.span
              key={revealed ? "revealed" : "idle"}
              className="tnum text-[28px] font-bold leading-none"
              style={{ color: scoreColor(projection.projected_score) }}
              initial={revealed ? { opacity: 0, scale: 0.85 } : false}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ type: "spring", stiffness: 300, damping: 18, delay: 0.15 }}
            >
              {projection.projected_score}
            </motion.span>
            <Badge tone="positive" className="ml-auto">
              +{projection.delta} pts
            </Badge>
          </div>
          <div className="mt-3">
            <ScoreMeter
              score={projection.projected_score}
              color={scoreColor(projection.projected_score)}
            />
          </div>
        </div>

        <div className="rounded-xl bg-surface-muted p-4">
          <p className="text-[12px] font-medium text-subtle">Evening transactions</p>
          <p className="tnum mt-2 text-[28px] font-bold leading-none text-positive">
            +{lift.toFixed(0)}%
          </p>
          <p className="mt-3 text-[12px] leading-relaxed text-muted">
            About {rupees(revenuePerWeek)} of recovered weekly revenue, against roughly{" "}
            {rupees(costPerWeek)} in cashback.
            {restockRevenue
              ? ` Restocking adds about ${rupees(restockRevenue)} a week on top.`
              : null}
          </p>
        </div>
      </div>

      <div className="border-t border-border px-5 py-4">
        <p className="text-[12px] font-semibold text-subtle">Where the points come from</p>
        <ul className="mt-2.5 space-y-2">
          {Object.entries(projection.components_after ?? {})
            .map(([key, after]) => ({
              key,
              after,
              before: projection.components_before?.[key] ?? after,
            }))
            .filter((row) => row.after !== row.before)
            .map((row) => (
              <li key={row.key} className="flex items-center gap-3 text-[13px]">
                <span className="flex-1 capitalize text-muted">
                  {row.key.replace(/_/g, " ")}
                </span>
                <span className="tnum text-subtle">{row.before}</span>
                <ArrowRight className="size-3 text-subtle" aria-hidden />
                <span className="tnum font-semibold text-positive">{row.after}</span>
              </li>
            ))}
        </ul>
      </div>

      <div className="border-t border-border bg-warning-soft/50 px-5 py-4">
        <div className="flex gap-2.5">
          <Info className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <div className="min-w-0">
            <p className="text-[12px] font-semibold text-warning">What this assumes</p>
            <ul className="mt-1.5 space-y-1 text-[12px] leading-relaxed text-muted">
              {(projection.assumptions ?? []).map((assumption) => (
                <li key={assumption}>· {assumption}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </Card>
  );
}

function ConfirmModal({
  action,
  launching,
  onCancel,
  onConfirm,
}: {
  action: MerchantAction;
  launching: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <motion.div
      className="fixed inset-0 z-50 grid place-items-end sm:place-items-center"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
    >
      <button
        type="button"
        aria-label="Cancel"
        className="absolute inset-0 bg-foreground/40 backdrop-blur-[2px]"
        onClick={launching ? undefined : onCancel}
      />
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        className="relative w-full max-w-md rounded-t-3xl bg-surface p-6 shadow-[var(--shadow-lg)] sm:rounded-3xl"
        initial={{ y: 40, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        exit={{ y: 24, opacity: 0 }}
        transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="confirm-title" className="text-[18px] font-bold tracking-tight">
              Launch {action.name}?
            </h2>
            <p className="mt-1 text-[13px] leading-relaxed text-muted">
              This activates the offer across your Paytm storefront and QR immediately.
            </p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            disabled={launching}
            aria-label="Close"
            className="grid size-8 shrink-0 place-items-center rounded-lg text-subtle transition-colors hover:bg-surface-muted disabled:opacity-50"
          >
            <X className="size-4" aria-hidden />
          </button>
        </div>

        <dl className="mt-4 space-y-2 rounded-xl bg-surface-muted p-4 text-[13px]">
          <Row label="Cashback" value={`₹${action.config?.cashback_amount} per qualifying order`} />
          <Row label="Minimum order" value={`₹${action.config?.minimum_transaction}`} />
          <Row label="Active hours" value={action.config?.window_label ?? "—"} />
          <Row label="Audience" value="Customers who have bought before" />
        </dl>

        <div className="mt-5 flex gap-3">
          <Button variant="secondary" className="flex-1" onClick={onCancel} disabled={launching}>
            Cancel
          </Button>
          <Button className="flex-1" onClick={onConfirm} loading={launching}>
            {launching ? "Launching…" : "Confirm & launch"}
          </Button>
        </div>
      </motion.div>
    </motion.div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-semibold">{value}</dd>
    </div>
  );
}

function ActionsSkeleton() {
  return (
    <div className="space-y-4 px-4 pt-6 md:px-0 md:pt-0">
      <Skeleton className="h-7 w-52" />
      <Card>
        <div className="bg-surface-muted p-6">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="mt-3 h-8 w-44" />
        </div>
        <div className="space-y-2 p-5">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
        </div>
      </Card>
      <SkeletonCard lines={4} />
    </div>
  );
}
