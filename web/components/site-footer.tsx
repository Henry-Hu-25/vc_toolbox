"use client";

import * as React from "react";
import { getHealth } from "@/lib/api";

export function SiteFooter() {
  const [model, setModel] = React.useState<string | null>(null);
  const [effort, setEffort] = React.useState<string | null>(null);

  React.useEffect(() => {
    getHealth()
      .then((h) => {
        setModel((h.model_reasoning as string) ?? null);
        setEffort((h.reasoning_effort as string) ?? null);
      })
      .catch(() => {
        setModel(null);
      });
  }, []);

  return (
    <footer className="border-t border-border mt-16">
      <div className="container py-6 flex flex-wrap items-center justify-between gap-3 text-xs text-muted-fg">
        <p>vc_toolbox · founding_team_analyzer v0.1.1</p>
        {model && (
          <p className="font-mono">
            {model}
            {effort ? ` · ${effort}` : ""}
          </p>
        )}
      </div>
    </footer>
  );
}
