"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Building2,
  ClipboardList,
  FileBarChart,
  LayoutDashboard,
  LogOut,
  Map,
  Settings,
  Users,
  Workflow,
} from "lucide-react";
import { InstitutionalMark } from "@/components/brand/institutional-mark";
import { getAiHealth, getHealth, getMe, listBatches, logout } from "@/lib/api";
import { clearSession, readSession, writeSession } from "@/lib/auth";
import { readSelectedBatch, writeSelectedBatch } from "@/lib/session-state";
import { EmptyState, ErrorState, LoadingState, StageBadge } from "./status";
import { useEffect, useMemo, useState } from "react";

const NAV = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/dashboard/batches", label: "Batches", icon: Workflow },
  { href: "/dashboard/anomalies", label: "Review queue", icon: Activity },
  { href: "/dashboard/analytics", label: "Analytics", icon: FileBarChart },
  { href: "/dashboard/rules", label: "Detectors", icon: Settings },
  { href: "/dashboard/investigations", label: "Investigations", icon: ClipboardList },
  { href: "/dashboard/enumerators", label: "Enumerators", icon: Users },
  { href: "/dashboard/clusters", label: "Clusters", icon: Map },
  { href: "/dashboard/districts", label: "Districts", icon: Building2 },
  { href: "/dashboard/reports", label: "Reports", icon: FileBarChart },
  { href: "/dashboard/settings", label: "Settings", icon: Settings },
];

function aiLabel(status?: string, configured?: boolean, pending?: boolean) {
  if (pending) return "PENDING";
  if (!configured) return "NOT CONFIGURED";
  if (status === "ready") return "READY";
  return "UNAVAILABLE";
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: getMe,
    retry: false,
  });
  const session = me.data
    ? { username: me.data.username, role: me.data.role }
    : readSession();
  const [batchId, setBatchId] = useState<string | null>(null);

  const health = useQuery({ queryKey: ["health"], queryFn: getHealth });
  const ai = useQuery({ queryKey: ["ai-health"], queryFn: getAiHealth });
  const batches = useQuery({ queryKey: ["batches"], queryFn: listBatches, enabled: me.isSuccess, retry: false });

  useEffect(() => {
    if (me.isError) {
      clearSession();
      router.replace("/login");
    }
    if (me.data) {
      writeSession({ username: me.data.username, role: me.data.role, display_name: me.data.display_name, demo: me.data.demo });
    }
  }, [me.isError, me.data, router]);

  useEffect(() => {
    if (!batches.isSuccess) return;
    const stored = readSelectedBatch();
    const items = batches.data?.items ?? [];
    if (stored && items.some((item) => item.batch_id === stored)) {
      setBatchId(stored);
      return;
    }
    if (items[0]) {
      setBatchId(items[0].batch_id);
      writeSelectedBatch(items[0].batch_id);
      window.dispatchEvent(new Event("sv-batch-change"));
      return;
    }
    setBatchId(null);
  }, [batches.data, batches.isSuccess]);

  const current = useMemo(
    () => batches.data?.items?.find((item) => item.batch_id === batchId),
    [batches.data, batchId]
  );

  const systemStatus = health.isPending ? "PENDING" : health.data?.status === "ok" ? "COMPLETED" : "UNAVAILABLE";
  const systemsOperational = !health.isPending && health.data?.status === "ok";

  return (
    <div className="sv-portal flex min-h-screen">
      <aside className="relative flex w-60 shrink-0 flex-col border-r border-inst-border bg-inst-surface">
        <div className="sv-tricolor" aria-hidden="true">
          <span className="bg-inst-saffron" />
          <span className="bg-white" />
          <span className="bg-inst-green" />
        </div>
        <nav className="flex-1 space-y-0.5 p-3" aria-label="Application">
          {NAV.map((item) => {
            const active = pathname === item.href || (item.href !== "/dashboard" && pathname.startsWith(item.href));
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2 rounded px-3 py-2 text-sm ${
                  active
                    ? "bg-[#e8eef5] font-semibold text-inst-navy"
                    : "text-inst-text hover:bg-inst-muted"
                }`}
              >
                <Icon className="h-4 w-4 text-inst-blue" />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="relative overflow-hidden border-t border-inst-border p-4">
          <div className="sv-shell-motif" aria-hidden="true" />
          <p className="relative text-[11px] font-semibold uppercase tracking-[0.14em] text-inst-navy">
            Secure data service
          </p>
          <p className="relative mt-2 text-xs text-inst-text">
            {health.isPending ? (
              "Checking system status…"
            ) : (
              <span className="inline-flex items-center gap-1.5">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${systemsOperational ? "bg-inst-green" : "bg-inst-warning"}`}
                  aria-hidden="true"
                />
                {systemsOperational ? "Systems operational" : "System status unavailable"}
              </span>
            )}
          </p>
          <p className="relative mt-3 text-[10px] leading-4 text-inst-text-secondary">
            Project identity for survey quality review · Not an official government service
          </p>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-b border-inst-border bg-inst-surface px-6 py-3">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex min-w-0 items-center gap-3">
              <InstitutionalMark className="h-11 w-11 shrink-0" />
              <div>
                <p className="text-[0.65rem] font-semibold uppercase tracking-[0.18em] text-inst-navy">
                  Survey Data Intelligence
                </p>
                <p className="font-display text-sm font-semibold text-inst-navy">
                  Official Statistics &amp; Survey Quality
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-end gap-6">
              <div>
                <p className="sv-label">Survey</p>
                <p className="text-sm text-inst-text">
                  {current?.survey_code || (batches.isPending ? "…" : "DEMO")}
                </p>
              </div>
              <div>
                <label className="sv-label" htmlFor="shell-batch-select">
                  Batch
                </label>
                <select
                  id="shell-batch-select"
                  className="mt-0.5 block border-0 bg-transparent p-0 text-sm text-inst-text"
                  value={batchId ?? ""}
                  onChange={(event) => {
                    writeSelectedBatch(event.target.value);
                    setBatchId(event.target.value);
                    window.dispatchEvent(new Event("sv-batch-change"));
                  }}
                >
                  {(batches.data?.items ?? []).map((item) => (
                    <option key={item.batch_id} value={item.batch_id}>
                      {item.batch_id}
                    </option>
                  ))}
                  {batches.isPending ? <option value="">Loading batches…</option> : null}
                  {batches.isError ? <option value="">Batches unavailable</option> : null}
                  {batches.isSuccess && !batches.data?.items.length ? <option value="">No batches</option> : null}
                </select>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-6 text-sm">
              <div>
                <p className="sv-label">System</p>
                <StageBadge value={systemStatus} />
              </div>
              <div>
                <p className="sv-label">AI</p>
                <StageBadge value={aiLabel(ai.data?.status, ai.data?.configured, ai.isPending)} />
              </div>
              <div className="flex items-center gap-3">
                <div>
                  <p className="sv-label">Supervisor</p>
                  <p className="text-sm text-inst-text">
                    {session?.username} · {session?.role}
                  </p>
                </div>
                <button
                  className="rounded border border-inst-border p-2 text-inst-text-secondary hover:text-inst-navy"
                  onClick={async () => {
                    await logout().catch(() => undefined);
                    clearSession();
                    router.replace("/login");
                  }}
                  aria-label="Sign out"
                >
                  <LogOut className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        </header>
        <main className="min-w-0 flex-1 overflow-auto p-6">
          {batches.isError ? (
            <div className="mb-4">
              <ErrorState message="Could not load batches from the backend." onRetry={() => batches.refetch()} />
            </div>
          ) : null}
          {children}
        </main>
        <footer className="border-t border-inst-border bg-inst-surface px-6 py-3 text-xs text-inst-text-secondary">
          © 2026 Survey Data Intelligence
        </footer>
      </div>
    </div>
  );
}

