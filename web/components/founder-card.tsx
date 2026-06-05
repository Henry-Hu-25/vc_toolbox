import type { FounderProfile } from "@/lib/types";
import { Card, CardContent } from "./ui/card";
import { Badge } from "./ui/badge";
import { GraduationCap, Briefcase, Rocket, Award, ExternalLink } from "lucide-react";

const CONFIDENCE_VARIANT: Record<string, "success" | "info" | "warning"> = {
  high: "success",
  medium: "info",
  low: "warning",
};

export function FounderCard({ founder }: { founder: FounderProfile }) {
  const initials = founder.name
    .split(/\s+/)
    .map((n) => n[0])
    .slice(0, 2)
    .join("");
  return (
    <Card className="h-full">
      <CardContent className="p-6 space-y-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-primary/80 to-primary/40 text-primary-fg font-semibold">
              {initials.toUpperCase()}
            </div>
            <div>
              <h3 className="font-semibold leading-tight">{founder.name}</h3>
              <p className="text-xs text-muted-fg">{founder.current_title || "—"}</p>
            </div>
          </div>
          <Badge variant={CONFIDENCE_VARIANT[founder.confidence] ?? "default"}>
            {founder.confidence}
          </Badge>
        </div>

        {(founder.total_years_experience != null ||
          founder.domain_years_experience != null) && (
          <div className="flex gap-2 text-xs text-muted-fg">
            {founder.total_years_experience != null && (
              <span>
                <span className="font-medium text-fg">
                  {founder.total_years_experience}
                </span>{" "}
                yrs total
              </span>
            )}
            {founder.domain_years_experience != null && (
              <span>
                · <span className="font-medium text-fg">
                  {founder.domain_years_experience}
                </span>{" "}
                yrs in domain
              </span>
            )}
          </div>
        )}

        {founder.accelerators.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {founder.accelerators.map((a) => (
              <Badge key={a} variant="primary">
                {a}
              </Badge>
            ))}
          </div>
        )}

        <Section icon={<GraduationCap className="h-3.5 w-3.5" />} title="Education">
          {founder.education.length === 0 ? (
            <Empty />
          ) : (
            founder.education.map((e, i) => (
              <Row
                key={`${e.school}-${i}`}
                primary={e.school}
                secondary={[e.degree, e.field].filter(Boolean).join(", ") || null}
                years={yearRange(e.start_year, e.end_year)}
              />
            ))
          )}
        </Section>

        <Section icon={<Briefcase className="h-3.5 w-3.5" />} title="Work">
          {founder.work.length === 0 ? (
            <Empty />
          ) : (
            founder.work.map((w, i) => (
              <Row
                key={`${w.company}-${i}`}
                primary={w.company}
                secondary={w.role}
                years={yearRange(w.start_year, w.end_year)}
                tags={[
                  w.is_founder_role ? "founder" : null,
                  w.is_technical_role ? "technical" : null,
                ].filter(Boolean) as string[]}
              />
            ))
          )}
        </Section>

        {founder.prior_startups.length > 0 && (
          <Section icon={<Rocket className="h-3.5 w-3.5" />} title="Prior startups">
            {founder.prior_startups.map((s, i) => (
              <Row
                key={`${s.name}-${i}`}
                primary={s.name}
                secondary={`${s.role} · ${s.outcome}`}
                years={s.year_started ? String(s.year_started) : null}
              />
            ))}
          </Section>
        )}

        {founder.notable_achievements.length > 0 && (
          <Section icon={<Award className="h-3.5 w-3.5" />} title="Notable">
            <ul className="space-y-1 text-sm text-muted-fg">
              {founder.notable_achievements.map((n, i) => (
                <li key={i}>· {n}</li>
              ))}
            </ul>
          </Section>
        )}

        {founder.linkedin_url && (
          <a
            href={founder.linkedin_url}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline"
          >
            LinkedIn <ExternalLink className="h-3 w-3" />
          </a>
        )}

        {founder.missing_fields.length > 0 && (
          <p className="text-[11px] text-muted-fg">
            Missing: {founder.missing_fields.join(", ")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-muted-fg mb-2">
        {icon}
        {title}
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function Row({
  primary,
  secondary,
  years,
  tags,
}: {
  primary: string;
  secondary?: string | null;
  years?: string | null;
  tags?: string[];
}) {
  return (
    <div className="text-sm flex flex-wrap items-baseline gap-x-2">
      <span className="font-medium text-fg">{primary}</span>
      {secondary && <span className="text-muted-fg">{secondary}</span>}
      {years && <span className="text-xs font-mono text-muted-fg ml-auto">{years}</span>}
      {tags && tags.length > 0 && (
        <div className="basis-full flex gap-1 mt-1">
          {tags.map((t) => (
            <span
              key={t}
              className="text-[10px] uppercase tracking-wider text-muted-fg border border-border rounded px-1 py-0.5"
            >
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Empty() {
  return <p className="text-xs text-muted-fg italic">No data found.</p>;
}

function yearRange(s: number | null, e: number | null): string | null {
  if (s == null && e == null) return null;
  return `${s ?? "?"}–${e ?? "present"}`;
}
