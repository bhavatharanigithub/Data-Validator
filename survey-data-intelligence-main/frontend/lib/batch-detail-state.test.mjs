import assert from "node:assert/strict";
import test from "node:test";

function resolveRouteParam(value) {
  if (Array.isArray(value)) return String(value[0] ?? "");
  return typeof value === "string" ? value : "";
}

function asStages(run) {
  const stages = run?.stages;
  return Array.isArray(stages) ? stages.filter((stage) => stage && typeof stage.stage === "string") : [];
}

function apiErrorMessage(error, fallback) {
  const status = error?.status;
  if (status === 401) return "You are not signed in.";
  if (status === 403) return "You do not have access to this batch.";
  if (status === 404) return "This batch was not found.";
  if (status === 0 || status >= 500) return "The validation service is unavailable.";
  if (status) return `${fallback} (HTTP ${status})`;
  return fallback;
}

function aiBatchLabel(run, items) {
  const stage = asStages(run).find((row) => row.stage === "EXPLANATION");
  if (run?.status === "RUNNING" || stage?.status === "PROCESSING") return "Generating";
  const rows = Array.isArray(items) ? items : [];
  const needed = rows.filter((row) => row.ai_explanation_status !== "not_required");
  const available = needed.filter((row) => row.ai_explanation_status === "available").length;
  const unavailable = needed.filter((row) => row.ai_explanation_status === "unavailable").length;
  if (stage?.status === "UNAVAILABLE" && available === 0) return "Unavailable";
  if (!needed.length) return "Not required";
  if (available === needed.length) return "Complete";
  if (available > 0 && unavailable > 0) return "Partial";
  if (unavailable === needed.length) return "Unavailable";
  if (available > 0 && available < needed.length) return "Partial";
  return "Generating";
}

test("dynamic batch route param may be a string or array", () => {
  assert.equal(resolveRouteParam("BATCH_1"), "BATCH_1");
  assert.equal(resolveRouteParam(["BATCH_1"]), "BATCH_1");
  assert.equal(resolveRouteParam(undefined), "");
});

test("missing pipeline stages do not throw", () => {
  assert.deepEqual(asStages(undefined), []);
  assert.deepEqual(asStages({}), []);
  assert.deepEqual(asStages({ stages: null }), []);
  assert.deepEqual(asStages({ stages: [{ stage: "FUSION", status: "COMPLETED" }] }).map((s) => s.stage), [
    "FUSION",
  ]);
});

test("API status codes map to UI copy instead of crashing", () => {
  assert.equal(apiErrorMessage({ status: 401 }, "fail"), "You are not signed in.");
  assert.equal(apiErrorMessage({ status: 403 }, "fail"), "You do not have access to this batch.");
  assert.equal(apiErrorMessage({ status: 404 }, "fail"), "This batch was not found.");
  assert.equal(apiErrorMessage({ status: 500 }, "fail"), "The validation service is unavailable.");
});

test("pipeline polling continues while pending, running, or missing", () => {
  function pipelineShouldKeepPolling(status, errorStatus) {
    if (status === "RUNNING" || status === "PENDING") return true;
    if (errorStatus === 404) return true;
    return false;
  }
  assert.equal(pipelineShouldKeepPolling("PENDING", null), true);
  assert.equal(pipelineShouldKeepPolling("RUNNING", null), true);
  assert.equal(pipelineShouldKeepPolling(undefined, 404), true);
  assert.equal(pipelineShouldKeepPolling("COMPLETED", null), false);
  assert.equal(pipelineShouldKeepPolling("FAILED", null), false);
});

test("optional anomaly fields can be missing", () => {
  const items = [{ record_id: "R1" }, { record_id: "R2", ai_explanation_status: "available" }];
  assert.equal(aiBatchLabel({ status: "COMPLETED", stages: [] }, items), "Partial");
  assert.equal(aiBatchLabel({ status: "COMPLETED", stages: [] }, null), "Not required");
});

test("query view distinguishes loading, error, empty, and ready", () => {
  function queryView(state, hasItems) {
    if (state.isPending) return "loading";
    if (state.isError) return "error";
    if (!hasItems) return "empty";
    return "ready";
  }
  assert.equal(queryView({ isPending: true }, false), "loading");
  assert.equal(queryView({ isError: true }, false), "error");
  assert.equal(queryView({}, false), "empty");
  assert.equal(queryView({}, true), "ready");
});

test("pipeline headlines keep backend status labels", () => {
  function pipelineHeadline(status) {
    switch (status) {
      case "PENDING":
      case "RUNNING":
      case "COMPLETED":
      case "PARTIAL":
      case "FAILED":
        return status;
      default:
        return status || "UNKNOWN";
    }
  }
  assert.equal(pipelineHeadline("PENDING"), "PENDING");
  assert.equal(pipelineHeadline("RUNNING"), "RUNNING");
  assert.equal(pipelineHeadline("PARTIAL"), "PARTIAL");
});

test("explanation confidence is shown as a supervisor label, not a raw score", () => {
  function explanationConfidenceLabel(value) {
    if (typeof value !== "number" || Number.isNaN(value)) return null;
    if (value >= 0.85) return "Very high";
    if (value >= 0.7) return "High";
    if (value >= 0.4) return "Moderate";
    return "Low";
  }
  assert.equal(explanationConfidenceLabel(0.98), "Very high");
  assert.equal(explanationConfidenceLabel(0.75), "High");
  assert.equal(explanationConfidenceLabel(0.5), "Moderate");
  assert.equal(explanationConfidenceLabel(0.2), "Low");
  assert.equal(explanationConfidenceLabel(null), null);
});
