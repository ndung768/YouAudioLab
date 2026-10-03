import { apiJson } from "./api.js";

const ACTIVE = new Set(["QUEUED", "RUNNING"]);
const TERMINAL = new Set(["SUCCEEDED", "FAILED", "STALE", "CANCELLED"]);

const STATUS_LABELS = {
  QUEUED: "Queued",
  RUNNING: "Running",
  SUCCEEDED: "Succeeded",
  FAILED: "Failed",
  STALE: "Out of date",
  CANCELLED: "Cancelled",
  CANCEL_REQUESTED: "Cancellation requested…",
};

function t(key) {
  return (window.YAL_I18N && window.YAL_I18N[key]) || key;
}

function displayLabel(job) {
  if (job.cancel_requested_at && ACTIVE.has(job.status)) {
    return t(STATUS_LABELS.CANCEL_REQUESTED);
  }
  return t(STATUS_LABELS[job.status] || job.status);
}

function shouldPoll() {
  return !document.hidden;
}

async function refreshJob(row) {
  const jobId = row.getAttribute("data-job-id");
  if (!jobId) return null;
  const job = await apiJson(`/api/v1/jobs/${jobId}`);
  row.setAttribute("data-job-status", job.status);
  if (job.cancel_requested_at) {
    row.setAttribute("data-cancel-requested", "true");
  }
  const badge = row.querySelector(".job-status-badge .badge, .job-status-badge span, .badge");
  if (badge) {
    badge.textContent = displayLabel(job);
  }
  return job;
}

function startPolling() {
  const rows = [...document.querySelectorAll("[data-job-id]")];
  if (!rows.length) return undefined;
  const controller = new AbortController();
  const timer = window.setInterval(async () => {
    if (!shouldPoll() || controller.signal.aborted) return;
    let changedToTerminal = false;
    for (const row of rows) {
      const status = row.getAttribute("data-job-status");
      if (!status || !ACTIVE.has(status)) continue;
      try {
        const job = await refreshJob(row);
        if (job && TERMINAL.has(job.status)) {
          changedToTerminal = true;
        }
      } catch {
        /* keep last known status */
      }
    }
    if (changedToTerminal) {
      window.location.reload();
    }
  }, 3000);
  controller.signal.addEventListener("abort", () => window.clearInterval(timer));
  return controller;
}

const poller = startPolling();
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  if (!poller) startPolling();
});
