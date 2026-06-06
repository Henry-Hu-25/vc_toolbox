"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, ExternalLink, FileJson, FileText } from "lucide-react";
import { getRun, API_BASE } from "@/lib/api";
import type { ReportPayload } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { TierBadge } from "@/components/tier-badge";
import { ScoreGauge } from "@/components/score-gauge";
import { FounderCard } from "@/components/founder-card";
import { OverlapTable } from "@/components/overlap-table";
import { CostLedger } from "@/components/cost-ledger";
import { MarkdownReport } from "@/components/markdown-report";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";

export default function RunDetailPage() {
  const { slug } = useParams<{ slug: string }>();
  const [data, setData] = React.useState<{
    slug: string;
    report: ReportPayload;
    markdown: string;
  } | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [view, setView] = React.useState<"structured" | "markdown" | "json">("structured");

  React.useEffect(() => {
    getRun(slug)
      .then(setData)
      .catch((e) => setError((e as Error).message));
  }, [slug]);

  return (
    <div className="min-h-screen flex flex-col">
      <SiteHeader />
      <main className="flex-1">
        <section className="container max-w-5xl py-8 sm:py-12">
          <Link
            href="/runs"
            className="inline-flex items-center gap-1.5 text-sm text-muted-fg hover:text-fg transition-colors mb-6"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Back to history
          </Link>

          {error && (
            <Card>
              <CardContent className="p-6 text-sm text-rose-500">
                {error}
              </CardContent>
            </Card>
          )}

          {!data && !error && <ReportSkeleton />}

          {data && <Report data={data} view={view} setView={setView} />}
        </section>
      </main>
      <SiteFooter />
    </div>
  );
}

