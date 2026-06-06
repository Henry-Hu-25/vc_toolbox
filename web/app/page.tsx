import { AnalyzeForm } from "@/components/analyze-form";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import { LiveModelName } from "@/components/live-model-name";

export default function HomePage() {
  return (
    <div className="min-h-screen flex flex-col">
      <SiteHeader />
      <main className="flex-1">
        <section className="container max-w-2xl pt-16 sm:pt-24 pb-12">
          <div className="text-center mb-10">
            <p className="text-xs uppercase tracking-widest text-primary font-medium mb-3">
              Multi-agent founder analysis
            </p>
            <h1 className="text-4xl sm:text-5xl font-semibold tracking-tight text-balance">
              Score a founding team in 90 seconds.
            </h1>
            <p className="mt-4 text-muted-fg sm:text-lg max-w-xl mx-auto text-balance">
              Drop a company name or URL. We&rsquo;ll resolve the company, find
              the founders, research each one, detect shared history, and grade
              the team against an 8-criterion VC rubric.
            </p>
          </div>
          <AnalyzeForm />
          <FeatureGrid />
        </section>
      </main>
      <SiteFooter />
    </div>
  );
}

function FeatureGrid() {
  const cards = [
    {
      title: "Six specialist agents",
      body: "Profiler, FounderFinder, Researcher (fan-out), OverlapAnalyzer, Scorer, ReportWriter.",
    },
    {
      title: "Evidence-first",
      body: "Every score cites a source URL. Anti-collision gates drop look-alike profiles.",
    },
    {
      title: null,
      body: "Frontier reasoning with structured outputs and a tight per-run budget.",
    },
  ];
  return (
    <div className="mt-16 grid sm:grid-cols-3 gap-4">
      {cards.map((it, i) => (
        <div
          key={i}
          className="rounded-lg border border-border bg-card p-5"
        >
          <h3 className="font-medium text-sm">
            {it.title ?? (
              <>
                Powered by <LiveModelName />
              </>
            )}
          </h3>
          <p className="text-xs text-muted-fg mt-1.5 leading-relaxed">
            {it.body}
          </p>
        </div>
      ))}
    </div>
  );
}
