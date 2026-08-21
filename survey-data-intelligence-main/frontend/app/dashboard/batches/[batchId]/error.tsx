"use client";

import { ErrorState } from "@/components/status";

export default function BatchDetailError({ error, reset }: { error: Error; reset: () => void }) {
  const chunk = /Loading chunk|ChunkLoadError/i.test(error.message || "");
  return (
    <ErrorState
      message={
        chunk
          ? "This batch page failed to load a module. Reload to use the current frontend build."
          : error.message || "This batch page could not be loaded. Deterministic validation is unaffected."
      }
      onRetry={() => {
        if (chunk) window.location.reload();
        else reset();
      }}
    />
  );
}
