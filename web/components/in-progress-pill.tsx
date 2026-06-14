"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { useRunStore } from "@/lib/run-store";

export function InProgressPill() {
  const hydrated = useRunStore((s) => s.hydrated);
  const status = useRunStore((s) => s.status);
  const input = useRunStore((s) => s.input);

  // Do not render until hydration is complete to avoid SSR/CSR mismatch.
  if (!hydrated) return null;
  if (status !== "running" && status !== "pending") return null;

  return (
    <Link
      href="/#live-run"
      aria-label={input ? `Analyzing ${input} — in progress` : "Run in progress"}
      className="inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 transition-colors"
    >
      <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
      <span className="hidden sm:inline">Run in progress</span>
      <span className="sm:hidden">Running</span>
    </Link>
  );
}
