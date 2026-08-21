# Intelligent Survey Data Validation Platform

Hackathon build frozen through **Phase 11**. Deterministic survey-data intelligence for supervisor review, built survey-agnostic with **PLFS (Periodic Labour Force Survey)** as the first target survey.

Sample extracts are **synthetic/demo data**, not live government survey microdata.

> Turns raw CSV/eSIGMA survey submissions into an explainable, evidence-fused, investigable anomaly dashboard — using deterministic rules/statistics/ML as the source of truth and AI purely as an optional, privacy-conscious explanation layer.

---

## The Problem

Large-scale field surveys (enumerators across thousands of households/clusters/districts) produce data riddled with quality issues: impossible values (age > 100, working hours > 168/week, negative income), enumerator bias/fabrication, referential breaks (records pointing to clusters/districts/enumerators that don't exist), missing identifiers, and statistical drift vs. historical rounds. Manual review doesn't scale — this platform automates ingestion → profiling → multi-signal validation → risk scoring → explainable, investigable dashboard.

---

## Architecture

```
CSV upload  ─┐
             ├─> Standardizer ─> Parquet (data/processed/{batch_id}.parquet)
eSIGMA JSON ─┘
                     │
                     ▼
        SIRL (Survey Intelligence Retrieval Layer)
   deterministic profiling (Pandas/NumPy) + optional AI enrichment
   → dataset / variable / record / enumerator / cluster / district / historical profiles
   → stored in SQLite
                     │
                     ▼
          Unified Validation Engine
   Rules (safe DSL)  +  Statistics (z/IQR/PSI/KS/deviation)  +  ML (Isolation Forest)
                     │
                     ▼
             Evidence Fusion
   weighted combination of all channels → risk_score (0–100) → severity/priority
                     │
                     ▼
        LLM Explanation (optional, structured-evidence-only)
   summary, why_flagged[], recommended_action — deterministic fallback if AI is down
                     │
                     ▼
           Supervisor Dashboard (Next.js)
   KPIs, anomaly queue, record drill-down, hierarchy analytics, investigation, export
```

**Architecture lock (`.cursor/rules`):**
- CSV and eSIGMA are the only two inputs; both converge into one normalized schema.
- Normalized data → Parquet → SIRL → Unified Validation → Evidence Fusion.
- **AI is enrichment/explanation only — never the source of truth.** Scoring stays in Python. AI must not change `risk_score`, `severity`, or `agreement`.
- The complete Parquet dataset is **never** sent to an LLM — only structured summaries/evidence bundles for top-flagged records.
- AI access goes through a vendor-neutral abstraction layer, configured via env vars.
- The deterministic pipeline works end-to-end even if the AI API is unavailable.
- **No Redis, Kafka, Celery, Kubernetes, PostgreSQL, vector databases, LangChain, or LlamaIndex.** Hackathon-scale: SQLite + Parquet only.
- Live eSIGMA is only treated as real if `ESIGMA_BASE_URL` is configured **and** a probe succeeds.

---

## What "SIRL" Means

**SIRL = Survey Intelligence Retrieval Layer** — RAG-inspired structured-data intelligence, **not** traditional document RAG. No text embeddings, no vector search.

1. Reads a completed Parquet batch (never re-touches raw CSV/JSON).
2. Runs deterministic profiling with Pandas/NumPy — no external calls, no embeddings, no vector DB.
3. Builds seven structured profile types: **dataset, variable, record, enumerator, cluster, district, historical.**
4. Optionally enriches variable/dataset profiles with AI-generated context (summaries only, never raw data).
5. Persists everything to SQLite as JSON-compatible structured blobs.
6. Produces a reusable **context object** consumed by Rules, Statistics, ML, and the AI explainer.

SIRL understands and represents context — it does **not** decide anomalies, assign risk, run ML, or generate explanations. Those are downstream phases.

---

## Pipeline Stages

### 1. Ingest → Standardize → Parquet
- Two ingest paths — CSV multipart upload and eSIGMA JSON — both funnel into one canonical internal schema (`record_id`, `hh_id`, `person_id`, `age`, `sex`, `education`, `employment_status`, `working_hours`, `income`, `enumerator_id`, `cluster_id`, `district_code`, `state_code`, `survey_code`, `survey_round`, `visit`, `ref_period`, `collected_at`).
- Both paths produce identical column names, dtypes, and missing-value policy (`NaN` for numeric, `None` for categorical).
- CSVs read with `encoding="utf-8-sig"` to strip BOM; string columns cast to pandas `StringDtype`. Raw file bytes are not stored.
- Written to `data/processed/{batch_id}.parquet`. `batch_id` format: `{SURVEY}_{YYYY}_{MM}_{DD}_{NNN}`.

### 2. SIRL Profiling (deterministic + optional AI enrichment)
- Reads Parquet only. Vectorized Pandas groupby/transform/agg — no row-by-row loops.
- Dataset, variable, record, enumerator/cluster/district, and historical profiles (historical returns `historical_context_available = false` if no prior batch exists — never fabricates history).
- `POST /api/sirl/profile/{batch_id}` is idempotent and rejects batches that aren't `COMPLETED`.
- AI enrichment (`POST /api/sirl/enrich/{batch_id}`) sends summaries only (mean/std/percentiles/district variation/historical change) — never raw records. If `AI_API_KEY` is missing or the call fails, enrichment is skipped and `ai_enriched=false`; the batch never flips to a failure state because of AI.

### 3. Unified Validation
- **Rules** — data, not code. Stored in `validation_rules`, evaluated via a safe DSL (no `eval`/`exec`): single-field, cross-field, range, and structured `when`/`then` conditionals. Referential integrity (must exist in a reference set) is kept explicitly separate from existential integrity (must simply exist). Rules are filtered by the batch's `survey_code` so one survey's rules never leak into another's run. 8 starter rules cover age/hours/income bounds, unemployed-but-nonzero-hours, invalid cluster/district pairing, and referential person/household checks. Vectorized Pandas execution.
- **Statistics** — z-score vs. variable profile (`|z| > 3`), IQR fences (`k = 1.5`), historical deviation, distribution shift (PSI/KS) vs. a prior batch, enumerator- and cluster-level deviation. Kept as a separate evidence channel from rules; re-running doesn't duplicate evidence.
- **ML (Isolation Forest)** — trained per-batch on `age, income, working_hours, education_encoded, employment_encoded, historical_dev, cluster_dev, enumerator_dev`. Output normalized to `[0,1]`. Optional AI channel for top-N high-signal records only (never the full batch); backend never adopts the AI's suggested priority as the actual score.

### 4. Evidence Fusion + Risk Score
Weighted fusion of five channels, each normalized to `[0,1]`:

| Channel | Weight |
|---|---|
| Rules | 0.25 |
| Statistics | 0.25 |
| ML | 0.20 |
| Historical | 0.20 |
| AI context | 0.10 (0 if AI unavailable — weights renormalize) |

`risk_score = round(100 * weighted_sum)`. Priority tiers: `HIGH ≥ 75`, `MEDIUM ≥ 50`, `LOW ≥ 25`, else unflagged/`INFO`. Only records with `risk_score ≥ 25` or any hard rule fire are persisted. Group-level anomalies (`entity_type = district|cluster|enumerator`) are also inserted when historical deviation crosses a threshold.

### 5. Anomaly Classification (`classification.py`)
`risk_score`/`severity` alone do **not** mean "confirmed error." A dedicated `classify_anomaly_status()` is the one authoritative source of truth:
- **`CONFIRMED`** — only if a hard validity rule fired (age/hours/income/household/required-ID/employment-hours bounds). Reference-lookup misses (`*_IN_REFERENCE`) do **not** count as confirmed.
- **`REVIEW`** — statistics + ML agree, or either alone is unusual. Flagged for human review; never described as "invalid."
- **`NORMAL`** — nothing fired, or only a demo reference-list miss.

A second layer (`classify_intelligence`) produces a user-facing label — `VALIDATION_ERROR`, `INVESTIGATION_REQUIRED`, `UNUSUAL_PATTERN`, or `INFORMATIONAL` — plus `primary_detector` and `detector_count`.

### 6. LLM Explanation
For flagged records/groups, sends evidence JSON only, receives `status`, `reason`, `model`, `primary_reason`, `secondary_reason`, `summary`, `what_it_means`, `key_findings[]`, `evidence_explanations[]`, `recommended_action`, `limitations[]`, `explanation_confidence`. Deterministic fallback template if AI is down: *"Risk {n}. Rules fired: ... Statistical: ... ML score: ... Historical: ... Recommended action: Verify with supervisor."* The AI must never override `risk_score`, `severity`, or `anomaly_status`; `REVIEW` records must be called "unusual, needs verification" (not "invalid"); `NORMAL` records must not be described as suspicious.

### 7. Supervisor Dashboard (Next.js)

| Route | Purpose |
|---|---|
| `/login` | Demo auth (role selector: `FIELD_SUPERVISOR` / `SURVEY_ADMIN`) |
| `/` | KPIs: processed, normal, flagged, high risk, enumerators/clusters/districts flagged |
| `/dashboard/ingest` | CSV upload + eSIGMA trigger + batch list |
| `/dashboard/anomalies` | Filterable/paginated anomaly queue (risk, severity, agreement, source, AI status, detector, classification, investigation status, free-text search) |
| `/dashboard/records/[recordId]` | Full record detail: risk assessment, per-source evidence cards, AI explanation, evidence graph (record → rules/statistics/ml → fusion → classification) |
| `/dashboard/analytics` | District/cluster/enumerator Recharts views |
| `/rules` | List rules, enable/disable |
| `/export` | CSV/Excel download links |

Frontend stack: TanStack Query for data fetching, TanStack Table for the anomaly queue, `lucide-react` icons, Tailwind with an "inst-navy"/"inst-blue" institutional color scheme.

### 8. Investigation Workflow
Actions: `VERIFY`, `REQUEST_REENUMERATION`, `MARK_VALID`. Status lifecycle: `OPEN → INVESTIGATING → RESOLVED`. Every action stores actor, notes, timestamp, and a full audit trail (`AuditEvent`: previous_status → new_status, note, timestamp).

### 9. Export
CSV + Excel (via `openpyxl`) for anomalies and batch summaries. **Explicitly no PDF.**

---

## Pipeline Orchestrator (added during build)

Full run-tracking system (`OrchestratorRun` / `OrchestratorStage`) tracking each pipeline stage (`PENDING/PROCESSING/COMPLETED/FAILED/UNAVAILABLE/SKIPPED`) per batch, with a background poller so the frontend shows live progress. `POST /api/pipeline/run/{batch_id}` runs SIRL → validate → optional explanations in one call.

---

## API Surface

Base: `http://localhost:8000/api`. JSON unless noted.

**Health & auth**
- `GET /api/health` → `{status: "ok"}`
- `POST /api/auth/login` → `{access_token, token_type: "bearer"}`

**Ingest**
- `POST /api/ingest/csv` (multipart: `file`, optional `survey_code`)
- `POST /api/ingest/esigma` (`{survey_code, records[], pull, endpoint}`)
- `GET /api/ingest/batches`, `GET /api/ingest/batches/{batch_id}`

**Pipeline**
- `POST /api/pipeline/run/{batch_id}?explain=true`
- `GET /api/pipeline/{run_id}`

**SIRL**
- `POST /api/sirl/profile/{batch_id}`
- `GET /api/sirl/profile/{batch_id}` (+ `/variables/{name}`, `/enumerators/{id}`, `/clusters/{id}`, `/districts/{code}`)
- `POST /api/sirl/enrich/{batch_id}`

**Validation**
- `POST /api/validate/{batch_id}`
- `GET /api/rules`, `PATCH /api/rules/{rule_id}`

**Anomalies & dashboard**
- `GET /api/dashboard/summary?batch_id=`
- `GET /api/anomalies` (filters: `batch_id`, `min_risk_score`, `severity`, `agreement`, `evidence_source`, `ai_status`, `detector_type`, `classification`, `classification_scope`, `q`, `page`, `page_size`)
- `GET /api/anomalies/{id}` / `GET /api/validation/explanations/{batch_id}/{record_id}`
- `POST /api/anomalies/{id}/explain`

**Investigation**
- `POST /api/anomalies/{id}/actions`, `GET /api/investigations`

**Analytics**
- `GET /api/analytics/districts|clusters|enumerators?batch_id=`

**Export**
- `GET /api/export/anomalies.csv|xlsx?batch_id=`

---

## Database Schema (SQLite)

- `ingestion_batches` — `batch_id`, `source`, `status`, `records`, `columns`, `parquet_path`, `survey_code`, timestamps
- `dataset_profiles`, `variable_profiles`, `record_profiles`, `enumerator_profiles`, `cluster_profiles`, `district_profiles`, `historical_profiles` — SIRL output, JSON blobs for nested structures
- `validation_rules` — rule DSL storage
- `unified_risk_assessments` — `risk_score`, `severity`, `agreement`, `evidence_confidence`, `anomaly_status`, `classification_reason`, `source_scores_json`, `source_severities_json`, `evidence_refs_json`
- `anomalies` / `anomaly_evidence` — persisted flagged records + per-channel evidence rows (`channel`, `code`, `score`, `payload_json`)
- `investigations` — `id`, `anomaly_id`, `user_id`, `action`, `status`, `notes`, `finding`, `final_classification`, timestamps
- `audit_events` — investigation status-change trail
- Indexes: `anomalies(batch_id, risk_score)`, `anomalies(district_code)`, `anomalies(enumerator_id)`, `anomalies(status)`, `variable_profiles(batch_id, variable_name)`

---

## Sample End-to-End Output

Record `M033`, batch `BATCH_2026_08_15_111911_csv_e12de2`:
- `risk_score: 98.91`, `severity: CRITICAL`, `agreement: strong`, `anomaly_status: CONFIRMED`, `classification_reason: hard_rule_violation`
- **Rule fired:** `working_hours = 190` exceeds `WORKING_HOURS_MAX` (168)
- **Statistics:** dataset z-score 4.59 (threshold 3.0), district z-score 3.77, cluster z-score 3.46, enumerator z-score 2.45
- **ML:** Isolation Forest anomaly score 95.64 (HIGH)
- **AI explanation** (model: `deepseek/deepseek-v4-flash`): plain-language summary tying together the rule violation, statistical outlier status vs. every peer group, and the ML flag, with `recommended_action` and stated `explanation_confidence`.

---

## Tech Stack

**Backend**
- FastAPI + Uvicorn
- SQLAlchemy 2 + SQLite (`data/app.db`)
- Pandas, NumPy, SciPy, scikit-learn (Isolation Forest), PyArrow (Parquet)
- httpx (eSIGMA + AI HTTP calls)
- pydantic-settings for config, `.env` for secrets
- pytest (60+ tests)

**Frontend**
- Next.js (App Router), TypeScript
- Tailwind CSS
- Recharts (analytics), TanStack Table + TanStack Query
- lucide-react icons

**AI**
- Vendor-neutral provider abstraction via env vars (`AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`, `AI_TIMEOUT_SECONDS`) — tested with `deepseek/deepseek-v4-flash`
- Mock AI mode for deterministic testing

**Explicitly excluded:** Redis, Kafka, Celery, Kubernetes, PostgreSQL, vector databases, LangChain, LlamaIndex, embeddings, external profiling libraries, PDF export.

---

## Runtime Behavior When AI Is Down

| Stage | Behavior |
|---|---|
| SIRL profiling | Full deterministic stats run normally; `ai_enriched = false` |
| Validation | Rules + stats + Isolation Forest run normally; AI channel weight = 0 (others renormalize) |
| Explanation | Deterministic template used instead of LLM text |
| Dashboard | Shows "AI unavailable" status badge, everything else functions |
| Batch status | Never flips to a failure state purely because AI failed |

---

## Non-Goals (Hackathon Scope)

- Real eSIGMA production auth / VPN integration
- Vector DB / document RAG
- Deep learning, AutoML, streaming message bus
- PDF reports
- Multi-tenant SaaS / full production RBAC
- Sending full datasets to any LLM
- MLOps leaderboards / formal model training service

---

## Differentiators

1. **Multi-signal evidence fusion, not a single model.** Rules, statistics, and ML vote independently; the UI shows which sources agreed, not a black-box number.
2. **AI is enrichment, never the source of truth.** The deterministic pipeline works completely with AI off.
3. **Privacy/cost-conscious AI usage.** The full dataset never touches an LLM; only compact structured evidence summaries for top-flagged records.
4. **Confirmed vs. Review distinction.** Avoids the "everything statistically unusual = accused of fraud" trap — only a genuine hard-rule violation is `CONFIRMED`; stats/ML-only signals go to a `REVIEW` queue with careful language.
5. **Hierarchical, not just record-level.** Flags aggregate patterns (enumerator bias, cluster/district drift vs. historical baselines) — catches systemic field-level issues, not just one-off typos.
6. **Survey-agnostic core.** Canonical internal schema + a PLFS mapping table; rules scoped by `survey_code` so a second survey can be onboarded without re-architecting or leaking rules.
7. **Explainable by design.** Every flagged record has a full evidence graph plus a plain-language AI explanation with stated confidence and limitations.
8. **Graceful degradation everywhere.** AI down, no historical baseline, missing columns, unknown reference codes — every case has a defined, tested fallback.

---

## Environment

Copy `.env.example` to `.env` at the **repository root**. `.env` is gitignored. Do not put secrets in frontend code.

Required for any shared/demo host:
- `JWT_SECRET` — replace the placeholder; do not ship the example value
- `AUTH_ADMIN_PASSWORD` / `AUTH_SUPERVISOR_PASSWORD` — change default hackathon passwords
- `AUTH_COOKIE_SECURE=true` when serving over HTTPS
- Persistent disk for `data/app.db` and `data/processed/` (SQLite + Parquet). An ephemeral filesystem will lose batches after restart.

Default login accounts are **hackathon/demo only**:
- `admin` / `admin` — `SURVEY_ADMIN`
- `supervisor` / `supervisor` — `FIELD_SUPERVISOR`

`AUTH_DEMO_MODE=true` also seeds the optional demo username from `SUPERVISOR_USER`.

Leave `AI_*` and `ESIGMA_*` empty to run fully deterministic. `ESIGMA_MOCK_MODE=true` uses the bundled fixture.

Frontend API:
- Same-origin (recommended): leave `NEXT_PUBLIC_API_BASE_URL` empty. Next.js rewrites `/api/*` to `BACKEND_URL` (default `http://127.0.0.1:8000`).
- Split origin: set `NEXT_PUBLIC_API_BASE_URL` to the API origin and configure CORS. Cookies need a shared site or HTTPS `Secure` + appropriate `SameSite`.

---

## Backend

Python 3.11+.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health: `GET /api/health` → `{"status":"ok"}`.

Tests:

```bash
cd backend
.venv/bin/pytest -q
```

---

## Frontend

Node.js 20+.

```bash
cd frontend
npm install
npm run build
npm run start -- --port 3000
```

Open http://localhost:3000. Sign in, ingest a sample CSV from `data/samples/`, then **Run validation** on the batch page (ingestion does not auto-run the full pipeline).

---

## Persistence (deployment)

This app is process + local files, not a hosted blueprint. Keep:
- SQLite: `DATABASE_URL` / `data/app.db`
- Parquet: `DATA_DIR/processed/`

If those paths are not on a persistent volume, data will disappear on remount.

---

## Security Notes

- Secrets belong in environment variables, never in the Next.js bundle
- Session cookie: httpOnly, SameSite=lax; set `AUTH_COOKIE_SECURE=true` on HTTPS
- Placeholder JWT/demo passwords are not production identity
- Core validation APIs intentionally remain unauthenticated (login gates the UI only, by explicit hackathon-scope decision)
- Do not claim live eSIGMA or live AI unless those env vars are set and health/probe succeed
