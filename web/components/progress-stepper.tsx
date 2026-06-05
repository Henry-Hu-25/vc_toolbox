"use client";

import { motion, AnimatePresence } from "framer-motion";
import { Check, Loader2, Circle, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

export type StepState = "pending" | "running" | "done" | "warning";

export interface Step {
  id: string;
  label: string;
  state: StepState;
  detail?: string;
}

export function ProgressStepper({ steps }: { steps: Step[] }) {
  return (
    <ol className="relative space-y-3" aria-live="polite">
      {steps.map((step, idx) => {
        const isLast = idx === steps.length - 1;
        return (
          <li key={step.id} className="flex gap-4">
            <div className="flex flex-col items-center">
              <StepIcon state={step.state} />
              {!isLast && (
                <div
                  className={cn(
                    "w-px flex-1 mt-1",
                    step.state === "done" ? "bg-primary/40" : "bg-border",
                  )}
                  style={{ minHeight: 24 }}
                />
              )}
            </div>
            <div className="flex-1 pb-3">
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "text-sm font-medium",
                    step.state === "pending"
                      ? "text-muted-fg"
                      : step.state === "warning"
                        ? "text-amber-500"
                        : "text-fg",
                  )}
                >
                  {step.label}
                </span>
                {step.state === "running" && (
                  <span className="text-xs text-muted-fg">Working...</span>
                )}
              </div>
              <AnimatePresence>
                {step.detail && (
                  <motion.p
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    className="text-xs text-muted-fg mt-1"
                  >
                    {step.detail}
                  </motion.p>
                )}
              </AnimatePresence>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function StepIcon({ state }: { state: StepState }) {
  if (state === "done") {
    return (
      <motion.div
        initial={{ scale: 0.6, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
        className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-fg"
      >
        <Check className="h-3.5 w-3.5" />
      </motion.div>
    );
  }
  if (state === "running") {
    return (
      <div className="flex h-6 w-6 items-center justify-center rounded-full border border-primary text-primary">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      </div>
    );
  }
  if (state === "warning") {
    return (
      <div className="flex h-6 w-6 items-center justify-center rounded-full bg-amber-500 text-white">
        <AlertTriangle className="h-3.5 w-3.5" />
      </div>
    );
  }
  return (
    <div className="flex h-6 w-6 items-center justify-center rounded-full border border-border text-muted-fg">
      <Circle className="h-3 w-3" />
    </div>
  );
}
