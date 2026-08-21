"use client";

import { Suspense } from "react";
import RecordPage from "./record-page";

export default function Page() {
  return (
    <Suspense fallback={<p className="text-sm text-inst-text-secondary">Loading record…</p>}>
      <RecordPage />
    </Suspense>
  );
}
