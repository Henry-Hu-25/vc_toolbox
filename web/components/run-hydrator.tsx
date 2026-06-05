"use client";

import * as React from "react";
import { useRunStore } from "@/lib/run-store";

export function RunHydrator() {
  const hydrate = useRunStore((s) => s.hydrate);
  const ranRef = React.useRef(false);

  React.useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;
    void hydrate();
  }, [hydrate]);

  return null;
}
