"use client";

import * as React from "react";
import { getHealth } from "@/lib/api";

export function LiveModelName() {
  const [model, setModel] = React.useState<string | null>(null);

  React.useEffect(() => {
    getHealth()
      .then((h) => {
        setModel((h.model_reasoning as string) ?? null);
      })
      .catch(() => {
        setModel(null);
      });
  }, []);

  return <>{model ?? "frontier LLM"}</>;
}
