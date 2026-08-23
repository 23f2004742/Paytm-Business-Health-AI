"use client";

/*
  The money detail: the three columns, then the two books behind them.

  The expense book needs a typed way in as well as a spoken one. Voice is the
  real interface on a shop floor, but a merchant reconciling at closing time is
  sitting down with a phone, and a spend recorded wrong is worse than a spend
  not recorded at all. Every row keeps the sentence it came from, so a number
  can always be traced back to what was actually said.
*/

import { useCallback, useEffect, useState } from "react";
import { ArrowUpRight, Check, Loader2, Plus, Send, Wallet } from "lucide-react";

import { MoneyColumns, MoneyVerdict } from "@/components/money";
import { useAppData } from "@/components/providers";
import { PageHeader } from "@/components/shell";
import { VoiceCommand } from "@/components/voice-command";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ErrorState,
  SkeletonCard,
  Stagger,
  StaggerItem,
} from "@/components/ui";
import { api } from "@/lib/api";
import { rupees } from "@/lib/format";
import type { CategoryTotal, CollectionsSnapshot, Expense } from "@/types";

export default function MoneyPage() {
  const { dashboard, loading, error, reload } = useAppData();

  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [categories, setCategories] = useState<{ key: string; label: string }[]>([]);
  const [byCategory, setByCategory] = useState<CategoryTotal[]>([]);

  const refreshExpenses = useCallback(async () => {
    try {
      const payload = await api.expenses();
      setExpenses(payload.expenses);
      setCategories(payload.categories);
      setByCategory(payload.totals.by_category);
    } catch {
      /* The columns above still render from the dashboard payload. */
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshExpenses();
  }, [refreshExpenses]);

  const refreshAll = useCallback(async () => {
    await Promise.all([reload(), refreshExpenses()]);
  }, [reload, refreshExpenses]);

  if (error) {
    return (
      <div className="px-4 pt-6 md:px-0">
        <ErrorState
          title="Can't load your books"
          message={error.message}
          hint={error.hint}
          onRetry={() => void reload()}
        />
      </div>
    );
  }

  if (loading || !dashboard) {
    return (
      <div className="space-y-4 px-4 pt-6 md:px-0 md:pt-0">
        <SkeletonCard lines={3} />
        <SkeletonCard lines={6} />
      </div>
    );
  }

  const money = dashboard.money;

  return (
    <Stagger className="space-y-4 md:pt-0">
      <StaggerItem>
        <PageHeader
          eyebrow="Munim AI"
          title="Your money"
          description="In, stuck, and out. Two of these three columns exist only because you said them out loud."
        />
      </StaggerItem>

      <div className="space-y-4 px-4 md:px-0">
        <StaggerItem>
          <VoiceCommand onAction={() => void refreshAll()} />
        </StaggerItem>

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

        <StaggerItem>
          <div className="grid gap-4 lg:grid-cols-2">
            <ExpenseBook
              expenses={expenses}
              categories={categories}
              byCategory={byCategory}
              onRecorded={() => void refreshAll()}
            />

            <UdhaarBook onChanged={() => void refreshAll()} />
          </div>
        </StaggerItem>
      </div>
    </Stagger>
  );
}

/**
 * A stored expense carries a category key, not a label. The keys come back
 * with the list, so resolve against those rather than hard-coding a second
 * copy of the names the backend already owns.
 */
function labelFor(
  category: string,
  categories: { key: string; label: string }[],
): string {
  return categories.find((item) => item.key === category)?.label ?? "Spend";
}

function ExpenseBook({
  expenses,
  categories,
  byCategory,
  onRecorded,
}: {
  expenses: Expense[];
  categories: { key: string; label: string }[];
  byCategory: CategoryTotal[];
  onRecorded: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [category, setCategory] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function submit() {
    const value = Number(amount);
    if (!Number.isFinite(value) || value <= 0 || !note.trim()) {
      setProblem("An amount above zero and a short note are both needed.");
      return;
    }

    setBusy(true);
    setProblem(null);
    try {
      await api.recordExpense({
        amount: value,
        note: note.trim(),
        category: category || undefined,
      });
      setAmount("");
      setNote("");
      setCategory("");
      setOpen(false);
      onRecorded();
    } catch {
      setProblem("Could not record that spend.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Kharcha book"
        subtitle="What left the shop, and where it went"
        icon={<ArrowUpRight className="size-4" aria-hidden />}
        action={
          <Button size="sm" variant="secondary" onClick={() => setOpen((v) => !v)}>
            <Plus className="size-3.5" aria-hidden />
            Add
          </Button>
        }
      />

      {open ? (
        <div className="mx-5 mt-4 rounded-xl border border-border bg-surface-muted p-3.5">
          <div className="flex flex-wrap gap-2">
            <input
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              inputMode="decimal"
              placeholder="Amount"
              aria-label="Amount spent"
              className="h-10 w-28 rounded-lg border border-border bg-surface px-3 text-[14px] outline-none focus:border-brand"
            />
            <input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="What was it for?"
              aria-label="What the spend was for"
              className="h-10 min-w-0 flex-1 rounded-lg border border-border bg-surface px-3 text-[14px] outline-none focus:border-brand"
            />
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              aria-label="Category"
              className="h-10 rounded-lg border border-border bg-surface px-2.5 text-[13px] outline-none focus:border-brand"
            >
              <option value="">Work it out from the note</option>
              {categories.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
            <Button size="sm" onClick={() => void submit()} disabled={busy}>
              {busy ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
              Record
            </Button>
          </div>
          {problem ? <p className="mt-2 text-[12px] text-negative">{problem}</p> : null}
        </div>
      ) : null}

      {byCategory.length ? (
        <div className="flex flex-wrap gap-1.5 px-5 pt-4">
          {byCategory.map((row) => (
            <span
              key={row.category}
              className="rounded-full bg-surface-muted px-2.5 py-1 text-[11.5px] text-muted"
            >
              {row.label}{" "}
              <span className="tnum font-semibold text-foreground">
                {rupees(row.amount)}
              </span>
            </span>
          ))}
        </div>
      ) : null}

      {expenses.length ? (
        <ul className="divide-y divide-border px-5 pb-4 pt-3">
          {expenses.slice(0, 8).map((expense) => (
            <li key={expense.expense_id} className="py-3">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[14px] font-semibold">
                  {expense.payee ?? labelFor(expense.category, categories)}
                </span>
                <span className="tnum shrink-0 text-[14px] font-bold">
                  {rupees(expense.amount)}
                </span>
              </div>
              <p className="mt-0.5 truncate text-[12px] text-muted">
                &ldquo;{expense.transcript}&rdquo;
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-5 pb-5 pt-3 text-[13px] leading-relaxed text-muted">
          Nothing recorded yet. Say{" "}
          <span className="font-medium text-foreground">
            &ldquo;supplier ko 5000 diye&rdquo;
          </span>{" "}
          , or add one by hand.
        </p>
      )}
    </Card>
  );
}

/**
 * The udhaar book, with a way to act on it.
 *
 * A list of people who owe you money is a worry. The same list with a button
 * that chases them is a tool, which is the whole point of "money stuck" being
 * a column rather than a statistic.
 */
function UdhaarBook({ onChanged }: { onChanged: () => void }) {
  const [data, setData] = useState<CollectionsSnapshot | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<{ name: string; text: string; ok: boolean } | null>(null);

  const refresh = useCallback(async () => {
    try {
      setData(await api.collections());
    } catch {
      /* the money columns above still render */
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  async function chase(name: string, force = false) {
    setBusy(name);
    setNote(null);
    try {
      const result = await api.remind(name, force);
      setNote({ name, text: `Reminder sent to ${name}.`, ok: true });
      void result;
    } catch (err) {
      // 409 is a deliberate refusal and 502 is a delivery failure. Both carry
      // a reason worth showing: silently doing nothing is the one bad answer.
      const api_err = err as { message?: string; status?: number };
      const detail =
        typeof api_err.message === "string" ? api_err.message : "Could not send.";
      setNote({ name, text: detail, ok: false });
    } finally {
      setBusy(null);
      await refresh();
      onChanged();
    }
  }

  const debtors = data?.outstanding ?? [];

  return (
    <Card>
      <CardHeader
        title="Udhaar book"
        subtitle="Money your customers still owe you"
        icon={<Wallet className="size-4" aria-hidden />}
        action={
          data?.total_outstanding ? (
            <Badge tone="warning" className="shrink-0">
              {rupees(data.total_outstanding)} out
            </Badge>
          ) : (
            <Badge tone="positive" className="shrink-0">
              All clear
            </Badge>
          )
        }
      />

      {debtors.length ? (
        <ul className="divide-y divide-border px-5 pb-2 pt-2">
          {debtors.map((debtor) => (
            <li key={debtor.customer_id} className="py-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[14px] font-semibold">{debtor.name}</p>
                  <p className="mt-0.5 text-[11.5px] text-subtle">
                    {debtor.phone
                      ? `${debtor.language} · reminded ${debtor.reminder_count}×`
                      : "No phone number yet"}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="tnum text-[14px] font-bold text-warning">
                    {rupees(debtor.balance)}
                  </span>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={!debtor.phone || busy === debtor.name}
                    onClick={() => void chase(debtor.name)}
                  >
                    {busy === debtor.name ? (
                      <Loader2 className="size-3.5 animate-spin" aria-hidden />
                    ) : (
                      <Send className="size-3.5" aria-hidden />
                    )}
                    Yaad dilao
                  </Button>
                </div>
              </div>

              {note?.name === debtor.name ? (
                <p
                  className="mt-2 text-[12px] leading-relaxed"
                  style={{ color: note.ok ? "var(--positive)" : "var(--negative)" }}
                >
                  {note.ok ? (
                    <Check className="mr-1 inline size-3.5" aria-hidden />
                  ) : null}
                  {note.text}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-5 pb-5 pt-3 text-[13px] leading-relaxed text-muted">
          Nobody owes you anything right now. Say{" "}
          <span className="font-medium text-foreground">
            &ldquo;Sagar ke khate mein 200 rupaye baaki hain&rdquo;
          </span>{" "}
          to record an udhaar.
        </p>
      )}

      <p className="border-t border-border px-5 py-2.5 text-[11px] leading-relaxed text-subtle">
        Say &ldquo;<span className="font-medium">Sagar ko yaad dilao</span>&rdquo; to chase
        by voice. Each customer is written to in their own language, once per{" "}
        {data?.cooldown_hours ?? 24} hours.
        {data && !data.pay_link_configured
          ? " Set PAYMENT_LINK_BASE in .env to attach a Pay Now link."
          : null}
      </p>
    </Card>
  );
}
