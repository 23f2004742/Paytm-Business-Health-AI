"use client";

import { motion } from "framer-motion";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { ReactNode } from "react";

import { cn, percent } from "@/lib/format";
import type { Tone } from "@/types";

/* ------------------------------------------------------------------ Card */

export function Card({
  children,
  className,
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "article";
}) {
  return (
    <Tag
      className={cn(
        "rounded-2xl border border-border bg-surface shadow-[var(--shadow-sm)]",
        className,
      )}
    >
      {children}
    </Tag>
  );
}

export function CardHeader({
  title,
  subtitle,
  action,
  icon,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 pt-5">
      <div className="flex items-start gap-3">
        {icon ? (
          <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand">
            {icon}
          </span>
        ) : null}
        <div>
          <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>
          {subtitle ? (
            <p className="mt-0.5 text-[13px] leading-snug text-muted">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {action}
    </div>
  );
}

/* ------------------------------------------------------------- Delta pill */

const TONE_STYLES: Record<Tone, string> = {
  positive: "bg-positive-soft text-positive",
  negative: "bg-negative-soft text-negative",
  neutral: "bg-surface-muted text-muted",
};

export function DeltaPill({
  value,
  tone,
  suffix = "",
  className,
}: {
  value: number;
  tone: Tone;
  suffix?: string;
  className?: string;
}) {
  const Icon =
    tone === "positive" ? ArrowUpRight : tone === "negative" ? ArrowDownRight : Minus;

  return (
    <span
      className={cn(
        "tnum inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold",
        TONE_STYLES[tone],
        className,
      )}
    >
      <Icon className="size-3.5" strokeWidth={2.5} aria-hidden />
      {percent(value)}
      {suffix}
    </span>
  );
}

/* ----------------------------------------------------------------- Badge */

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: Tone | "brand" | "warning";
  className?: string;
}) {
  const styles: Record<string, string> = {
    ...TONE_STYLES,
    brand: "bg-brand-soft text-brand",
    warning: "bg-warning-soft text-warning",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-semibold",
        styles[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/* ---------------------------------------------------------------- Button */

export function Button({
  children,
  onClick,
  variant = "primary",
  size = "md",
  disabled,
  loading,
  className,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  loading?: boolean;
  className?: string;
  type?: "button" | "submit";
}) {
  const variants = {
    primary:
      "bg-brand text-white hover:bg-brand-strong shadow-[var(--shadow-sm)] disabled:bg-subtle",
    secondary:
      "bg-surface text-foreground border border-border-strong hover:bg-surface-muted",
    ghost: "text-brand hover:bg-brand-soft",
  };
  const sizes = {
    sm: "h-9 px-3 text-[13px]",
    md: "h-11 px-4 text-[14px]",
    lg: "h-13 px-6 text-[15px]",
  };

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-xl font-semibold",
        "transition-colors duration-150 outline-none",
        "focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-70",
        variants[variant],
        sizes[size],
        className,
      )}
    >
      {loading ? (
        <span
          className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent"
          aria-hidden
        />
      ) : null}
      {children}
    </button>
  );
}

/* -------------------------------------------------------------- Skeleton */

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton rounded-lg", className)} aria-hidden />;
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <Card className="p-5">
      <Skeleton className="h-4 w-1/3" />
      <div className="mt-4 space-y-2.5">
        {Array.from({ length: lines }).map((_, i) => (
          <Skeleton key={i} className={cn("h-3", i === lines - 1 ? "w-2/3" : "w-full")} />
        ))}
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------ Empty/error */

export function ErrorState({
  title,
  message,
  hint,
  onRetry,
}: {
  title: string;
  message: string;
  hint?: string;
  onRetry?: () => void;
}) {
  return (
    <Card className="p-6 text-center">
      <div className="mx-auto grid size-11 place-items-center rounded-full bg-warning-soft text-warning">
        <Minus className="size-5" strokeWidth={2.5} aria-hidden />
      </div>
      <h3 className="mt-3 text-[15px] font-semibold">{title}</h3>
      <p className="mx-auto mt-1 max-w-sm text-[13px] leading-relaxed text-muted">
        {message}
      </p>
      {hint ? (
        <p className="mx-auto mt-2 max-w-sm rounded-lg bg-surface-muted px-3 py-2 font-mono text-[12px] text-subtle">
          {hint}
        </p>
      ) : null}
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry} className="mt-4">
          Try again
        </Button>
      ) : null}
    </Card>
  );
}

/* ------------------------------------------------------------- Animation */

export const fadeUp = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.32, ease: [0.22, 1, 0.36, 1] as const },
};

export function Stagger({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      initial="hidden"
      animate="show"
      variants={{
        hidden: {},
        show: { transition: { staggerChildren: 0.06 } },
      }}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      variants={{
        hidden: { opacity: 0, y: 12 },
        show: {
          opacity: 1,
          y: 0,
          transition: { duration: 0.32, ease: [0.22, 1, 0.36, 1] },
        },
      }}
    >
      {children}
    </motion.div>
  );
}
