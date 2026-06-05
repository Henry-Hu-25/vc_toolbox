import Link from "next/link";
import { ThemeToggle } from "./theme-toggle";
import { InProgressPill } from "./in-progress-pill";

export function SiteHeader() {
  return (
    <header className="border-b border-border bg-bg/80 backdrop-blur supports-[backdrop-filter]:bg-bg/60 sticky top-0 z-40">
      <div className="container flex h-14 items-center justify-between">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <Logo />
          <span>Founding Team Analyzer</span>
        </Link>
        <nav className="flex items-center gap-2">
          <InProgressPill />
          <Link
            href="/runs"
            className="text-sm text-muted-fg hover:text-fg transition-colors px-3 py-1.5 rounded-md hover:bg-muted"
          >
            History
          </Link>
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}

function Logo() {
  return (
    <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="8" fill="hsl(var(--fg))" />
      <circle cx="11" cy="13" r="3.5" fill="hsl(var(--primary))" />
      <circle cx="21" cy="13" r="3.5" fill="hsl(217 91% 60%)" />
      <circle cx="16" cy="22" r="3.5" fill="hsl(158 64% 52%)" />
    </svg>
  );
}
