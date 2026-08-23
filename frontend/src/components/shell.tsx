"use client";

/*
  App shell.

  Mobile-first: a bottom tab bar is the primary navigation, exactly as it
  would be inside the Paytm for Business app. On desktop the same routes
  become a left rail so the layout has somewhere to grow.

  The rail carries every route; the phone bar carries five. Seven tabs on a
  360px screen gives each one 51px, which is below the comfortable touch
  target, so the two routes a merchant reaches from inside a page instead
  (Why, from the health card, and AI Box, from the device banner) are left off
  the phone bar rather than shrinking all of them.
*/

import { Activity, Box, HelpCircle, Home, Mic, Target, Wallet } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Route } from "next";

import { cn } from "@/lib/format";
import { useAppData } from "@/components/providers";

const NAV = [
  { href: "/", label: "Overview", icon: Home, phone: true },
  { href: "/money", label: "Money", icon: Wallet, phone: true },
  { href: "/health", label: "Health", icon: Activity, phone: true },
  { href: "/why", label: "Why", icon: HelpCircle, phone: false },
  { href: "/shop", label: "Shop", icon: Mic, phone: true },
  { href: "/ai-box", label: "AI Box", icon: Box, phone: false },
  { href: "/actions", label: "Actions", icon: Target, phone: true },
] satisfies { href: Route; label: string; icon: typeof Home; phone: boolean }[];

const PHONE_NAV = NAV.filter((item) => item.phone);

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { dashboard } = useAppData();

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-6xl md:gap-6 md:px-6">
      {/* Desktop rail */}
      <aside className="sticky top-0 hidden h-dvh w-56 shrink-0 flex-col py-6 md:flex">
        <div className="flex items-center gap-2.5 px-3">
          <span className="grid size-9 place-items-center rounded-xl bg-brand text-[15px] font-bold text-white">
            म
          </span>
          <div className="leading-tight">
            <p className="text-[13px] font-bold tracking-tight">Munim AI</p>
            <p className="text-[11px] text-subtle">Paytm for Business</p>
          </div>
        </div>

        <nav className="mt-7 flex flex-col gap-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 rounded-xl px-3 py-2.5 text-[14px] font-medium transition-colors",
                  active
                    ? "bg-brand-soft text-brand"
                    : "text-muted hover:bg-surface hover:text-foreground",
                )}
              >
                <Icon className="size-[18px]" strokeWidth={2} aria-hidden />
                {label}
              </Link>
            );
          })}
        </nav>

        {dashboard ? (
          <div className="mt-auto rounded-xl border border-border bg-surface p-3">
            <p className="text-[12px] font-semibold">{dashboard.merchant.name}</p>
            <p className="mt-0.5 text-[11px] text-subtle">
              {dashboard.merchant.location}
            </p>
            <p className="mt-2 border-t border-border pt-2 text-[11px] text-subtle">
              AI: {dashboard.ai_provider.label}
            </p>
          </div>
        ) : null}
      </aside>

      {/* Content */}
      <main className="min-w-0 flex-1 pb-24 md:py-6 md:pb-10">{children}</main>

      {/* Mobile tab bar */}
      <nav
        className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface/95 backdrop-blur md:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <div className="mx-auto flex max-w-lg items-stretch justify-between px-1">
          {PHONE_NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex flex-1 flex-col items-center gap-1 px-1 py-2.5 text-[10px] font-medium transition-colors",
                  active ? "text-brand" : "text-subtle",
                )}
              >
                <Icon className="size-[20px]" strokeWidth={active ? 2.4 : 1.9} aria-hidden />
                {label}
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-3 px-4 pt-6 md:px-0 md:pt-0">
      <div>
        {eyebrow ? (
          <p className="text-[12px] font-semibold uppercase tracking-wider text-brand">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="mt-1 text-[22px] font-bold tracking-tight md:text-[26px]">{title}</h1>
        {description ? (
          <p className="mt-1 max-w-xl text-[14px] leading-relaxed text-muted">{description}</p>
        ) : null}
      </div>
      {action}
    </header>
  );
}
