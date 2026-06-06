"use client";

import * as React from "react";
import { useTheme } from "next-themes";
import { Moon, Sun, Monitor } from "lucide-react";
import { Button } from "./ui/button";

const cycle = ["light", "dark", "system"] as const;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  const current = theme || "system";
  const idx = cycle.indexOf(current as (typeof cycle)[number]);
  const nextIdx = (idx + 1) % cycle.length;
  const next = cycle[nextIdx];

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={`Switch to ${next} mode (current: ${current})`}
      data-state={current}
      onClick={() => mounted && setTheme(next)}
    >
      {current === "dark" ? (
        <Monitor className="h-4 w-4" />
      ) : current === "system" ? (
        <Sun className="h-4 w-4" />
      ) : (
        <Moon className="h-4 w-4" />
      )}
    </Button>
  );
}
