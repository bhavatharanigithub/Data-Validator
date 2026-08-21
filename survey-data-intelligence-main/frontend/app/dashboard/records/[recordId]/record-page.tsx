"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useSelectedBatch } from "@/components/shell";
import { EmptyState, ErrorState, InvestigationStatusBadge, SeverityBadge } from "@/components/status";
import {
  addInvestigationNote,
  createInvestigation,
  getInvestigationAudit,
  getRecordDetail,
  listInvestigations,
  patchInvestigation,
  runRecordExplanation,
} from "@/lib/api";
import type { SourceCard } from "@/lib/api/types";
import { apiErrorMessage, explanationConfidenceLabel, resolveRouteParam } from "@/lib/batch-detail-state";
import { ApiError } from "@/lib/api/client";

const ACTIONS = [
  { action: "REVIEW", label: "Start Review", className: "sv-btn-compact" },
  { action: "REQUEST_REENUMERATION", label: "Request Re-enumeration", className: "sv-btn-warning-outline" },
  { action: "ESCALATE", label: "Escalate", className: "sv-btn-danger-outline" },
  { action: "MARK_VALID", label: "Mark Valid", className: "sv-btn-success" },
  { action: "MARK_INVALID", label: "Mark Invalid", className: "sv-btn-danger" },
] as const;

const SOURCE_META: Record<string, { title: string; hint: string }> = {
  rules: { title: "Rules", hint: "Deterministic validation evidence" },
  statistics: { title: "Statistics", hint: "Statistical unusualness" },
  ml: { title: "ML", hint: "Machine-learning anomaly signal" },
  intelligence: { title: "Intelligence", hint: "Quality detector signals" },
};

function sourceMeta(source: string) {
  return SOURCE_META[source] ?? { title: source, hint: "" };
}

function EvidenceSourceCard({ card }: { card: SourceCard }) {
  const meta = sourceMeta(card.source);
  return (
    <article className="sv-card p-4">
      <p className="sv-label">{meta.title}</p>
      {meta.hint ? <p className="mt-1 text-xs leading-5 text-inst-text-secondary">{meta.hint}</p> : null}
      <p className="mt-2 text-xs font-semibold uppercase tracking-wide text-inst-navy">{card.status}</p>
      <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
        <div>
          <dt className="sv-label">Score</dt>
          <dd className="mt-1 tabular-nums font-semibold text-inst-navy">{card.score ?? "—"}</dd>
        </div>
        <div>
          <dt className="sv-label">Severity</dt>
          <dd className="mt-1">
            {card.severity ? <SeverityBadge value={card.severity} /> : <span className="text-inst-text-secondary">—</span>}
          </dd>
        </div>
        <div>
          <dt className="sv-label">Detections</dt>
          <dd className="mt-1 tabular-nums font-semibold text-inst-navy">{card.detections}</dd>
        </div>
      </dl>
      <ul className="mt-3 space-y-2 text-xs text-inst-text-secondary">
        {(card.items ?? []).length === 0 ? <li>No persisted evidence rows.</li> : null}
        {(card.items ?? []).map((item, index) => (
          <li key={index} className="border-t border-inst-border pt-2 text-inst-text">
            {item.code || item.detector || item.model_type} {item.field || item.variable || ""}
            {item.score != null ? ` · score ${item.score}` : ""}
            {item.anomaly_score != null ? ` · anomaly ${item.anomaly_score}` : ""}
            {item.observed_value != null ? ` · observed ${String(item.observed_value)}` : ""}
            {item.expected ? ` · expected ${item.expected}` : ""}
            {item.severity ? ` · ${item.severity}` : ""}
          </li>
        ))}
      </ul>
    </article>
  );
}

