import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(num: number): string {
  if (num >= 1000000) {
    return (num / 1000000).toFixed(1) + "M";
  }
  if (num >= 1000) {
    return (num / 1000).toFixed(1) + "K";
  }
  return num.toFixed(0);
}

export function formatLatency(ns: number): string {
  if (ns >= 1000000) {
    return (ns / 1000000).toFixed(2) + "ms";
  }
  if (ns >= 1000) {
    return (ns / 1000).toFixed(2) + "µs";
  }
  return ns.toFixed(0) + "ns";
}
