import { apiFetch } from "./api.js";

async function loadArtifactMeta(artifactId) {
  const response = await apiFetch(`/api/v1/artifacts/${artifactId}`);
  if (!response.ok) return null;
  return response.json();
}

async function loadArtifactContent(artifactId) {
  const response = await apiFetch(`/api/v1/artifacts/${artifactId}/content`);
  if (!response.ok) return null;
  return response.blob();
}

function t(key) {
  return (window.YAL_I18N && window.YAL_I18N[key]) || key;
}

function setStatus(message, { hidePlayer = true } = {}) {
  const status = document.getElementById("audio-status");
  const player = document.getElementById("artifact-player");
  const download = document.getElementById("download-artifact");
  const hint = document.getElementById("audio-hint");
  if (status) {
    status.textContent = message;
    status.classList.toggle("d-none", !message);
  }
  if (hidePlayer) {
    if (player) player.classList.add("d-none");
    if (download) download.classList.add("d-none");
    if (hint) hint.classList.add("d-none");
  }
}

async function setup() {
  const root = document.querySelector("[data-segment-workspace]");
  if (!root) return;
  const artifactId = root.getAttribute("data-artifact-id");
  if (!artifactId) return;

  const player = document.getElementById("artifact-player");
  const download = document.getElementById("download-artifact");
  setStatus(t("Loading audio…"), { hidePlayer: true });

  const meta = await loadArtifactMeta(artifactId);
  if (!meta) {
    setStatus(t("Could not load artifact audio."));
    return;
  }
  if (!meta.verified) {
    setStatus(t("Artifact exists but is not verified yet."));
    return;
  }

  const blob = await loadArtifactContent(artifactId);
  if (!blob) {
    setStatus(t("Could not load artifact audio."));
    return;
  }

  const url = URL.createObjectURL(blob);
  setStatus("", { hidePlayer: false });
  if (player instanceof HTMLAudioElement) {
    player.classList.remove("d-none");
    player.src = url;
  }
  if (download instanceof HTMLButtonElement) {
    download.classList.remove("d-none");
    download.addEventListener("click", () => {
      const link = document.createElement("a");
      link.href = url;
      link.download = `segment-${artifactId}.wav`;
      link.click();
    });
  }
  const hint = document.getElementById("audio-hint");
  if (hint) hint.classList.remove("d-none");
  window.addEventListener("beforeunload", () => URL.revokeObjectURL(url));
}

setup();