export default function RecordPage() {
  const params = useParams<{ recordId: string }>();
  const search = useSearchParams();
  const selected = useSelectedBatch();
  const batchId = search.get("batchId") || selected;
  const recordId = resolveRouteParam(params.recordId);
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["record", batchId, recordId],
    queryFn: () => getRecordDetail(batchId!, recordId),
    enabled: Boolean(batchId && recordId),
  });
  const cases = useQuery({
    queryKey: ["investigation-for-record", batchId, recordId],
    queryFn: () => listInvestigations({ batch_id: batchId!, record_id: recordId }),
    enabled: Boolean(batchId && recordId),
  });
  const investigation = cases.data?.items[0];
  const audit = useQuery({
    queryKey: ["investigation-audit", investigation?.id],
    queryFn: () => getInvestigationAudit(investigation!.id),
    enabled: Boolean(investigation?.id),
  });
  const [note, setNote] = useState("");
  const ensure = useMutation({
    mutationFn: async (action?: string) => {
      const current = investigation ?? (await createInvestigation(batchId!, recordId));
      if (action) await patchInvestigation(current.id, { action });
      return current;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["investigation-for-record", batchId, recordId] });
      queryClient.invalidateQueries({ queryKey: ["investigation-audit"] });
      queryClient.invalidateQueries({ queryKey: ["investigations"] });
      queryClient.invalidateQueries({ queryKey: ["record", batchId, recordId] });
    },
  });
  const explain = useMutation({
    mutationFn: () => runRecordExplanation(batchId!, recordId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["record", batchId, recordId] });
      queryClient.invalidateQueries({ queryKey: ["anomalies"] });
    },
  });
  const saveNote = useMutation({
    mutationFn: async () => {
      const current = investigation ?? (await createInvestigation(batchId!, recordId));
      return addInvestigationNote(current.id, note);
    },
    onSuccess: () => {
      setNote("");
      queryClient.invalidateQueries({ queryKey: ["investigation-for-record", batchId, recordId] });
      queryClient.invalidateQueries({ queryKey: ["investigation-audit"] });
    },
  });

  if (!batchId) return <EmptyState title="No batch selected" detail="Select a batch to inspect this record." />;
  if (query.isError) {
    const status = query.error instanceof ApiError ? query.error.status : 0;
    if (status === 404) return <EmptyState title="Record not found" detail="This record is not in the selected batch." />;
    return <ErrorState message={apiErrorMessage(query.error, "Record detail could not be loaded.")} onRetry={() => query.refetch()} />;
  }
  const data = query.data;
  if (data && !data.available) return <EmptyState title="Record unavailable" detail={data.message || "No fused assessment for this record."} />;
  const assessment = data?.assessment;
  if (!assessment) return <p className="text-sm text-inst-text-secondary">Loading record…</p>;

  return (
    <div className="space-y-6">
      <header>
        <p className="sv-label">Investigation</p>
        <div className="mt-1 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-inst-navy">{assessment.record_id}</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-inst-text-secondary">
              Review record evidence and determine the appropriate supervisory action.
            </p>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-inst-text">
              Unusual pattern detected — investigation required unless a deterministic validation rule failed. Risk is an
              investigation priority, not a fraud probability.
            </p>
          </div>
          <dl className="sv-card grid grid-cols-2 gap-x-6 gap-y-3 p-4 sm:grid-cols-4">
            <div>
              <dt className="sv-label">Risk</dt>
              <dd className="mt-1 text-lg font-semibold tabular-nums text-inst-navy">
                {assessment.risk_score != null ? `${assessment.risk_score.toFixed(0)} / 100` : "—"}
              </dd>
            </div>
            <div>
              <dt className="sv-label">Severity</dt>
              <dd className="mt-1">
                <SeverityBadge value={assessment.severity} />
              </dd>
            </div>
            <div>
              <dt className="sv-label">Status</dt>
              <dd className="mt-1">
                {investigation?.status ? (
                  <InvestigationStatusBadge value={investigation.status} />
                ) : (
                  <span className="text-sm text-inst-text-secondary">None</span>
                )}
              </dd>
            </div>
            <div>
              <dt className="sv-label">Priority</dt>
              <dd className="mt-1">
                <SeverityBadge value={investigation?.priority ?? assessment.severity} />
              </dd>
            </div>
          </dl>
        </div>
      </header>

      {data?.escalation_applied ? (
        <div className="sv-alert-critical">
          <p className="font-semibold">High-risk escalation</p>
          <p className="mt-1">{data.escalation_reason}</p>
        </div>
      ) : null}

      <section>
        <h2 className="text-sm font-semibold text-inst-navy">Evidence overview</h2>
        <p className="mt-1 text-sm text-inst-text-secondary">Persisted signals from each evidence source. The frontend does not compute these values.</p>
        <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {data?.sources?.map((card) => (
            <EvidenceSourceCard key={card.source} card={card} />
          ))}
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="sv-card p-5">
          <h2 className="text-sm font-semibold text-inst-navy">Deterministic assessment</h2>
          <p className="mt-2 text-xs leading-5 text-inst-text-secondary">
            Flagged records require review. Statistical or ML signals are not proof of an incorrect response.
          </p>
          <dl className="mt-4 grid gap-3 sm:grid-cols-2">
            <div>
              <dt className="sv-label">Anomaly status</dt>
              <dd className="mt-1 text-sm font-semibold uppercase text-inst-navy">{assessment.anomaly_status ?? "—"}</dd>
            </div>
            <div>
              <dt className="sv-label">Classification</dt>
              <dd className="mt-1 text-sm font-medium text-inst-navy">{assessment.classification_reason ?? "—"}</dd>
            </div>
            <div>
              <dt className="sv-label">Risk score</dt>
              <dd className="mt-1 text-sm font-semibold tabular-nums text-inst-navy">{assessment.risk_score ?? "—"}</dd>
            </div>
            <div>
              <dt className="sv-label">Severity</dt>
              <dd className="mt-1">
                <SeverityBadge value={assessment.severity} />
              </dd>
            </div>
            <div>
              <dt className="sv-label">Agreement</dt>
              <dd className="mt-1 text-sm font-medium uppercase text-inst-navy">{assessment.agreement ?? "—"}</dd>
            </div>
            <div>
              <dt className="sv-label">Sources</dt>
              <dd className="mt-1 text-sm text-inst-navy">{(assessment.available_sources ?? []).join(" · ") || "none"}</dd>
            </div>
          </dl>
          <p className="mt-4 text-xs text-inst-text-secondary">Deterministic assessment from fusion. The frontend does not compute these values.</p>
        </section>

        <section className="sv-ai-panel rounded p-5">
          <h2 className="text-sm font-semibold text-inst-navy">AI-assisted interpretation</h2>
          <p className="mt-1 text-xs leading-5 text-inst-text-secondary">
            AI-assisted explanation based on the available survey evidence. AI explains the available evidence. AI does
            not determine the final outcome.
          </p>
          {assessment.ai_explanation_status === "not_required" && data?.explanation?.status !== "available" ? (
            <p className="mt-3 text-sm text-inst-text">No review signal detected. AI explanation not required.</p>
          ) : data?.explanation?.status === "available" ? (
            <div className="mt-3 space-y-4 text-sm text-inst-text">
              <div>
                <p className="sv-label">Why this record was flagged</p>
                <p className="mt-1 leading-6">{data.explanation.primary_reason || "—"}</p>
              </div>
              <div>
                <p className="sv-label">Why we are concerned</p>
                <p className="mt-1 leading-6">{data.explanation.secondary_reason || "—"}</p>
              </div>
              <div>
                <p className="sv-label">What this means</p>
                <p className="mt-1 leading-6">{data.explanation.what_it_means || data.explanation.summary || "—"}</p>
              </div>
              <div>
                <p className="sv-label">What to check first</p>
                <p className="mt-1 leading-6">{data.explanation.recommended_action || "—"}</p>
              </div>
              {(data.explanation.key_findings ?? []).length ? (
                <div>
                  <p className="sv-label">Possible causes</p>
                  <ul className="mt-1 list-disc space-y-1 pl-5 leading-6">
                    {(data.explanation.key_findings ?? []).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {explanationConfidenceLabel(data.explanation.explanation_confidence) ? (
                <div>
                  <p className="sv-label">Confidence</p>
                  <p className="mt-1">{explanationConfidenceLabel(data.explanation.explanation_confidence)}</p>
                </div>
              ) : null}
              <details className="rounded border border-inst-border bg-inst-surface p-3">
                <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-inst-navy">
                  Technical evidence
                </summary>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
                  {(data.explanation.evidence_explanations ?? []).length
                    ? (data.explanation.evidence_explanations ?? []).map((item) => (
                        <li key={`${item.source}-${item.finding}`}>
                          {item.source}: {item.finding}
                        </li>
                      ))
                    : null}
                </ul>
                {(data.explanation.limitations ?? []).length ? (
                  <div className="mt-3">
                    <p className="sv-label">Limitations</p>
                    <ul className="mt-1 list-disc space-y-1 pl-5">
                      {(data.explanation.limitations ?? []).map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </details>
              <p className="text-xs leading-5 text-inst-text-secondary">
                Advisory only — supervisor decides. AI does not calculate risk.
              </p>
            </div>
          ) : (
            <div className="mt-3 space-y-3 text-sm text-inst-text">
              <p>
                {data?.explanation?.status === "generating"
                  ? "AI explanation is generating."
                  : data?.explanation?.status === "unavailable"
                    ? `AI explanation unavailable${data.explanation.reason ? ` (${data.explanation.reason})` : ""}. Deterministic evidence remains reviewable.`
                    : assessment.ai_explanation_status === "not_required"
                      ? "No review signal detected. AI explanation not required."
                      : "AI explanation is generating automatically."}
              </p>
              {data?.explanation?.status === "unavailable" ? (
                <button
                  type="button"
                  className="sv-btn-outline"
                  disabled={explain.isPending}
                  onClick={() => explain.mutate()}
                >
                  {explain.isPending ? "Retrying…" : "Retry explanation"}
                </button>
              ) : null}
            </div>
          )}
        </section>
      </div>

      <section className="sv-card p-5">
        <h2 className="text-sm font-semibold text-inst-navy">Supervisory action</h2>
        <p className="mt-1 text-xs leading-5 text-inst-text-secondary">
          AI recommendations are not executed automatically.
        </p>
        <dl className="mt-4 grid gap-3 sm:grid-cols-3">
          <div>
            <dt className="sv-label">Current status</dt>
            <dd className="mt-1">
              {investigation?.status ? (
                <InvestigationStatusBadge value={investigation.status} />
              ) : (
                <span className="text-sm text-inst-text-secondary">None</span>
              )}
            </dd>
          </div>
          <div>
            <dt className="sv-label">Assigned supervisor</dt>
            <dd className="mt-1 text-sm font-medium text-inst-navy">{investigation?.assigned_to ?? "—"}</dd>
          </div>
          <div>
            <dt className="sv-label">Priority</dt>
            <dd className="mt-1">
              <SeverityBadge value={investigation?.priority ?? assessment.severity} />
            </dd>
          </div>
        </dl>
        {ensure.isError ? (
          <div className="sv-alert-critical mt-4">The investigation action could not be saved.</div>
        ) : null}
        <div className="mt-4 flex flex-wrap gap-2">
          {ACTIONS.map((item) => (
            <button
              key={item.action}
              type="button"
              className={`${item.className} disabled:opacity-40`}
              onClick={() => ensure.mutate(item.action)}
              disabled={ensure.isPending}
            >
              {item.label}
            </button>
          ))}
        </div>
      </section>

      <section className="sv-card p-5">
        <h2 className="text-sm font-semibold text-inst-navy">Add note</h2>
        {saveNote.isError ? <div className="sv-alert-critical mt-3">The note could not be saved.</div> : null}
        <label className="mt-3 block text-sm text-inst-text">
          Note
          <textarea
            className="sv-control mt-1 w-full"
            rows={3}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            aria-label="Add note"
          />
        </label>
        <button
          type="button"
          className="sv-btn-compact mt-3 disabled:opacity-40"
          disabled={!note.trim() || saveNote.isPending}
          onClick={() => saveNote.mutate()}
        >
          {saveNote.isPending ? "Saving…" : "Add Note"}
        </button>
      </section>

      <section className="sv-card p-5">
        <h2 className="text-sm font-semibold text-inst-navy">Investigation timeline</h2>
        <ol className="mt-4 space-y-0 border-l border-inst-border">
          {(audit.data ?? []).map((event) => (
            <li key={event.id} className="relative py-3 pl-5">
              <span className="absolute -left-1.5 top-5 h-3 w-3 rounded-full border border-inst-border bg-inst-blue" aria-hidden="true" />
              <p className="text-xs text-inst-text-secondary">
                {event.timestamp ? new Date(event.timestamp).toLocaleString() : "—"}
              </p>
              <p className="mt-1 text-sm font-semibold text-inst-navy">{event.user_id}</p>
              <p className="mt-0.5 text-sm text-inst-text">{event.action}</p>
              {event.previous_status && event.new_status ? (
                <p className="mt-1 text-xs text-inst-text-secondary">
                  {event.previous_status} → {event.new_status}
                </p>
              ) : null}
              {event.note ? <p className="mt-1 text-sm text-inst-text">{event.note}</p> : null}
            </li>
          ))}
          {!audit.data?.length ? (
            <li className="py-3 pl-5 text-sm text-inst-text-secondary">No audit events yet. Start a review to begin the trail.</li>
          ) : null}
        </ol>
      </section>
    </div>
  );
}
