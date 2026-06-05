import type { Tier } from "./types";

export const TIER_META: Record<
  Tier,
  { label: string; color: string; description: string }
> = {
  Strong: {
    label: "Strong",
    color: "var(--tier-strong)",
    description: "Push to first meeting.",
  },
  Promising: {
    label: "Promising",
    color: "var(--tier-promising)",
    description: "Needs targeted diligence.",
  },
  Mixed: {
    label: "Mixed",
    color: "var(--tier-mixed)",
    description: "Major gaps; pass unless thesis-fit.",
  },
  Weak: {
    label: "Weak",
    color: "var(--tier-weak)",
    description: "Pass.",
  },
};

export function tierFromScore(score: number | null | undefined): Tier {
  if (score == null) return "Weak";
  if (score >= 80) return "Strong";
  if (score >= 60) return "Promising";
  if (score >= 40) return "Mixed";
  return "Weak";
}
