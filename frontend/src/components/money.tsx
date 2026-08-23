"use client";

/*
  Money in, money stuck, money out.

  The three columns are the product's whole argument, so the design carries it
  rather than leaving it to a tagline. A payments soundbox can draw exactly one
  of these columns. The other two exist only because somebody spoke to the box
  on the counter, and each of those is marked as heard rather than banked.

  Colour is used strictly:
    in     positive   money that arrived
    stuck  warning    money that is owed to you and has not
    out    plain      spending is normal, not a problem, so it is never red

  Money out is deliberately NOT red. A shop that spends nothing is a shop that
  sells nothing, and colouring every expense as a loss would teach the merchant
  to ignore the colour that matters.
*/

import { motion } from "framer-motion";
import { ArrowDownLeft, ArrowUpRight, Mic, Wallet } from "lucide-react";
import type { ReactNode } from "react";

import { Card, DeltaPill } from "@/components/ui";
import { cn, rupees, toneFor } from "@/lib/format";
import type { MoneyFlow } from "@/types";

type Accent = "in" | "stuck" | "out";

const ACCENT: Record<Accent, { color: string; soft: string; ring: string }> = {
  in: { color: "var(--positive)", soft: "var(--positive-soft)", ring: "rgba(15,143,95,0.22)" },
  stuck: { color: "var(--warning)", soft: "var(--warning-soft)", ring: "rgba(178,106,0,0.22)" },
  out: { color: "var(--foreground)", soft: "var(--surface-muted)", ring: "var(--border-strong)" },
};

export function MoneyColumns({ money }: { money: MoneyFlow }) {
  const { money_in, money_stuck, money_out } = money;
  const topCategory = money_out.by_category[0] ?? null;

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <MoneyCard
        accent="in"
        icon={<ArrowDownLeft className="size-[18px]" strokeWidth={2.4} aria-hidden />}
        label="Money in"
        amount={money_in.today}
        source={money_in.source}
        spoken={false}
        footer={
          <div className="flex flex-wrap items-center gap-2">
            <DeltaPill value={money_in.today_change} tone={toneFor(money_in.today_change)} />
            <span className="text-[12px] text-subtle">
              {money_in.transactions_today} sales today
            </span>
          </div>
        }
      />

      <MoneyCard
        accent="stuck"
        icon={<Wallet className="size-[18px]" strokeWidth={2.4} aria-hidden />}
        label="Money stuck"
        amount={money_stuck.outstanding}
        source={money_stuck.source}
        spoken
        footer={
          money_stuck.customers_with_dues ? (
            <p className="text-[12px] leading-relaxed text-muted">
              {money_stuck.customers_with_dues} customer
              {money_stuck.customers_with_dues === 1 ? "" : "s"} owe you.{" "}
              {money_stuck.top_debtors[0] ? (
                <span className="font-medium text-foreground">
                  {money_stuck.top_debtors[0].name} has the most,{" "}
                  {rupees(money_stuck.top_debtors[0].balance)}.
                </span>
              ) : null}
            </p>
          ) : (
            <p className="text-[12px] text-muted">No udhaar pending. Every khata is clear.</p>
          )
        }
      />

      <MoneyCard
        accent="out"
        icon={<ArrowUpRight className="size-[18px]" strokeWidth={2.4} aria-hidden />}
        label="Money out"
        amount={money_out.today}
        source={money_out.source}
        spoken
        footer={
          topCategory ? (
            <p className="text-[12px] leading-relaxed text-muted">
              Mostly{" "}
              <span className="font-medium text-foreground">
                {topCategory.label.toLowerCase()}
              </span>{" "}
              ({rupees(topCategory.amount)}) across {money_out.count} entr
              {money_out.count === 1 ? "y" : "ies"}.
            </p>
          ) : (
            <p className="text-[12px] text-muted">
              Nothing spent yet. Say &ldquo;supplier ko 5000 diye&rdquo; to record one.
            </p>
          )
        }
      />
    </div>
  );
}

function MoneyCard({
  accent,
  icon,
  label,
  amount,
  source,
  spoken,
  footer,
}: {
  accent: Accent;
  icon: ReactNode;
  label: string;
  amount: number;
  source: string;
  /** True when this column exists only because the merchant said it out loud. */
  spoken: boolean;
  footer: ReactNode;
}) {
  const tone = ACCENT[accent];

  return (
    <Card className="flex flex-col overflow-hidden p-0">
      <div className="flex items-center gap-2.5 px-4 pt-4">
        <span
          className="grid size-8 shrink-0 place-items-center rounded-lg"
          style={{ background: tone.soft, color: tone.color }}
        >
          {icon}
        </span>
        <p className="text-[13px] font-semibold tracking-tight">{label}</p>
        {spoken ? (
          <span
            className="ml-auto inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold"
            style={{ background: "var(--brand-soft)", color: "var(--brand)" }}
            title="Your payments app cannot see this. Munim AI heard it."
          >
            <Mic className="size-3" strokeWidth={2.6} aria-hidden />
            heard
          </span>
        ) : null}
      </div>

      <motion.p
        className="tnum px-4 pt-3 text-[27px] font-bold leading-none tracking-tight"
        style={{ color: tone.color }}
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
      >
        {rupees(amount)}
      </motion.p>

      <div className="min-h-[46px] px-4 pt-2.5">{footer}</div>

      <p
        className={cn(
          "mt-auto border-t px-4 py-2 text-[10.5px] font-medium uppercase tracking-wider",
          "border-border text-subtle",
        )}
      >
        {source}
      </p>
    </Card>
  );
}

/**
 * The one-line verdict, plus the money that never arrived.
 *
 * `at_risk` is kept visually separate from the columns above because nobody is
 * holding that money: it is an estimate of demand that walked out, and folding
 * it into a total would quietly turn a forecast into a rupee.
 */
export function MoneyVerdict({ money }: { money: MoneyFlow }) {
  const risk = money.at_risk;
  const net = money.net_today;

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-subtle">
            Today, in one line
          </p>
          <p className="mt-2 text-[15px] font-medium leading-relaxed text-foreground">
            {money.verdict}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-3 sm:flex-col sm:items-end sm:gap-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-subtle">
            Net today
          </p>
          <p
            className="tnum text-[24px] font-bold leading-none tracking-tight"
            style={{ color: net >= 0 ? "var(--positive)" : "var(--negative)" }}
          >
            {net >= 0 ? "+" : "−"}
            {rupees(Math.abs(net))}
          </p>
        </div>
      </div>

      {risk.estimated_lost_revenue ? (
        <div className="border-t border-border bg-surface-muted px-5 py-3">
          <p className="text-[12.5px] leading-relaxed text-muted">
            <span className="font-semibold text-warning">
              About {rupees(risk.estimated_lost_revenue)} never reached the counter
            </span>{" "}
            — {risk.unfulfilled_requests} customers asked for something you did not have.
            An estimate from what was said on the shop floor, so it is not counted in
            any column above.
          </p>
        </div>
      ) : null}
    </Card>
  );
}
