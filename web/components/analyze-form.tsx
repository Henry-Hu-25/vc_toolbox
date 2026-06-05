"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowRight, Sparkles, X } from "lucide-react";
import { Card, CardContent } from "./ui/card";
import { Input } from "./ui/input";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { ProgressStepper } from "./progress-stepper";
import { CostLedger } from "./cost-ledger";
import { isTerminal, useRunStore } from "@/lib/run-store";
import { cn } from "@/lib/utils";

const EXAMPLES = ["Vellum AI", "Cursor", "Perplexity"];

export function AnalyzeForm() {
  const router = useRouter();
  const [value, setValue] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);

  const status = useRunStore((s) => s.status);
  const input = useRunStore((s) => s.input);
  const steps = useRunStore((s) => s.steps);
  const cost = useRunStore((s) => s.cost);
  const warnings = useRunStore((s) => s.warnings);
  const error = useRunStore((s) => s.error);
  const slug = useRunStore((s) => s.slug);
  const startRun = useRunStore((s) => s.startRun);
  const cancelRun = useRunStore((s) => s.cancelRun);
  const reset = useRunStore((s) => s.reset);

  const running = status === "pending" || status === "running";
  const staleSlugRef = React.useRef<string | null>(
    status === "completed" ? slug : null,
  );
  const isStaleCompletion =
    status === "completed" && slug !== null && slug === staleSlugRef.current;
  const showRunPanel =
    running || status === "failed" || (status === "completed" && !isStaleCompletion);

  async function handleSubmit(targetInput?: string) {
    const target = (targetInput ?? value).trim();
    if (!target || running || submitting) return;
    setSubmitting(true);
    try {
      await startRun(target);
    } catch (err) {
      console.error(err);
    } finally {
      setSubmitting(false);
    }
  }

  function handleCancel() {
    void cancelRun();
  }

  function handleReset() {
    reset();
    setValue("");
  }

  React.useEffect(() => {
    if (status === "pending" || status === "running") {
      staleSlugRef.current = null;
    }
  }, [status]);

  React.useEffect(() => {
    if (isStaleCompletion) return;
    if (status === "completed" && slug) {
      const t = setTimeout(() => {
        router.push(`/runs/${slug}`);
      }, 900);
      return () => clearTimeout(t);
    }
  }, [status, slug, router, isStaleCompletion]);

  return (
    <Card className="w-full overflow-hidden">
      <CardContent className="p-0">
        <AnimatePresence mode="wait" initial={false}>
          {!showRunPanel ? (
            <motion.form
              key="form"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.2 }}
              onSubmit={(e) => {
                e.preventDefault();
                void handleSubmit();
              }}
              className="p-6 sm:p-8"
            >
              <label
                htmlFor="company"
                className="text-sm font-medium text-muted-fg"
              >
                Company name, URL, or LinkedIn URL
              </label>
              <div className="mt-2 flex gap-2">
                <Input
                  id="company"
                  autoFocus
                  placeholder="Vellum AI / https://vellum.ai / linkedin.com/company/vellumai"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  disabled={submitting}
                />
                <Button
                  type="submit"
                  size="lg"
                  disabled={!value.trim() || submitting}
                >
                  Analyze
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-muted-fg">
                <Sparkles className="h-3.5 w-3.5" />
                <span>Try:</span>
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    onClick={() => {
                      setValue(ex);
                      void handleSubmit(ex);
                    }}
                    className={cn(
                      "rounded-full border border-border px-2.5 py-1 hover:border-primary hover:text-primary transition-colors",
                      submitting && "opacity-50 pointer-events-none",
                    )}
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </motion.form>
          ) : (
            <motion.div
              key="run"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.2 }}
              className="p-6 sm:p-8 space-y-6"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-wider text-muted-fg">
                    Analyzing
                  </p>
                  <h2 className="text-xl font-semibold mt-1 break-all">
                    {input}
                  </h2>
                </div>
                {running && (
                  <Button variant="ghost" size="sm" onClick={handleCancel}>
                    <X className="h-3.5 w-3.5" />
                    Cancel
                  </Button>
                )}
                {isTerminal(status) && (
                  <Button variant="ghost" size="sm" onClick={handleReset}>
                    New run
                  </Button>
                )}
              </div>

              <ProgressStepper steps={steps} />

              {cost && <CostLedger cost={cost} />}

              {warnings.length > 0 && (
                <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-700 dark:text-amber-300">
                  <p className="font-medium mb-1">
                    {warnings.length} warning{warnings.length === 1 ? "" : "s"}
                  </p>
                  <ul className="space-y-0.5">
                    {warnings.slice(0, 4).map((w, i) => (
                      <li key={i} className="truncate">
                        - {w}
                      </li>
                    ))}
                    {warnings.length > 4 && (
                      <li className="text-muted-fg">
                        +{warnings.length - 4} more...
                      </li>
                    )}
                  </ul>
                </div>
              )}

              {error && (
                <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-3 text-sm text-rose-700 dark:text-rose-300">
                  <p className="font-medium">Run failed</p>
                  <p className="text-xs mt-1 break-all">{error}</p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-3"
                    onClick={handleReset}
                  >
                    Try again
                  </Button>
                </div>
              )}

              {status === "completed" && slug && (
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="flex items-center justify-between rounded-md border border-primary/30 bg-primary/5 p-4"
                >
                  <div>
                    <p className="text-sm font-medium">Report ready</p>
                    <p className="text-xs text-muted-fg">
                      Redirecting to the full report...
                    </p>
                  </div>
                  <Badge variant="primary">opening</Badge>
                </motion.div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </CardContent>
    </Card>
  );
}
