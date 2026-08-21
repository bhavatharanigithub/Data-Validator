"use client";

import { useQuery } from "@tanstack/react-query";
import { Building2, Info, Server, Shield, Sparkles, UserRound } from "lucide-react";
import { useBatchSelection } from "@/components/shell";
import { ErrorState, LoadingState, StageBadge } from "@/components/status";
import { getAiHealth, getAuthStatus, getHealth, getMe, listBatches } from "@/lib/api";
import { readSession } from "@/lib/auth";

function aiLabel(status?: string, configured?: boolean, pending?: boolean) {
  if (pending) return "PENDING";
  if (!configured) return "NOT CONFIGURED";
  if (status === "ready") return "READY";
  return "UNAVAILABLE";
}

function backendLabel(pending: boolean, status?: string) {
  if (pending) return "PENDING";
  return status === "ok" ? "COMPLETED" : "UNAVAILABLE";
}

function backendExplanation(label: string) {
  if (label === "PENDING") return "Checking backend availability.";
  if (label === "COMPLETED") return "The backend health check succeeded. Services are available.";
  return "The backend health check did not succeed.";
}

function aiExplanation(label: string) {
  if (label === "PENDING") return "Checking AI service status.";
  if (label === "READY") return "AI services are available through the backend.";
  if (label === "NOT CONFIGURED") return "AI is not configured on the backend.";
  return "AI is configured but not reported as ready.";
}

