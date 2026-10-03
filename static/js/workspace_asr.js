/** ASR generate form: keep model sensible when provider changes. */

const LOCAL_MODELS = new Set([
  "tiny",
  "base",
  "small",
  "medium",
  "large-v3",
  "large",
]);

function syncProviderModel(form) {
  const provider = form.querySelector("[data-asr-provider]")?.value || "local";
  const modelInput = form.querySelector("[data-asr-model]");
  if (!modelInput) {
    return;
  }
  const localDefault = form.dataset.localDefault || "base";
  const openaiDefault = form.dataset.openaiDefault || "gpt-4o-mini-transcribe";
  const current = (modelInput.value || "").trim();
  if (provider === "openai" && (!current || LOCAL_MODELS.has(current))) {
    modelInput.value = openaiDefault;
  } else if (provider === "local" && (!current || !LOCAL_MODELS.has(current))) {
    modelInput.value = localDefault;
  }
}

function initWorkspaceAsr() {
  const form = document.querySelector("[data-asr-generate-form]");
  if (!form) {
    return;
  }
  form
    .querySelector("[data-asr-provider]")
    ?.addEventListener("change", () => syncProviderModel(form));
}

document.addEventListener("DOMContentLoaded", initWorkspaceAsr);