function Report({
  data,
  view,
  setView,
}: {
  data: { slug: string; report: ReportPayload; markdown: string };
  view: "structured" | "markdown" | "json";
  setView: (v: "structured" | "markdown" | "json") => void;
}) {
  const report = data.report;
  const score = report.score;
  const company = report.company;

  return (
    <div className="space-y-10">
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-center gap-6 lg:gap-10">
        <div className="flex-1 min-w-0">
          <p className="text-xs uppercase tracking-widest text-muted-fg mb-2">
            Founding team analysis
          </p>
          <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight">
            {company?.name ?? data.slug}
          </h1>
          {company?.one_liner && (
            <p className="text-muted-fg mt-2 max-w-2xl">{company.one_liner}</p>
          )}
          <div className="flex flex-wrap items-center gap-2 mt-4">
            {company?.sector && <Badge variant="outline">{company.sector}</Badge>}
            {company?.hq_location && (
              <Badge variant="outline">{company.hq_location}</Badge>
            )}
            {company?.founded_year && (
              <Badge variant="outline">Founded {company.founded_year}</Badge>
            )}
            {company?.stage_signals?.slice(0, 3).map((s) => (
              <Badge key={s} variant="primary">
                {s}
              </Badge>
            ))}
          </div>
          <div className="flex flex-wrap gap-3 mt-5">
            {company?.website && (
              <a
                href={company.website}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
              >
                {company.website} <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
            {company?.linkedin_url && (
              <a
                href={company.linkedin_url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1.5 text-sm text-muted-fg hover:text-fg"
              >
                LinkedIn <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
          </div>
        </div>
        {score && (
          <div className="flex flex-col items-center gap-3 shrink-0">
            <ScoreGauge score={score.overall_0_100} />
            <TierBadge tier={score.tier} size="lg" />
          </div>
        )}
      </div>

      <Separator />

      {/* View toggle */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          className="inline-flex rounded-md border border-border p-1 bg-card"
          role="tablist"
          aria-label="Report view"
        >
          {(["structured", "markdown", "json"] as const).map((v) => (
            <button
              key={v}
              role="tab"
              aria-selected={view === v}
              aria-controls={`tabpanel-${v}`}
              onClick={() => setView(v)}
              onKeyDown={(e) => {
                const views = ["structured", "markdown", "json"] as const;
                const idx = views.indexOf(v);
                let next = -1;
                if (e.key === "ArrowRight") next = (idx + 1) % views.length;
                else if (e.key === "ArrowLeft") next = (idx - 1 + views.length) % views.length;
                if (next >= 0) {
                  e.preventDefault();
                  setView(views[next]);
                  (e.currentTarget.parentElement?.querySelector(`[data-tab="${views[next]}"]`) as HTMLElement)?.focus();
                }
              }}
              data-tab={v}
              className={`px-3 py-1 text-xs rounded ${
                view === v ? "bg-muted text-fg" : "text-muted-fg hover:text-fg"
              }`}
            >
              {v[0].toUpperCase() + v.slice(1)}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <a
            href={`${API_BASE}/api/runs/${data.slug}`}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex h-8 items-center gap-2 rounded-md border border-border bg-transparent px-3 text-xs font-medium hover:bg-muted text-fg"
          >
            <FileJson className="h-3.5 w-3.5" /> JSON
          </a>
          <Button
            variant="outline"
            size="sm"
            onClick={() => downloadMarkdown(data.slug, data.markdown)}
          >
            <FileText className="h-3.5 w-3.5" /> .md
          </Button>
        </div>
      </div>

      {view === "structured" && (
        <div role="tabpanel" id="tabpanel-structured" aria-labelledby="structured" className="space-y-10">
          <Section title="Founders">
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {report.founders.map((f, i) => (
                <FounderCard key={`${f.name}-${i}`} founder={f} />
              ))}
            </div>
          </Section>
          <Section title="Founder Overlap">
            <OverlapTable overlap={report.overlaps} />
          </Section>
          {score && (
            <Section title="Score">
              <ScoreSection score={score} />
            </Section>
          )}
          <Section title="Cost & sources">
            <CostLedger cost={report.cost} className="mb-4" />
            {report.warnings.length > 0 && (
              <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-700 dark:text-amber-300 space-y-0.5">
                <p className="font-medium mb-1">
                  Warnings ({report.warnings.length})
                </p>
                {report.warnings.map((w, i) => (
                  <p key={i} className="break-all">- {w}</p>
                ))}
              </div>
            )}
          </Section>
        </div>
      )}

      {view === "markdown" && (
        <Card role="tabpanel" id="tabpanel-markdown" aria-labelledby="markdown">
          <CardContent className="p-6 sm:p-8">
            <MarkdownReport markdown={data.markdown} />
          </CardContent>
        </Card>
      )}

      {view === "json" && (
        <Card role="tabpanel" id="tabpanel-json" aria-labelledby="json">
          <CardContent className="p-0">
            <pre className="text-xs font-mono p-6 overflow-x-auto leading-6 max-h-[70vh]">
              {JSON.stringify(report, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function ScoreSection({
  score,
}: {
  score: NonNullable<ReportPayload["score"]>;
}) {
  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted text-xs uppercase tracking-wider text-muted-fg">
            <tr>
              <th className="text-left px-4 py-2 font-medium">Criterion</th>
              <th className="text-right px-4 py-2 font-medium">Weight</th>
              <th className="text-left px-4 py-2 font-medium">Score</th>
              <th className="text-left px-4 py-2 font-medium">Rationale</th>
            </tr>
          </thead>
          <tbody>
            {score.criteria.map((c) => (
              <tr key={c.key} className="border-t border-border">
                <td className="px-4 py-3 font-medium">{c.label}</td>
                <td className="px-4 py-3 text-right font-mono text-xs">
                  {Math.round(c.weight * 100)}%
                </td>
                <td className="px-4 py-3 w-40">
                  <ScoreBar value={c.score} />
                </td>
                <td className="px-4 py-3 text-muted-fg">
                  {c.rationale}
                  {c.evidence.length > 0 && (
                    <details className="mt-2">
                      <summary className="text-xs cursor-pointer text-muted-fg hover:text-fg select-none">
                        Evidence ({c.evidence.length})
                      </summary>
                      <ul className="mt-2 space-y-1 pl-4 list-disc list-outside text-xs">
                        {c.evidence.map((e, i) => (
                          <li key={i}>
                            <EvidenceText text={e} />
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid md:grid-cols-3 gap-4">
        <Pill title="Strengths" items={score.top_strengths} variant="success" />
        <Pill title="Risks" items={score.top_risks} variant="danger" />
        <Pill title="DD questions" items={score.open_questions} variant="info" />
      </div>
    </div>
  );
}

function ScoreBar({ value }: { value: number }) {
  const pct = (Math.max(0, Math.min(5, value)) / 5) * 100;
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full bg-primary"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-mono w-4 text-right">{value}</span>
    </div>
  );
}

function Pill({
  title,
  items,
  variant,
}: {
  title: string;
  items: string[];
  variant: "success" | "danger" | "info";
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2 mb-2">
        <Badge variant={variant}>{title}</Badge>
        <span className="text-xs text-muted-fg">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-muted-fg italic">None.</p>
      ) : (
        <ul className="space-y-1.5 text-sm">
          {items.map((it, i) => (
            <li key={i} className="leading-relaxed">
              · {it}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h2 className="text-xs uppercase tracking-widest text-muted-fg mb-4">
        {title}
      </h2>
      {children}
    </section>
  );
}

function ReportSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-10 w-2/3" />
      <Skeleton className="h-4 w-1/2" />
      <div className="grid md:grid-cols-3 gap-4">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-48 rounded-lg" />
        ))}
      </div>
    </div>
  );
}

function downloadMarkdown(slug: string, md: string) {
  const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${slug}.report.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const URL_RE = /https?:\/\/[^\s)>]+/i;

function EvidenceText({ text }: { text: string }) {
  const pureUrl = /^https?:\/\/[^\s]+$/i.test(text);
  if (pureUrl) {
    return (
      <a
        href={text}
        target="_blank"
        rel="noreferrer noopener"
        className="text-primary hover:underline break-all"
      >
        {text}
      </a>
    );
  }
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let key = 0;
  while (remaining.length > 0) {
    const match = remaining.match(URL_RE);
    if (!match || match.index === undefined) {
      parts.push(remaining);
      break;
    }
    if (match.index > 0) {
      parts.push(remaining.slice(0, match.index));
    }
    const href = match[0];
    parts.push(
      <a
        key={key++}
        href={href}
        target="_blank"
        rel="noreferrer noopener"
        className="text-primary hover:underline break-all"
      >
        {href}
      </a>
    );
    remaining = remaining.slice(match.index + href.length);
  }
  return <>{parts}</>;
}
