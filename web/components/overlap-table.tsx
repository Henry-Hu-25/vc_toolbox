import type { TeamOverlap } from "@/lib/types";
import { Badge } from "./ui/badge";
import { cn } from "@/lib/utils";

const STRENGTH_VARIANT = {
  strong: "success",
  medium: "info",
  weak: "warning",
  none: "default",
} as const;

export function OverlapTable({ overlap }: { overlap: TeamOverlap | null }) {
  if (!overlap || overlap.pairs.length === 0) {
    return (
      <p className="text-sm text-muted-fg italic">
        {overlap?.notes?.[0] ?? "No pairwise overlap available."}
      </p>
    );
  }
  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted">
            <tr>
              <Th>Pair</Th>
              <Th>Schools</Th>
              <Th>Employers</Th>
              <Th>Prior startups</Th>
              <Th>Accelerators</Th>
              <Th>Strength</Th>
            </tr>
          </thead>
          <tbody>
            {overlap.pairs.map((p, i) => (
              <tr key={i} className={cn(i % 2 === 0 ? "bg-card" : "bg-muted/30")}>
                <Td>
                  <span className="font-medium">{p.founder_a}</span>
                  <span className="text-muted-fg"> · </span>
                  <span className="font-medium">{p.founder_b}</span>
                </Td>
                <Td>{listOr(p.shared_schools.map((s) => s.school))}</Td>
                <Td>{listOr(p.shared_employers.map((s) => s.company))}</Td>
                <Td>{listOr(p.shared_prior_startups)}</Td>
                <Td>{listOr(p.shared_accelerators)}</Td>
                <Td>
                  <Badge variant={STRENGTH_VARIANT[p.strength]}>
                    {p.strength}
                  </Badge>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="space-y-1.5 text-sm text-muted-fg">
        {overlap.pairs
          .filter((p) => p.narrative)
          .map((p, i) => (
            <li key={i}>
              <span className="font-medium text-fg">
                {p.founder_a} &amp; {p.founder_b}:{" "}
              </span>
              {p.narrative}
            </li>
          ))}
      </ul>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-3 py-2 text-left text-xs uppercase tracking-wider text-muted-fg font-medium">
      {children}
    </th>
  );
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-3 py-2 align-top">{children}</td>;
}

function listOr(items: string[]) {
  if (!items.length) return <span className="text-muted-fg">—</span>;
  return items.join(", ");
}
