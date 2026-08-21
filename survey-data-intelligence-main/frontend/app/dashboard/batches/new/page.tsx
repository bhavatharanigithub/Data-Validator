"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Database, FileSpreadsheet, ScanLine, Upload } from "lucide-react";
import { ErrorState } from "@/components/status";
import { PhotoPdfUpload } from "@/components/ocr/photo-pdf-upload";
import { getEsigmaStatus, ingestCsv, ingestEsigma } from "@/lib/api";
import { writePipelineRun, writeSelectedBatch } from "@/lib/session-state";

const PIPELINE_STAGES = ["Ingestion", "Parquet", "SIRL", "Rules", "Statistics", "Intelligence", "ML", "Fusion / Risk"];

export default function NewBatchPage() {
  const queryClient = useQueryClient();
  const esigma = useQuery({ queryKey: ["esigma-status"], queryFn: getEsigmaStatus, retry: false });
  const [source, setSource] = useState<"csv" | "esigma" | "photo_pdf">("csv");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function afterIngest(result: { batch_id?: string; pipeline_run_id?: number | null }) {
    if (!result.batch_id) throw new Error("missing batch_id");
    writeSelectedBatch(result.batch_id);
    if (result.pipeline_run_id) writePipelineRun(result.batch_id, result.pipeline_run_id);
    await queryClient.invalidateQueries({ queryKey: ["batches"] });
    const runQuery = result.pipeline_run_id ? `?run=${result.pipeline_run_id}` : "";
    window.location.assign(`/dashboard/batches/${encodeURIComponent(result.batch_id)}${runQuery}`);
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="sv-label">New batch</p>
        <h1 className="mt-1 text-2xl font-semibold text-inst-navy">Ingest survey data</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-inst-text-secondary">
          Upload a survey extract or ingest data from a configured source. The validation and quality pipeline begins
          automatically after ingestion.
        </p>
      </div>

      <section className="sv-card p-5">
        <p className="sv-label">Data source</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className="sv-source-tab" aria-pressed={source === "csv"} onClick={() => setSource("csv")}>
            Upload CSV
          </button>
          <button type="button" className="sv-source-tab" aria-pressed={source === "esigma"} onClick={() => setSource("esigma")}>
            eSIGMA
          </button>
          <button
            type="button"
            className="sv-source-tab"
            aria-pressed={source === "photo_pdf"}
            onClick={() => setSource("photo_pdf")}
          >
            Photo / PDF
          </button>
        </div>

        {source === "csv" ? (
          <div className="mt-5">
            <label
              className="sv-dropzone"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                if (submitting) return;
                const next = event.dataTransfer.files[0];
                if (next) setFile(next);
              }}
            >
              <input
                type="file"
                accept=".csv,text/csv"
                className="sr-only"
                disabled={submitting}
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
              {file ? (
                <>
                  <FileSpreadsheet className="h-8 w-8 text-inst-blue" aria-hidden="true" />
                  <p className="mt-3 text-sm font-semibold text-inst-navy">Ready to upload</p>
                  <p className="mt-1 text-sm text-inst-text">{file.name}</p>
                  <p className="mt-1 text-xs text-inst-text-secondary">{(file.size / 1024).toFixed(1)} KB</p>
                </>
              ) : (
                <>
                  <Upload className="h-8 w-8 text-inst-blue" aria-hidden="true" />
                  <p className="mt-3 text-sm font-semibold text-inst-navy">Drop your CSV file here</p>
                  <p className="mt-1 text-sm text-inst-text-secondary">or browse from your computer</p>
                  <p className="mt-3 max-w-md text-xs leading-5 text-inst-text-secondary">
                    CSV files are processed through the survey validation and quality pipeline.
                  </p>
                </>
              )}
            </label>
            <button
              className="sv-btn-compact mt-4"
              disabled={!file || submitting}
              onClick={async () => {
                if (!file || submitting) return;
                setError(null);
                setSubmitting(true);
                try {
                  const result = await ingestCsv(file);
                  await afterIngest(result);
                } catch {
                  setSubmitting(false);
                  setError("Unable to ingest the selected file.");
                }
              }}
            >
              {submitting && source === "csv" ? "Uploading..." : "Submit CSV"}
            </button>
            <p className="mt-3 text-xs leading-5 text-inst-text-secondary">
              Analysis starts automatically after upload. You do not need to run validation separately.
            </p>
          </div>
        ) : source === "esigma" ? (
          <div className="mt-5">
            <div className="flex items-start gap-3">
              <span className="sv-metric-icon bg-[#e8eef5] text-inst-blue" aria-hidden="true">
                <Database className="h-4 w-4" />
              </span>
              <div>
                <h2 className="text-lg font-semibold text-inst-navy">eSIGMA</h2>
                <p className="text-sm text-inst-text-secondary">Backend-mediated ingest</p>
              </div>
            </div>
            {esigma.isPending ? <p className="mt-4 text-sm text-inst-text-secondary">Checking connection status…</p> : null}
            {esigma.isError ? (
              <div className="mt-4">
                <ErrorState message="Unable to load eSIGMA connection status." onRetry={() => esigma.refetch()} />
              </div>
            ) : null}
            {esigma.isSuccess ? (
              <dl className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded border border-inst-border bg-inst-muted px-3 py-3">
                  <dt className="sv-label">Connection</dt>
                  <dd className="mt-1 text-sm font-semibold uppercase text-inst-navy">
                    {esigma.data.status ?? (esigma.data.configured ? "configured" : "not configured")}
                  </dd>
                </div>
                <div className="rounded border border-inst-border bg-inst-muted px-3 py-3">
                  <dt className="sv-label">Mock mode</dt>
                  <dd className="mt-1 text-sm font-semibold text-inst-navy">{esigma.data.mock_mode ? "Yes" : "No"}</dd>
                </div>
              </dl>
            ) : null}
            {esigma.data?.notice ? <p className="mt-3 text-sm text-inst-text">{esigma.data.notice}</p> : null}
            <p className="mt-3 text-xs leading-5 text-inst-text-secondary">
              Connection credentials are handled by the backend and are not exposed to the browser.
            </p>
            <button
              className="sv-btn-compact mt-4"
              disabled={submitting}
              onClick={async () => {
                if (submitting) return;
                setError(null);
                setSubmitting(true);
                try {
                  const result = await ingestEsigma();
                  await afterIngest(result);
                } catch {
                  setSubmitting(false);
                  setError("Unable to ingest from eSIGMA.");
                }
              }}
            >
              {submitting && source === "esigma" ? "Ingesting..." : "Ingest from eSIGMA"}
            </button>
          </div>
        ) : (
          <div>
            <div className="flex items-start gap-3">
              <span className="sv-metric-icon bg-[#e8eef5] text-inst-blue" aria-hidden="true">
                <ScanLine className="h-4 w-4" />
              </span>
              <div>
                <h2 className="text-lg font-semibold text-inst-navy">Photo / PDF</h2>
                <p className="text-sm text-inst-text-secondary">
                  Local OCR extraction. Extracted records are reviewable and editable before import.
                </p>
              </div>
            </div>
            <PhotoPdfUpload onImported={afterIngest} />
          </div>
        )}
      </section>

      {error ? <ErrorState message={error} onRetry={() => setError(null)} /> : null}

      <section className="sv-card p-5">
        <h2 className="text-sm font-semibold text-inst-navy">Processing pipeline</h2>
        <p className="mt-1 text-sm text-inst-text-secondary">
          Once ingested, the dataset moves through the configured quality pipeline.
        </p>
        <ol className="mt-4 flex flex-wrap gap-2">
          {PIPELINE_STAGES.map((stage, index) => (
            <li key={stage} className="flex items-center gap-2 text-sm text-inst-navy">
              <span className="sv-chip">{stage}</span>
              {index < PIPELINE_STAGES.length - 1 ? <span className="text-inst-text-secondary">→</span> : null}
            </li>
          ))}
        </ol>
        <p className="mt-4 text-xs leading-5 text-inst-text-secondary">
          Every ingested dataset is evaluated through the configured validation and quality pipeline before records are
          surfaced for review.
        </p>
      </section>
    </div>
  );
}
