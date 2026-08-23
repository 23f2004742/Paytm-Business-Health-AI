"use client";

import { motion } from "framer-motion";
import { ArrowUp, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useAppData } from "@/components/providers";
import { PageHeader } from "@/components/shell";
import { Card, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/format";

interface Turn {
  id: number;
  role: "user" | "ai";
  text: string;
  provider?: string;
  pending?: boolean;
  failed?: boolean;
}

const SUGGESTIONS = [
  "Why did my score drop?",
  "What is hurting my business?",
  "What is doing well?",
  "How can I improve?",
  "Tell me about my customers",
];

export default function ChatPage() {
  const { dashboard } = useAppData();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(0);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  async function send(question: string) {
    const text = question.trim();
    if (!text || busy) return;

    const userId = nextId.current++;
    const aiId = nextId.current++;

    setTurns((prev) => [
      ...prev,
      { id: userId, role: "user", text },
      { id: aiId, role: "ai", text: "", pending: true },
    ]);
    setDraft("");
    setBusy(true);

    try {
      const result = await api.ask(text);
      setTurns((prev) =>
        prev.map((turn) =>
          turn.id === aiId
            ? { ...turn, text: result.answer, provider: result.provider, pending: false }
            : turn,
        ),
      );
    } catch {
      setTurns((prev) =>
        prev.map((turn) =>
          turn.id === aiId
            ? {
                ...turn,
                pending: false,
                failed: true,
                text: "I couldn't reach the analysis service. Check that the backend is running and try again.",
              }
            : turn,
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-dvh flex-col md:min-h-0">
      <PageHeader
        eyebrow="Paytm Business AI"
        title="Ask about your business"
        description={
          dashboard
            ? `Answers come from ${dashboard.merchant.name}'s own transaction data, never invented figures.`
            : undefined
        }
      />

      <div className="flex-1 space-y-4 px-4 py-5 md:px-0">
        {turns.length === 0 ? (
          <Card className="p-5">
            <div className="flex items-start gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-brand text-white">
                <Sparkles className="size-4.5" strokeWidth={2.2} aria-hidden />
              </span>
              <div className="min-w-0">
                <p className="text-[14px] font-semibold">
                  Ask me anything about how your shop is doing
                </p>
                <p className="mt-1 text-[13px] leading-relaxed text-muted">
                  I read your last five months of transactions. I&rsquo;ll only quote
                  figures I can actually see in the data.
                </p>
              </div>
            </div>
          </Card>
        ) : null}

        {turns.map((turn) =>
          turn.role === "user" ? (
            <motion.div
              key={turn.id}
              className="flex justify-end"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.24 }}
            >
              <p className="max-w-[85%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-[14px] font-medium text-white">
                {turn.text}
              </p>
            </motion.div>
          ) : (
            <motion.div
              key={turn.id}
              className="flex justify-start"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.24 }}
            >
              <div className="max-w-[92%] rounded-2xl rounded-bl-md border border-border bg-surface px-4 py-3 shadow-[var(--shadow-sm)]">
                {turn.pending ? (
                  <div className="space-y-2 py-0.5" role="status" aria-live="polite">
                    <span className="sr-only">Analysing…</span>
                    <Skeleton className="h-3 w-52" />
                    <Skeleton className="h-3 w-40" />
                  </div>
                ) : (
                  <>
                    <div className="space-y-2.5">
                      {turn.text.split("\n\n").map((para, i) => (
                        <p
                          key={i}
                          className={cn(
                            "text-[14px] leading-relaxed",
                            turn.failed ? "text-negative" : "text-foreground",
                            para.trimStart().startsWith("-") && "whitespace-pre-line text-muted",
                          )}
                        >
                          {para}
                        </p>
                      ))}
                    </div>
                    {turn.provider ? (
                      <p className="mt-2.5 border-t border-border pt-2 text-[11px] text-subtle">
                        {turn.provider === "deterministic"
                          ? "Answered by the built-in insight engine"
                          : `Answered by ${turn.provider}`}
                      </p>
                    ) : null}
                  </>
                )}
              </div>
            </motion.div>
          ),
        )}
        <div ref={endRef} />
      </div>

      {/* Composer */}
      <div className="sticky bottom-16 z-30 border-t border-border bg-background/95 px-4 py-3 backdrop-blur md:bottom-0 md:px-0">
        <div className="mb-2.5 flex gap-2 overflow-x-auto pb-1">
          {SUGGESTIONS.map((question) => (
            <button
              key={question}
              type="button"
              onClick={() => void send(question)}
              disabled={busy}
              className="shrink-0 rounded-full border border-border bg-surface px-3 py-1.5 text-[12px] font-medium text-muted transition-colors hover:border-brand hover:text-brand disabled:opacity-50"
            >
              {question}
            </button>
          ))}
        </div>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            void send(draft);
          }}
          className="flex items-center gap-2 rounded-2xl border border-border bg-surface p-1.5 shadow-[var(--shadow-sm)] focus-within:border-brand"
        >
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask about your revenue, customers, or timing…"
            aria-label="Ask a question about your business"
            className="min-w-0 flex-1 bg-transparent px-3 py-2 text-[14px] outline-none placeholder:text-subtle"
          />
          <button
            type="submit"
            disabled={busy || !draft.trim()}
            aria-label="Send question"
            className="grid size-9 shrink-0 place-items-center rounded-xl bg-brand text-white transition-colors hover:bg-brand-strong disabled:bg-subtle"
          >
            <ArrowUp className="size-4" strokeWidth={2.5} aria-hidden />
          </button>
        </form>
      </div>
    </div>
  );
}
