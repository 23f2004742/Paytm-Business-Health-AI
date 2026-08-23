"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";

import { ScoreMeter, ScoreRing } from "@/components/charts";
import { useAppData } from "@/components/providers";
import { PageHeader } from "@/components/shell";
import {
  Badge,
  Card,
  DeltaPill,
  ErrorState,
  Skeleton,
  Stagger,
  StaggerItem,
} from "@/components/ui";
import { cn, scoreColor, toneFor } from "@/lib/format";
import type { ComponentDetail, Tone } from "@/types";

export default function HealthPage() {
  const { dashboard, loading, error, reload } = useAppData();
  const [open, setOpen] = useState<string | null>(null);

  if (error) {
    return (
      <div className="px-4 pt-6 md:px-0">
        <ErrorState
          title="Can't load your health breakdown"
          message={error.message}
          hint={error.hint}
          onRetry={() => void reload()}
        />
      </div>
    );
  }

  if (loading || !dashboard) return <HealthSkeleton />;

  const { health } = dashboard;
  const color = scoreColor(health.overall_score);

  return (
    <Stagger className="space-y-4">
      <StaggerItem>
        <PageHeader
          eyebrow="Business Health"
          title="How your score is built"
          description="Five components, each measured against your own recent trading history."
        />
      </StaggerItem>

      <div className="space-y-4 px-4 md:px-0">
        <StaggerItem>
          <Card className="flex flex-col items-center gap-5 p-6 sm:flex-row">
            <ScoreRing score={health.overall_score} size={136} stroke={11} color={color}>
              <div className="text-center">
                <p className="tnum text-[32px] font-bold leading-none" style={{ color }}>
                  {health.overall_score}
                </p>
                <p className="text-[11px] text-subtle">/ 100</p>
              </div>
            </ScoreRing>
            <div className="flex-1 text-center sm:text-left">
              <div className="flex flex-wrap items-center justify-center gap-2 sm:justify-start">
                <Badge tone={health.overall_score >= 80 ? "positive" : "brand"}>
                  {health.status}
                </Badge>
                <DeltaPill
                  value={health.change}
                  tone={toneFor(health.change)}
                  suffix=" pts"
                />
              </div>
              <p className="mt-3 text-[14px] leading-relaxed text-muted">
                Each component is scored 0&ndash;100, then weighted. Tap any row to see
                what moved it.
              </p>
              <div className="mt-3 flex flex-wrap justify-center gap-1.5 sm:justify-start">
                {health.status_bands
                  .slice()
                  .reverse()
                  .map((band) => (
                    <span
                      key={band.label}
                      className={cn(
                        "rounded-md px-2 py-1 text-[11px] font-medium",
                        health.status === band.label
                          ? "bg-brand text-white"
                          : "bg-surface-muted text-subtle",
                      )}
                    >
                      {band.label} {band.min}+
                    </span>
                  ))}
              </div>
            </div>
          </Card>
        </StaggerItem>

        {health.component_detail.map((component) => (
          <StaggerItem key={component.key}>
            <ComponentRow
              component={component}
              expanded={open === component.key}
              onToggle={() => setOpen(open === component.key ? null : component.key)}
            />
          </StaggerItem>
        ))}

        <StaggerItem>
          <p className="px-1 pb-2 text-[12px] leading-relaxed text-subtle">
            Scores are calculated directly from your transactions, so the same inputs always
            produce the same score. Declines are weighted more heavily than equivalent
            gains, so a developing problem shows up early.
          </p>
        </StaggerItem>
      </div>
    </Stagger>
  );
}

function ComponentRow({
  component,
  expanded,
  onToggle,
}: {
  component: ComponentDetail;
  expanded: boolean;
  onToggle: () => void;
}) {
  const color = scoreColor(component.score);

  return (
    <Card>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="w-full rounded-2xl px-5 py-4 text-left outline-none focus-visible:ring-2 focus-visible:ring-brand"
      >
        <div className="flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-3">
              <p className="text-[14px] font-semibold">{component.label}</p>
              <p className="tnum text-[15px] font-bold" style={{ color }}>
                {component.score}
                <span className="text-[12px] font-medium text-subtle">/100</span>
              </p>
            </div>
            <div className="mt-2.5">
              <ScoreMeter score={component.score} color={color} />
            </div>
            <div className="mt-2 flex items-center justify-between gap-2">
              <p className="text-[11px] text-subtle">
                {Math.round(component.weight * 100)}% of your score ·{" "}
                {component.weighted_points} pts contributed
              </p>
              <ChevronDown
                className={cn(
                  "size-4 shrink-0 text-subtle transition-transform duration-200",
                  expanded && "rotate-180",
                )}
                aria-hidden
              />
            </div>
          </div>
        </div>
      </button>

      {expanded ? (
        <div className="border-t border-border px-5 py-4">
          <p className="text-[13px] leading-relaxed text-foreground">{component.summary}</p>
          <dl className="mt-3 grid gap-2 sm:grid-cols-3">
            {component.drivers.map((driver) => (
              <div key={driver.label} className="rounded-xl bg-surface-muted px-3 py-2.5">
                <dt className="text-[11px] text-subtle">{driver.label}</dt>
                <dd
                  className={cn(
                    "tnum mt-0.5 text-[14px] font-semibold",
                    driver.tone === "positive" && "text-positive",
                    driver.tone === "negative" && "text-negative",
                    driver.tone === "neutral" && "text-foreground",
                  )}
                >
                  {driver.value}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
    </Card>
  );
}

function HealthSkeleton() {
  return (
    <div className="space-y-4 px-4 pt-6 md:px-0 md:pt-0">
      <Skeleton className="h-7 w-56" />
      <Card className="flex items-center gap-5 p-6">
        <Skeleton className="size-[136px] rounded-full" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      </Card>
      {Array.from({ length: 5 }).map((_, i) => (
        <Card key={i} className="p-5">
          <div className="flex justify-between">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-4 w-12" />
          </div>
          <Skeleton className="mt-3 h-2 w-full rounded-full" />
          <Skeleton className="mt-3 h-3 w-40" />
        </Card>
      ))}
    </div>
  );
}

export type { Tone };
