/** Toggle ASR preference / system-ASR fields by mode and provider. */

function syncAsrFields(root) {
  const mode =
    root.querySelector('input[name="mode"]:checked')?.value || "system";
  const custom = root.querySelector("[data-asr-custom-fields]");
  if (custom) {
    custom.classList.toggle("d-none", mode !== "custom");
  }
  if (mode !== "custom") {
    return;
  }
  const provider =
    root.querySelector("[data-asr-provider]")?.value || "local";
  const local = root.querySelector("[data-asr-local-fields]");
  const openai = root.querySelector("[data-asr-openai-fields]");
  if (local) {
    local.classList.toggle("d-none", provider !== "local");
  }
  if (openai) {
    openai.classList.toggle("d-none", provider !== "openai");
  }
}

function syncSystemAsrFields(root) {
  const provider =
    root.querySelector("[data-sys-asr-provider]")?.value || "local";
  const showBoth = Boolean(
    root.querySelector("[data-sys-asr-show-both]")?.checked
  );
  const local = root.querySelector("[data-sys-asr-local-fields]");
  const openai = root.querySelector("[data-sys-asr-openai-fields]");
  if (local) {
    local.classList.toggle("d-none", !showBoth && provider !== "local");
    local.classList.toggle("border-primary", provider === "local");
  }
  if (openai) {
    openai.classList.toggle("d-none", !showBoth && provider !== "openai");
    openai.classList.toggle("border-primary", provider === "openai");
  }
  root.querySelectorAll("[data-sys-asr-default-badge]").forEach((badge) => {
    const forProvider = badge.getAttribute("data-sys-asr-default-badge");
    badge.classList.toggle("d-none", forProvider !== provider);
  });
}

function initAsrSettings() {
  const prefs = document.querySelector("[data-settings-asr]");
  if (prefs) {
    syncAsrFields(prefs);
    prefs.querySelectorAll("[data-asr-mode]").forEach((el) => {
      el.addEventListener("change", () => syncAsrFields(prefs));
    });
    prefs
      .querySelector("[data-asr-provider]")
      ?.addEventListener("change", () => syncAsrFields(prefs));
  }

  const system = document.querySelector("[data-settings-system-asr]");
  if (system) {
    syncSystemAsrFields(system);
    system
      .querySelector("[data-sys-asr-provider]")
      ?.addEventListener("change", () => syncSystemAsrFields(system));
    system
      .querySelector("[data-sys-asr-show-both]")
      ?.addEventListener("change", () => syncSystemAsrFields(system));
  }
}

document.addEventListener("DOMContentLoaded", initAsrSettings);
