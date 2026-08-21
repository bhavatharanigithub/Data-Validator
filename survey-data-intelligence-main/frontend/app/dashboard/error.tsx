"use client";

import { ErrorState } from "@/components/status";

function isChunkError(error: Error) {
  return /Loading chunk|ChunkLoadError/i.test(error.message || "");
}

export default function DashboardError({ error, reset }: { error: Error; reset: () => void }) {
  const chunk = isChunkError(error);
  return (
    <ErrorState
      message={
        chunk
          ? "This dashboard page failed to load a module. Reload to use the current frontend build."
          : error.message || "This page could not be loaded."
      }
      onRetry={() => {
        if (chunk) window.location.reload();
        else reset();
      }}
    />
  );
}
