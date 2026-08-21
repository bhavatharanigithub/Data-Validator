"use client";

import { Info } from "lucide-react";

export function AccessInfoTooltip() {
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        className="inline-flex rounded-full p-0.5 text-inst-navy/80 hover:text-inst-navy"
        aria-describedby="authorized-access-tip"
        aria-label="About authorized access"
      >
        <Info className="h-4 w-4" aria-hidden="true" />
      </button>
      <span
        id="authorized-access-tip"
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-0 z-20 mb-2 w-64 max-w-[min(16rem,calc(100vw-3rem))] rounded border border-inst-border bg-inst-surface px-3 py-2 text-left text-xs leading-5 text-inst-text opacity-0 shadow-inst transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 sm:left-1/2 sm:-translate-x-1/2"
      >
        Restricted for government use only. Access is logged and monitored. Data is protected in an
        encrypted environment.
      </span>
    </span>
  );
}
