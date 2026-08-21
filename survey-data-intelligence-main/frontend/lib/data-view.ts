"use client";

import { useCallback, useEffect, useState } from "react";

export const DATA_VIEW_CURRENT = "current_batch";
export const DATA_VIEW_CUMULATIVE = "cumulative";
export type DataView = typeof DATA_VIEW_CURRENT | typeof DATA_VIEW_CUMULATIVE;

const STORAGE_KEY = "sv_data_view";

export function isCumulativeView(view: DataView): boolean {
  return view === DATA_VIEW_CUMULATIVE;
}

export function useDataView(): [DataView, (next: DataView) => void] {
  const [view, setView] = useState<DataView>(DATA_VIEW_CURRENT);

  useEffect(() => {
    try {
      const stored = sessionStorage.getItem(STORAGE_KEY);
      if (stored === DATA_VIEW_CUMULATIVE || stored === DATA_VIEW_CURRENT) {
        setView(stored);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const update = useCallback((next: DataView) => {
    setView(next);
    try {
      sessionStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
  }, []);

  return [view, update];
}
