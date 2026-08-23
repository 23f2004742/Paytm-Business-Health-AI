import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const inr = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 0,
});

/** ₹18,420. Indian digit grouping, no decimals. */
export function rupees(value: number): string {
  return `₹${inr.format(Math.round(value))}`;
}

/** Compact form for chart axes: ₹18.4k */
export function rupeesCompact(value: number): string {
  if (Math.abs(value) >= 100000) return `₹${(value / 100000).toFixed(1)}L`;
  if (Math.abs(value) >= 1000) return `₹${(value / 1000).toFixed(1)}k`;
  return `₹${Math.round(value)}`;
}

export function percent(value: number, digits = 1): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function absPercent(value: number, digits = 0): string {
  return `${Math.abs(value).toFixed(digits)}%`;
}

export function number(value: number): string {
  return inr.format(value);
}

/**
 * Direction of a change, from the merchant's point of view.
 * Small movements read as flat so noise doesn't get coloured as signal.
 */
export function toneFor(value: number, goodWhenPositive = true): "positive" | "negative" | "neutral" {
  if (Math.abs(value) < 1) return "neutral";
  const good = goodWhenPositive ? value > 0 : value < 0;
  return good ? "positive" : "negative";
}

export function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export function scoreColor(score: number): string {
  if (score >= 80) return "var(--positive)";
  if (score >= 65) return "var(--brand)";
  if (score >= 40) return "var(--warning)";
  return "var(--negative)";
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
  });
}
