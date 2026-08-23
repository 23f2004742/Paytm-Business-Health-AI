"use client";

import { useCallback, useEffect, useState } from "react";
import { Box, Check, Mic, Radio, Volume2, Wallet, X } from "lucide-react";

import { PageHeader } from "@/components/shell";
import { Badge, Button, Card, CardHeader, Stagger, StaggerItem } from "@/components/ui";
import { api } from "@/lib/api";
import { rupees } from "@/lib/format";
import type { AiBoxActivity, AiBoxSnapshot } from "@/types";

export default function AiBoxPage() {
  const [data, setData] = useState<AiBoxSnapshot | null>(null);
  const [status, setStatus] = useState("OFFLINE");
  const [response, setResponse] = useState<AiBoxActivity | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.aiBoxState();
      setData(next);
      setStatus(next.device.status);
    } catch { /* dashboard can still show its last known state */ }
  }, []);

  useEffect(() => {
    // Polling keeps the demo useful when a Pi or another browser posts events.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function checkConnection() {
    await refresh();
  }

  async function confirm(action: "confirm" | "reject") {
    if (!response) return;
    if (action === "confirm") {
      setResponse(await api.confirmAiBox(response.event_id));
    } else {
      const result = await api.rejectAiBox(response.event_id);
      setResponse({ ...response, requires_confirmation: false, action_taken: false, text_response: result.message });
    }
    await refresh();
  }

  const activity = data?.khata.activity ?? [];
  return (
    <Stagger className="space-y-4">
      <StaggerItem>
        <PageHeader eyebrow="Paytm Vyapaar AI Box" title="The shop has a second set of ears" description="A deliberate push-to-talk companion for conversations, customer credit, and missed demand." />
      </StaggerItem>

      <div className="grid gap-4 px-4 md:grid-cols-[1.25fr_0.75fr] md:px-0">
        <StaggerItem>
          <Card className="overflow-hidden border-brand/20 bg-[#f7fbff]">
            <div className="relative p-6 md:p-9">
              <div className="absolute right-7 top-7 grid size-12 place-items-center rounded-2xl bg-brand text-white shadow-lg"><Box className="size-6" /></div>
              <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-brand">Physical intelligence, now live</p>
              <h2 className="mt-3 max-w-md text-[30px] font-bold leading-tight tracking-tight">Paytm Vyapaar<br />AI Box</h2>
              <div className="mt-7 flex items-center gap-3"><span className={`size-3 rounded-full ${status === "OFFLINE" ? "bg-subtle" : "animate-pulse bg-positive"}`} /><span className="text-[14px] font-bold tracking-wide">{status}</span><Badge tone={status === "OFFLINE" ? "neutral" : "positive"}>{data?.device.demo_mode ? "Demo mode" : "Pi connected"}</Badge></div>
              <div className="mt-8 flex min-h-16 items-end gap-1.5" aria-label="Audio activity"><span className="h-5 w-1.5 rounded-full bg-accent" /><span className="h-10 w-1.5 rounded-full bg-brand" /><span className="h-7 w-1.5 rounded-full bg-accent" /><span className="h-14 w-1.5 rounded-full bg-brand" /><span className="h-8 w-1.5 rounded-full bg-accent" /><span className="h-11 w-1.5 rounded-full bg-brand" /><span className="h-4 w-1.5 rounded-full bg-accent" /></div>
              <p className="mt-4 text-[13px] text-muted">The connected Pi listens in short, deliberate recording windows.</p>
              <div className="mt-6 flex flex-wrap gap-2">
                {status === "OFFLINE" ? <Button size="lg" onClick={() => void checkConnection()}><Radio className="size-4" /> Check Pi connection</Button> : <Button size="lg" onClick={() => void api.aiBoxStatus("LISTENING", "pi-shopfloor-01")}><Mic className="size-4" /> Listen for interaction</Button>}
              </div>
            </div>
          </Card>
        </StaggerItem>

        <StaggerItem>
          <Card className="h-full"><CardHeader title="AI response" subtitle="Text plus browser voice output" icon={<Volume2 className="size-4" />} />
            <div className="p-5 pt-4">{response ? <><p className="text-[16px] font-semibold leading-relaxed">{response.text_response}</p><div className="mt-5 grid grid-cols-2 gap-3 text-[12px]"><div className="rounded-xl bg-surface-muted p-3"><p className="text-subtle">Understood</p><p className="mt-1 font-bold">{response.event_type.replaceAll("_", " ")}</p></div><div className="rounded-xl bg-surface-muted p-3"><p className="text-subtle">Confidence</p><p className="mt-1 font-bold">{Math.round(response.confidence * 100)}%</p></div></div>{response.requires_confirmation ? <><Badge tone="warning" className="mt-4"><X className="size-3.5" /> Confirmation required, no money changed</Badge><div className="mt-4 flex gap-2"><Button size="sm" onClick={() => void confirm("confirm")}><Check className="size-3.5" /> Confirm</Button><Button size="sm" variant="secondary" onClick={() => void confirm("reject")}><X className="size-3.5" /> Reject</Button></div></> : <Badge tone="positive" className="mt-4"><Check className="size-3.5" /> Action completed</Badge>}</> : <p className="py-8 text-[14px] leading-relaxed text-muted">The box will explain what it heard, what changed, and whether your Khata is safe to update.</p>}</div>
          </Card>
        </StaggerItem>
      </div>

      <div className="grid gap-4 px-4 md:grid-cols-[0.9fr_1.1fr] md:px-0">
        <StaggerItem><Card><CardHeader title="Smart Khata" subtitle="Customer credit, kept explicit" icon={<Wallet className="size-4" />} /><div className="grid grid-cols-2 gap-px bg-border p-px"><Metric label="Total outstanding" value={rupees(data?.khata.total_outstanding ?? 0)} /><Metric label="Customers with dues" value={String(data?.khata.customers_with_dues ?? 0)} /></div><div className="divide-y divide-border px-5">{(data?.khata.customers ?? []).map(customer => <div className="flex items-center justify-between py-3" key={customer.customer_id}><span className="font-semibold">{customer.name}</span><span className={customer.balance ? "font-bold text-warning" : "font-semibold text-positive"}>{rupees(customer.balance)} {customer.balance ? "due" : "cleared"}</span></div>)}</div></Card></StaggerItem>
        <StaggerItem><Card><CardHeader title="Live business activity" subtitle="Newest events appear automatically" icon={<Radio className="size-4" />} /><div className="divide-y divide-border">{activity.length ? activity.map(item => <ActivityRow key={item.event_id} item={item} />) : <p className="p-5 text-[14px] text-muted">Turn on the box and run a demo interaction.</p>}</div></Card></StaggerItem>
      </div>

    </Stagger>
  );
}

function Metric({ label, value }: { label: string; value: string }) { return <div className="bg-surface px-5 py-4"><p className="text-[11px] uppercase tracking-wider text-subtle">{label}</p><p className="tnum mt-1 text-[22px] font-bold">{value}</p></div>; }
function ActivityRow({ item }: { item: AiBoxActivity }) { return <article className="p-5"><div className="flex items-center justify-between gap-3"><Badge tone={item.requires_confirmation ? "warning" : item.action_taken ? "positive" : "neutral"}>{item.event_type.replaceAll("_", " ")}</Badge><span className="text-[11px] text-subtle">{new Date(item.timestamp).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span></div><p className="mt-3 text-[13px] text-muted">“{item.transcript}”</p><p className="mt-2 font-semibold">{item.text_response}</p></article>; }