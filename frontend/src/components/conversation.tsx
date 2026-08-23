"use client";

/*
  The buyer -> seller -> outcome chain.

  Shared by the Shop Intelligence feed and the root-cause page, because both
  need to show the same thing: the exchange that produced a number, with the
  roles the system read and how sure it is of each one.

  Roles are shown with their confidence deliberately. A merchant who can see
  that the system was 95% sure who was speaking will trust the outcome; one
  who is shown a bare label has to take it on faith.
*/

import { motion } from "framer-motion";
import { CheckCircle2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui";
import type { Interaction } from "@/types";

export function ConversationTimeline({ interaction }: { interaction: Interaction }) {
  const outcomeTone =
    interaction.interaction_outcome === "fulfilled"
      ? "positive"
      : interaction.interaction_outcome === "unfulfilled"
        ? "negative"
        : "warning";

  return (
    <div className="space-y-2.5">
      {interaction.conversation.map((turn, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, x: turn.speaker === "buyer" ? -8 : 8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: i * 0.08, duration: 0.3 }}
          className={turn.speaker === "seller" ? "flex justify-end" : "flex"}
        >
          <div
            className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 ${
              turn.speaker === "buyer"
                ? "rounded-tl-sm bg-surface-muted"
                : turn.speaker === "seller"
                  ? "rounded-tr-sm bg-brand-soft"
                  : "bg-warning-soft/60"
            }`}
          >
            <div className="flex items-center gap-1.5">
              <span
                className="text-[10px] font-bold uppercase tracking-wider"
                style={{
                  color:
                    turn.speaker === "buyer"
                      ? "var(--muted)"
                      : turn.speaker === "seller"
                        ? "var(--brand)"
                        : "var(--warning)",
                }}
              >
                {turn.speaker}
              </span>
              <span className="text-[10px] text-subtle">
                {Math.round(turn.confidence * 100)}%
              </span>
            </div>
            <p className="mt-0.5 text-[14px] leading-snug text-foreground">
              &ldquo;{turn.text}&rdquo;
            </p>
            {turn.intent || turn.response ? (
              <p className="mt-1 text-[11px] text-subtle">
                {(turn.intent ?? turn.response ?? "").replace(/_/g, " ")}
                {turn.quantity ? ` · qty ${turn.quantity}` : ""}
                {turn.price ? ` · ₹${turn.price}` : ""}
              </p>
            ) : null}
          </div>
        </motion.div>
      ))}

      <div className="flex items-center gap-2 pt-2">
        {interaction.interaction_outcome === "fulfilled" ? (
          <CheckCircle2 className="size-4 text-positive" aria-hidden />
        ) : (
          <XCircle className="size-4 text-negative" aria-hidden />
        )}
        <Badge tone={outcomeTone as "positive" | "negative" | "warning"}>
          {interaction.interaction_outcome.replace(/_/g, " ")}
        </Badge>
        {interaction.potential_lost_sale ? (
          <span className="text-[12px] font-medium text-negative">
            Potential lost sale
          </span>
        ) : null}
        {interaction.expects_transaction ? (
          <span className="text-[12px] text-muted">Transaction expected</span>
        ) : null}
      </div>

      {interaction.reasoning.length ? (
        <p className="pt-1 text-[11px] leading-relaxed text-subtle">
          {interaction.reasoning[0]}
        </p>
      ) : null}
    </div>
  );
}