export default function SettingsPage() {
  const me = useQuery({ queryKey: ["me"], queryFn: getMe, retry: false });
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth, retry: false });
  const ai = useQuery({ queryKey: ["ai-health"], queryFn: getAiHealth, retry: false });
  const auth = useQuery({ queryKey: ["auth-status"], queryFn: getAuthStatus, retry: false });
  const selection = useBatchSelection();
  const batches = useQuery({ queryKey: ["batches"], queryFn: listBatches, retry: false });

  const session = me.data
    ? { username: me.data.username, role: me.data.role, demo: me.data.demo }
    : readSession();
  const systemStatus = backendLabel(health.isPending, health.data?.status);
  const aiStatus = aiLabel(ai.data?.status, ai.data?.configured, ai.isPending);
  const currentBatch = batches.data?.items?.find((item) => item.batch_id === selection.batchId);
  const surveyCode = currentBatch?.survey_code || undefined;
  const demoMode = Boolean(auth.data?.demo ?? session?.demo);

  const workspaceRows = [
    surveyCode ? { label: "Survey", value: surveyCode } : null,
    selection.batchId ? { label: "Batch", value: selection.batchId } : null,
    session?.username && session?.role
      ? { label: "Supervisor", value: `${session.username} · ${session.role}` }
      : null,
    { label: "System", value: systemStatus, badge: true },
    { label: "AI", value: aiStatus, badge: true },
  ].filter(Boolean) as { label: string; value: string; badge?: boolean }[];

  return (
    <div className="space-y-6">
      <div>
        <p className="sv-label">Environment</p>
        <h1 className="mt-1 text-2xl font-semibold text-inst-navy">Workspace & system</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-inst-text-secondary">
          System status, authentication context, and security information for this workspace.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="sv-card p-5">
          <div className="flex items-start gap-3">
            <span className="sv-metric-icon bg-[#e8eef5] text-inst-blue" aria-hidden="true">
              <UserRound className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-inst-navy">
                Authentication & access
              </h2>
              <p className="mt-1 text-sm leading-6 text-inst-text-secondary">
                Current sign-in context from the authenticated user record.
              </p>
            </div>
          </div>

          {auth.isPending ? <div className="mt-4"><LoadingState message="Loading authentication status…" /></div> : null}
          {auth.isError ? (
            <div className="mt-4">
              <ErrorState message="Authentication status could not be loaded." onRetry={() => auth.refetch()} />
            </div>
          ) : null}

          <dl className="mt-4 divide-y divide-inst-border border-y border-inst-border">
            {demoMode ? (
              <InfoRow label="Environment" value="Walkthrough" />
            ) : null}
            <InfoRow label="User" value={session?.username ?? "…"} />
            <InfoRow label="Role" value={session?.role ?? "…"} />
            {demoMode ? (
              <InfoRow label="Authentication" value="Walkthrough authentication" />
            ) : null}
          </dl>

          {auth.data?.notice ? (
            <div className="mt-4 rounded border border-[#c5d4e6] bg-[#e8eef5] px-4 py-3 text-sm leading-6 text-inst-navy">
              {auth.data.notice}
            </div>
          ) : null}
        </section>

        <section className="sv-card p-5">
          <div className="flex items-start gap-3">
            <span className="sv-metric-icon bg-[#e8eef5] text-inst-blue" aria-hidden="true">
              <Server className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-inst-navy">System status</h2>
              <p className="mt-1 text-sm leading-6 text-inst-text-secondary">
                Availability reported by existing health endpoints.
              </p>
            </div>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {health.isError ? (
              <div className="sm:col-span-2">
                <ErrorState message="Backend health could not be loaded." onRetry={() => health.refetch()} />
              </div>
            ) : (
              <StatusTile
                icon={Server}
                name="Backend"
                status={systemStatus}
                explanation={backendExplanation(systemStatus)}
              />
            )}
            {ai.isError ? (
              <div className="sm:col-span-2">
                <ErrorState message="AI health could not be loaded." onRetry={() => ai.refetch()} />
              </div>
            ) : (
              <StatusTile
                icon={Sparkles}
                name="AI"
                status={aiStatus}
                explanation={aiExplanation(aiStatus)}
              />
            )}
          </div>
        </section>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="sv-card p-5">
          <div className="flex items-start gap-3">
            <span className="sv-metric-icon bg-[#e8eef5] text-inst-blue" aria-hidden="true">
              <Shield className="h-4 w-4" />
            </span>
            <div>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-inst-navy">
                Security & data handling
              </h2>
              <p className="mt-1 text-sm leading-6 text-inst-text-secondary">
                Principles already enforced by this application.
              </p>
            </div>
          </div>
          <ul className="mt-4 space-y-4">
            <li>
              <p className="text-sm font-semibold text-inst-navy">Backend-mediated AI calls</p>
              <p className="mt-1 text-sm leading-6 text-inst-text-secondary">
                AI credentials are not exposed to the browser.
              </p>
            </li>
            <li>
              <p className="text-sm font-semibold text-inst-navy">Persisted evidence</p>
              <p className="mt-1 text-sm leading-6 text-inst-text-secondary">
                Reports and quality signals are generated from backend evidence.
              </p>
            </li>
            <li>
              <p className="text-sm font-semibold text-inst-navy">Role-aware access</p>
              <p className="mt-1 text-sm leading-6 text-inst-text-secondary">
                User roles are supplied by the authenticated user record.
              </p>
            </li>
          </ul>
        </section>

        <section className="sv-card p-5">
          <div className="flex items-start gap-3">
            <span className="sv-metric-icon bg-[#e8eef5] text-inst-blue" aria-hidden="true">
              <Building2 className="h-4 w-4" />
            </span>
            <div>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-inst-navy">Current workspace</h2>
              <p className="mt-1 text-sm leading-6 text-inst-text-secondary">
                Values from the current session and selected batch.
              </p>
            </div>
          </div>
          {workspaceRows.length ? (
            <dl className="mt-4 divide-y divide-inst-border border-y border-inst-border">
              {workspaceRows.map((row) => (
                <InfoRow key={row.label} label={row.label} value={row.value} badge={row.badge} />
              ))}
            </dl>
          ) : (
            <p className="mt-4 text-sm leading-6 text-inst-text-secondary">
              Workspace context will appear when session and batch state are available.
            </p>
          )}
        </section>
      </div>

      {demoMode ? (
        <div className="rounded border border-[#c5d4e6] bg-[#e8eef5] px-4 py-3">
          <div className="flex items-start gap-3">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-inst-blue" aria-hidden="true" />
            <div>
              <p className="text-sm font-semibold text-inst-navy">Walkthrough environment</p>
              <p className="mt-1 text-sm leading-6 text-inst-navy">
                This workspace is optimized for hackathon evaluation, with authentication and service integrations managed through the configured environment.
              </p>
            </div>
          </div>
        </div>
      ) : null}

      <div className="rounded border border-inst-border bg-inst-muted px-4 py-3">
        <p className="text-sm font-semibold text-inst-navy">Security principle</p>
        <p className="mt-1 text-sm leading-6 text-inst-text">Sensitive AI credentials remain server-side.</p>
        <p className="mt-1 text-sm leading-6 text-inst-text-secondary">
          AI requests are mediated by the backend. The browser interface does not receive or transmit provider API
          keys.
        </p>
      </div>
    </div>
  );
}

function InfoRow({ label, value, badge }: { label: string; value: string; badge?: boolean }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 py-3">
      <dt className="sv-label">{label}</dt>
      <dd className="text-sm font-medium text-inst-navy">
        {badge ? <StageBadge value={value} /> : value}
      </dd>
    </div>
  );
}

function StatusTile({
  icon: Icon,
  name,
  status,
  explanation,
}: {
  icon: typeof Server;
  name: string;
  status: string;
  explanation: string;
}) {
  return (
    <div className="rounded border border-inst-border bg-inst-muted px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-inst-blue" aria-hidden="true" />
          <p className="text-sm font-semibold text-inst-navy">{name}</p>
        </div>
        <StageBadge value={status} />
      </div>
      <p className="mt-2 text-sm leading-6 text-inst-text-secondary">{explanation}</p>
    </div>
  );
}
