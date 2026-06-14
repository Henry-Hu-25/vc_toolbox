"use client";

import * as React from "react";
import Link from "next/link";
import { X } from "lucide-react";
import { listRuns } from "@/lib/api";
import type { RunSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TierBadge } from "@/components/tier-badge";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { useRunStore } from "@/lib/run-store";

export default function RunsPage() {
  const [items, setItems] = React.useState<RunSummary[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [cancellingId, setCancellingId] = React.useState<string | null>(null);
  const status = useRunStore((s) => s.status);
  const cancelRun = useRunStore((s) => s.cancelRun);
  const prevStatusRef = React.useRef(status);

  const refresh = React.useCallback(() => {
    listRuns()
      .then(setItems)
      .catch((e) => setError((e as Error).message));
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  React.useEffect(() => {
    if (status !== "running" && status !== "pending") return;
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [status, refresh]);

  React.useEffect(() => {
    const prev = prevStatusRef.current;
    if (
      (prev === "running" || prev === "pending") &&
      (status === "completed" || status === "failed" || status === "cancelled")
    ) {
      refresh();
    }
    prevStatusRef.current = status;
  }, [status, refresh]);

  return (
    <div className="min-h-screen flex flex-col">
      <SiteHeader />
      <main className="flex-1">
        <section className="container max-w-4xl py-12">
          <header className="mb-8">
            <h1 className="text-2xl font-semibold tracking-tight">History</h1>
            <p className="text-sm text-muted-fg mt-1">
              All reports persisted to the analyzer&rsquo;s <code className="font-mono text-xs">out/</code> directory.
            </p>
          </header>

          {error && (
            <Card>
              <CardContent className="p-6 text-sm text-rose-500">
                Failed to load history: {error}. Is the API server running?
              </CardContent>
            </Card>
          )}

          {items === null && !error && (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-16 rounded-md" />
              ))}
            </div>
          )}

          {items && items.length === 0 && (
            <Card>
              <CardContent className="p-8 text-center text-sm text-muted-fg">
                No runs yet. Head back to the{" "}
                <Link href="/" className="text-primary hover:underline">
                  home page
                </Link>{" "}
                to start one.
              </CardContent>
            </Card>
          )}

          {items && items.length > 0 && (
            <div className="rounded-lg border border-border bg-card overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-muted text-xs uppercase tracking-wider text-muted-fg">
                  <tr>
                    <th className="text-left px-4 py-3 font-medium">Company</th>
                    <th className="text-left px-4 py-3 font-medium">Tier</th>
                    <th className="text-right px-4 py-3 font-medium">Score</th>
                    <th className="text-right px-4 py-3 font-medium">Generated</th>
                    <th className="text-right px-4 py-3 font-medium">Modified</th>
                    <th className="px-4 py-3 w-20"></th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it) => {
                    const key = it.slug || it.run_id || it.company_name;
                    const inFlight =
                      !it.slug &&
                      (it.status === "running" || it.status === "pending");
                    return (
                      <tr
                        key={key}
                        className="border-t border-border hover:bg-muted/40 transition-colors"
                      >
                        <td className="px-4 py-3">
                          {it.slug ? (
                            <Link
                              href={`/runs/${it.slug}`}
                              className="font-medium hover:underline"
                            >
                              {it.company_name}
                            </Link>
                          ) : (
                            <span className="font-medium">{it.company_name}</span>
                          )}
                          {it.raw_input && (
                            <p className="text-xs text-muted-fg mt-0.5 break-all">
                              {it.raw_input}
                            </p>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {inFlight ? (
                            <span className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-primary">
                              {it.status}
                            </span>
                          ) : it.status && it.status !== "completed" ? (
                            <span className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-fg">
                              {it.status}
                            </span>
                          ) : (
                            it.tier && <TierBadge tier={it.tier} size="sm" />
                          )}
                        </td>
                        <td className="px-4 py-3 text-right font-mono">
                          {it.overall_0_100 != null
                            ? it.overall_0_100.toFixed(1)
                            : "—"}
                        </td>
                        <td className="px-4 py-3 text-right text-xs text-muted-fg font-mono">
                          {formatDate(it.generated_at)}
                        </td>
                        <td className="px-4 py-3 text-right text-xs text-muted-fg font-mono">
                          {formatDate(it.modified_at)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {inFlight && it.run_id && (
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label="Cancel run"
                              disabled={cancellingId === it.run_id}
                              onClick={async () => {
                                setCancellingId(it.run_id!);
                                await cancelRun(it.run_id);
                                refresh();
                                setCancellingId(null);
                              }}
                            >
                              <X className="h-3.5 w-3.5" />
                              Cancel
                            </Button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
      <SiteFooter />
    </div>
  );
}

function formatDate(iso: string | null) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
