import { TIER_META } from "@/lib/tier";
import type { Tier } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ShieldAlert, ShieldCheck, ShieldQuestion, ShieldX } from "lucide-react";

const ICONS: Record<Tier, React.ComponentType<{ className?: string }>> = {
  Strong: ShieldCheck,
  Promising: ShieldQuestion,
  Mixed: ShieldAlert,
  Weak: ShieldX,
};

export function TierBadge({
  tier,
  size = "md",
  className,
}: {
  tier: Tier;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const meta = TIER_META[tier];
  const Icon = ICONS[tier];
  const sizeCls =
    size === "sm"
      ? "text-xs px-2 py-0.5 gap-1"
      : size === "lg"
        ? "text-sm px-3 py-1.5 gap-2"
        : "text-xs px-2.5 py-1 gap-1.5";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full font-medium",
        sizeCls,
        className,
      )}
      style={{
        backgroundColor: `hsl(${meta.color} / 0.12)`,
        color: `hsl(${meta.color})`,
      }}
      title={meta.description}
    >
      <Icon className={size === "lg" ? "h-4 w-4" : "h-3.5 w-3.5"} />
      {meta.label}
    </span>
  );
}
