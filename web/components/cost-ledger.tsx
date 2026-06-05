import { Coins, Search, FileText, Cpu } from "lucide-react";
import type { CostLedger as Cost } from "@/lib/types";
import { cn } from "@/lib/utils";

export function CostLedger({
  cost,
  className,
}: {
  cost: Cost | null | undefined;
  className?: string;
}) {
  const c = cost ?? {
    llm_calls: 0,
    tavily_searches: 0,
    tavily_extracts: 0,
    http_fetches: 0,
    input_tokens: 0,
    output_tokens: 0,
  };
  return (
    <div
      className={cn(
        "grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono",
        className,
      )}
    >
      <Stat icon={<Cpu className="h-3.5 w-3.5" />} label="LLM" value={c.llm_calls} />
      <Stat
        icon={<Search className="h-3.5 w-3.5" />}
        label="Search"
        value={c.tavily_searches}
      />
      <Stat
        icon={<FileText className="h-3.5 w-3.5" />}
        label="Extract"
        value={c.tavily_extracts}
      />
      <Stat
        icon={<Coins className="h-3.5 w-3.5" />}
        label="HTTP"
        value={c.http_fetches}
      />
    </div>
  );
}

function Stat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
}) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2">
      <span className="text-muted-fg">{icon}</span>
      <span className="text-muted-fg">{label}</span>
      <span className="ml-auto font-semibold text-fg">{value}</span>
    </div>
  );
}
