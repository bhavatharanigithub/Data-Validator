"use client";

import { ErrorState } from "@/components/status";

function isChunkError(error: Error) {
  return /Loading chunk|ChunkLoadError/i.test(error.message || "");
}

export default function AppError({ error, reset }: { error: Error; reset: () => void }) {
  const chunk = isChunkError(error);
  return (
    <main className="mx-auto max-w-lg p-6">
      <ErrorState
        message={
          chunk
            ? "The page module failed to load. Reload to use the current frontend build."
            : error.message || "The page could not be loaded."
        }
        onRetry={() => {
          if (chunk) window.location.reload();
          else reset();
        }}
      />
    </main>
  );
}