export function useBatchSelection() {
  const [batchId, setBatchId] = useState<string | null>(readSelectedBatch());
  const batches = useQuery({ queryKey: ["batches"], queryFn: listBatches, retry: false });
  useEffect(() => {
    const sync = () => setBatchId(readSelectedBatch());
    window.addEventListener("sv-batch-change", sync);
    return () => window.removeEventListener("sv-batch-change", sync);
  }, []);
  useEffect(() => {
    if (!batches.isSuccess) return;
    const stored = readSelectedBatch();
    const items = batches.data?.items ?? [];
    if (stored && items.some((item) => item.batch_id === stored)) {
      setBatchId(stored);
      return;
    }
    if (items[0]) {
      setBatchId(items[0].batch_id);
      writeSelectedBatch(items[0].batch_id);
      return;
    }
    setBatchId(null);
  }, [batches.data, batches.isSuccess]);
  return {
    batchId,
    isLoading: batches.isPending,
    isError: batches.isError,
    isEmpty: batches.isSuccess && !(batches.data?.items.length),
    refetch: () => batches.refetch(),
  };
}

export function useSelectedBatch(): string | null {
  return useBatchSelection().batchId;
}

export function BatchSelectionGate({
  children,
  emptyDetail,
}: {
  children: (batchId: string) => ReactNode;
  emptyDetail: string;
}) {
  const selection = useBatchSelection();
  if (selection.isLoading && !selection.batchId) return <LoadingState message="Loading batches…" />;
  if (selection.isError && !selection.batchId) {
    return <ErrorState message="Could not load batches from the backend." onRetry={() => selection.refetch()} />;
  }
  if (!selection.batchId) {
    return <EmptyState title="No batches" detail={emptyDetail} />;
  }
  return <>{children(selection.batchId)}</>;
}
