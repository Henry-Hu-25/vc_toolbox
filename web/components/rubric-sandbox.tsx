"use client";

import * as React from "react";
import { RotateCcw } from "lucide-react";
import { getRubric } from "@/lib/api";
import { tierFromScore } from "@/lib/tier";
import type { CriterionScore, RubricCriterion } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { TierBadge } from "@/components/tier-badge";

const SLIDER_MAX = 40;

/** Mirrors scoring.py::compute_overall — weighted average of clamped 0-5
 *  scores, renormalized by the weight actually used so a zeroed-out criterion
 *  does not drag the total down. */
function computeOverall(
  criteria: CriterionScore[],
  weights: Record<string, number>,
): number {
  let total = 0;
  let usedWeight = 0;
  for (const c of criteria) {
    const weight = weights[c.key] ?? 0;
    if (weight <= 0) continue;
    const clamped = Math.max(0, Math.min(5, Math.trunc(c.score)));
    total += weight * (clamped / 5);
    usedWeight += weight;
  }
  if (usedWeight <= 0) return 0;
  return Math.round((total / usedWeight) * 1000) / 10;
}

export function RubricSandbox({
  criteria,
  houseOverall,
}: {
  criteria: CriterionScore[];
  houseOverall: number;
}) {
  const [rubric, setRubric] = React.useState<RubricCriterion[] | null>(null);
  const [weights, setWeights] = React.useState<Record<string, number> | null>(
    null,
  );

  React.useEffect(() => {
    let cancelled = false;
    getRubric()
      .then((r) => {
        if (!cancelled) setRubric(r.criteria);
      })
      // Fall back to the weights carried on the report itself.
      .catch(() => {
        if (!cancelled) setRubric([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const defaults = React.useMemo(() => {
    const houseByKey = new Map((rubric ?? []).map((c) => [c.key, c.weight]));
    const out: Record<string, number> = {};
    for (const c of criteria) {
      out[c.key] = Math.round((houseByKey.get(c.key) ?? c.weight) * 100);
    }
    return out;
  }, [rubric, criteria]);

  React.useEffect(() => {
    setWeights(defaults);
  }, [defaults]);

  const anchorsByKey = React.useMemo(
    () => new Map((rubric ?? []).map((c) => [c.key, c])),
    [rubric],
  );

  if (criteria.length === 0) return null;

  const active = weights ?? defaults;
  const isDefault = criteria.every((c) => active[c.key] === defaults[c.key]);
  const totalWeight = criteria.reduce(
    (sum, c) => sum + Math.max(0, active[c.key] ?? 0),
    0,
  );
  // At the house weighting, show the report's own number so this panel can
  // never disagree with the headline gauge over a rounding step.
  const overall = isDefault ? houseOverall : computeOverall(criteria, active);
  const delta = Math.round((overall - houseOverall) * 10) / 10;

  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-medium">Weight sandbox</h3>
          <p className="text-xs text-muted-fg mt-1 max-w-md leading-relaxed">
            Reweight the rubric to your thesis. The per-criterion scores stay
            fixed; only the weighting changes. Nothing is saved.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="flex items-baseline gap-1.5 justify-end">
              <span className="text-2xl font-semibold tabular-nums">
                {totalWeight <= 0 ? "—" : overall.toFixed(1)}
              </span>
              {totalWeight > 0 && delta !== 0 && (
                <span
                  className={`text-xs font-mono ${
                    delta > 0 ? "text-tier-strong" : "text-tier-weak"
                  }`}
                >
                  {delta > 0 ? "+" : ""}
                  {delta.toFixed(1)}
                </span>
              )}
            </div>
            {totalWeight > 0 && (
              <div className="mt-1 flex justify-end">
                <TierBadge tier={tierFromScore(overall)} size="sm" />
              </div>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={isDefault}
            onClick={() => setWeights(defaults)}
          >
            <RotateCcw className="h-3.5 w-3.5" /> House rubric
          </Button>
        </div>
      </div>

      {totalWeight <= 0 && (
        <p className="mt-4 text-xs text-tier-mixed">
          Give at least one criterion a non-zero weight to get a score.
        </p>
      )}

      <div className="mt-5 space-y-3">
        {criteria.map((c) => {
          const weight = Math.max(0, active[c.key] ?? 0);
          const share = totalWeight > 0 ? weight / totalWeight : 0;
          const anchors = anchorsByKey.get(c.key);
          return (
            <div
              key={c.key}
              className="grid grid-cols-[minmax(0,1fr)_auto] sm:grid-cols-[minmax(0,11rem)_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1"
            >
              <span
                className="text-sm truncate"
                title={
                  anchors
                    ? `0: ${anchors.anchor_0}\n3: ${anchors.anchor_3}\n5: ${anchors.anchor_5}`
                    : undefined
                }
              >
                {c.label}
                <span className="text-muted-fg font-mono text-xs ml-1.5">
                  {c.score}/5
                </span>
              </span>
              <input
                type="range"
                min={0}
                max={SLIDER_MAX}
                step={1}
                value={weight}
                aria-label={`${c.label} weight`}
                onChange={(e) =>
                  setWeights({
                    ...active,
                    [c.key]: Number(e.currentTarget.value),
                  })
                }
                className="col-span-2 sm:col-span-1 order-last sm:order-none w-full accent-primary"
              />
              <span className="text-xs font-mono text-muted-fg tabular-nums w-10 text-right">
                {totalWeight > 0 ? `${Math.round(share * 100)}%` : "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
