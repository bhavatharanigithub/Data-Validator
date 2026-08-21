"use client";

import { useState } from "react";
import { FileImage, FileText, Upload } from "lucide-react";
import { ApiError, importOcr, previewOcr } from "@/lib/api";
import type { OcrRecord } from "@/lib/api";

const ACCEPTED_EXTENSIONS = ".pdf,.jpg,.jpeg,.png,.webp,.bmp";
const MAX_UPLOAD_MB = 20;

const EDITABLE_FIELDS: { key: keyof OcrRecord; label: string; numeric?: boolean }[] = [
  { key: "record_id", label: "Record ID" },
  { key: "name", label: "Name" },
  { key: "age", label: "Age", numeric: true },
  { key: "gender", label: "Gender" },
  { key: "district", label: "District" },
  { key: "income", label: "Income", numeric: true },
  { key: "occupation", label: "Occupation" },
  { key: "education", label: "Education" },
  { key: "marital_status", label: "Marital Status" },
  { key: "remarks", label: "Remarks" },
];

function ConfidenceBadge({ band }: { band: string }) {
  const tone: Record<string, string> = {
    high: "border-emerald-200 bg-emerald-50 text-inst-green",
    medium: "border-amber-200 bg-amber-50 text-inst-warning",
    low: "border-red-200 bg-red-50 text-inst-critical",
    unknown: "border-inst-border bg-inst-muted text-inst-text-secondary",
  };
  const label: Record<string, string> = {
    high: "High confidence",
    medium: "Medium confidence",
    low: "Low confidence",
    unknown: "Unknown",
  };
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-semibold ${tone[band] ?? tone.unknown}`}
    >
      {label[band] ?? band}
    </span>
  );
}

type Stage = "idle" | "uploading" | "review" | "importing" | "done";

interface PhotoPdfUploadProps {
  onImported: (result: { batch_id: string; pipeline_run_id?: number | null }) => void | Promise<void>;
}

export function PhotoPdfUpload({ onImported }: PhotoPdfUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState<Stage>("idle");
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [filename, setFilename] = useState<string>("");
  const [pages, setPages] = useState<number>(0);
  const [records, setRecords] = useState<OcrRecord[]>([]);
  const [rawText, setRawText] = useState<string>("");
  const [showRaw, setShowRaw] = useState(false);
  const [importSummary, setImportSummary] = useState<{
    recordsImported: number;
    needingReview: number;
  } | null>(null);

  function reset() {
    setFile(null);
    setStage("idle");
    setStatusMessage("");
    setError(null);
    setFilename("");
    setPages(0);
    setRecords([]);
    setRawText("");
    setShowRaw(false);
    setImportSummary(null);
  }

  async function handleUpload() {
    if (!file) return;
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setError(`File exceeds the ${MAX_UPLOAD_MB} MB upload limit.`);
      return;
    }
    setError(null);
    setStage("uploading");
    const messages = ["Uploading...", "Processing OCR...", "Extracting survey records...", "Preparing records..."];
    let step = 0;
    setStatusMessage(messages[0]);
    const interval = window.setInterval(() => {
      step = Math.min(step + 1, messages.length - 1);
      setStatusMessage(messages[step]);
    }, 1400);
    try {
      const result = await previewOcr(file);
      setFilename(result.filename);
      setPages(result.pages);
      setRecords(result.records);
      setRawText(result.raw_text);
      setStage("review");
    } catch (err) {
      setStage("idle");
      if (err instanceof ApiError) {
        setError(err.message || "OCR processing failed.");
      } else {
        setError("OCR processing failed.");
      }
    } finally {
      window.clearInterval(interval);
    }
  }

  function updateRecord(index: number, key: keyof OcrRecord, value: string) {
    setRecords((prev) =>
      prev.map((rec, i) => {
        if (i !== index) return rec;
        const numericField = key === "age" || key === "income";
        if (numericField) {
          const trimmed = value.trim();
          return { ...rec, [key]: trimmed === "" ? null : Number(trimmed) };
        }
        return { ...rec, [key]: value === "" ? null : value };
      })
    );
  }

  async function handleImport() {
    setError(null);
    setStage("importing");
    try {
      const result = await importOcr(filename, records);
      setImportSummary({
        recordsImported: result.records_imported,
        needingReview: result.records_requiring_review,
      });
      setStage("done");
      await onImported({ batch_id: result.batch_id, pipeline_run_id: result.pipeline_run_id });
    } catch (err) {
      setStage("review");
      if (err instanceof ApiError) {
        setError(err.message || "Unable to import the extracted records.");
      } else {
        setError("Unable to import the extracted records.");
      }
    }
  }

  if (stage === "review" || stage === "importing") {
    const needingReview = records.filter((r) => r.needs_review).length;
    return (
      <div className="mt-5 space-y-4">
        <div>
          <p className="sv-label">OCR extraction preview</p>
          <div className="mt-2 flex flex-wrap gap-4 text-sm text-inst-text">
            <span>
              File: <span className="font-semibold text-inst-navy">{filename}</span>
            </span>
            <span>
              Pages: <span className="font-semibold text-inst-navy">{pages}</span>
            </span>
            <span>
              Records detected: <span className="font-semibold text-inst-navy">{records.length}</span>
            </span>
            {needingReview > 0 ? (
              <span className="text-inst-warning">{needingReview} record(s) need review</span>
            ) : null}
          </div>
        </div>

        <div className="overflow-x-auto rounded border border-inst-border">
          <table className="sv-table">
            <thead>
              <tr>
                <th>Confidence</th>
                {EDITABLE_FIELDS.map((f) => (
                  <th key={f.key}>{f.label}</th>
                ))}
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {records.map((rec, index) => (
                <tr key={index}>
                  <td>
                    <ConfidenceBadge band={rec.record_confidence_band} />
                  </td>
                  {EDITABLE_FIELDS.map((f) => (
                    <td key={f.key}>
                      <input
                        className="sv-control w-full min-w-[7rem]"
                        type={f.numeric ? "number" : "text"}
                        value={rec[f.key] === null || rec[f.key] === undefined ? "" : String(rec[f.key])}
                        onChange={(e) => updateRecord(index, f.key, e.target.value)}
                        disabled={stage === "importing"}
                      />
                    </td>
                  ))}
                  <td>
                    {rec.needs_review ? (
                      <span
                        className="inline-flex items-center rounded border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-inst-warning"
                        title={[...rec.issues, ...rec.warnings].join(" ") || "Needs review"}
                      >
                        Needs review
                      </span>
                    ) : (
                      <span className="inline-flex items-center rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-inst-green">
                        Ready
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <button type="button" className="sv-btn-outline" onClick={() => setShowRaw((v) => !v)}>
            {showRaw ? "Hide raw OCR text" : "View raw OCR text"}
          </button>
          {showRaw ? (
            <pre className="mt-3 max-h-64 overflow-auto rounded border border-inst-border bg-inst-muted p-3 text-xs text-inst-text-secondary">
              {rawText}
            </pre>
          ) : null}
        </div>

        {error ? <p className="text-sm text-inst-critical">{error}</p> : null}

        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            className="sv-btn-outline"
            disabled={stage === "importing"}
            onClick={reset}
          >
            Cancel
          </button>
          <button
            type="button"
            className="sv-btn-compact"
            disabled={stage === "importing" || records.length === 0}
            onClick={handleImport}
          >
            {stage === "importing" ? "Importing..." : `Import ${records.length} Record${records.length === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>
    );
  }

  if (stage === "done" && importSummary) {
    return (
      <div className="mt-5 space-y-2 rounded border border-emerald-200 bg-emerald-50 p-4">
        <p className="text-sm font-semibold text-inst-green">Batch imported successfully</p>
        <p className="text-sm text-inst-text">Source: Photo / PDF</p>
        <p className="text-sm text-inst-text">Records imported: {importSummary.recordsImported}</p>
        {importSummary.needingReview > 0 ? (
          <p className="text-sm text-inst-text">Records requiring review: {importSummary.needingReview}</p>
        ) : null}
        <p className="text-sm text-inst-text-secondary">Redirecting to the batch...</p>
      </div>
    );
  }

  return (
    <div className="mt-5">
      <label
        className="sv-dropzone"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          if (stage === "uploading") return;
          const next = event.dataTransfer.files[0];
          if (next) setFile(next);
        }}
      >
        <input
          type="file"
          accept={ACCEPTED_EXTENSIONS}
          className="sr-only"
          disabled={stage === "uploading"}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        {file ? (
          <>
            {file.type === "application/pdf" ? (
              <FileText className="h-8 w-8 text-inst-blue" aria-hidden="true" />
            ) : (
              <FileImage className="h-8 w-8 text-inst-blue" aria-hidden="true" />
            )}
            <p className="mt-3 text-sm font-semibold text-inst-navy">Ready to upload</p>
            <p className="mt-1 text-sm text-inst-text">{file.name}</p>
            <p className="mt-1 text-xs text-inst-text-secondary">{(file.size / 1024).toFixed(1)} KB</p>
          </>
        ) : (
          <>
            <Upload className="h-8 w-8 text-inst-blue" aria-hidden="true" />
            <p className="mt-3 text-sm font-semibold text-inst-navy">Upload Survey Photo or PDF</p>
            <p className="mt-1 text-sm text-inst-text-secondary">or browse from your computer</p>
            <p className="mt-3 max-w-md text-xs leading-5 text-inst-text-secondary">
              Supported: PDF, JPG, JPEG, PNG, WEBP, BMP. Maximum {MAX_UPLOAD_MB} MB.
            </p>
          </>
        )}
      </label>
      <button className="sv-btn-compact mt-4" disabled={!file || stage === "uploading"} onClick={handleUpload}>
        {stage === "uploading" ? statusMessage || "Processing..." : "Upload File"}
      </button>
      <p className="mt-3 text-xs leading-5 text-inst-text-secondary">
        OCR runs locally. You will be able to review and correct every extracted field before anything is
        imported.
      </p>
      {error ? <p className="mt-3 text-sm text-inst-critical">{error}</p> : null}
    </div>
  );
}
