"use client";

import * as React from "react";
import { useRunStore } from "@/lib/run-store";

export function RunHydrator() {
  const hydrate = useRunStore((s) => s.hydrate);
  const ranRef = React.useRef(false);

  React.useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;

    async function rehydrateAndHydrate() {
      // 1. Read persisted state from localStorage (skipHydration delays this
      //    until after mount so SSR and first client render match).
      await useRunStore.persist.rehydrate();
      // 2. Check if a persisted run is still active on the server and
      //    resubscribe to its SSE stream if so.
      await hydrate();
      // 3. Signal that hydration is complete — gated components may now
      //    render based on the real store state.
      useRunStore.setState({ hydrated: true });
    }

    void rehydrateAndHydrate();
  }, [hydrate]);

  return null;
}
