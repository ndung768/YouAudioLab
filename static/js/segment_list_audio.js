import { apiFetch } from "./api.js";

const urlCache = new Map();
let activeButton = null;
let sharedPlayer = null;

function t(key) {
  return (window.YAL_I18N && window.YAL_I18N[key]) || key;
}

async function loadArtifactContent(artifactId) {
  const response = await apiFetch(`/api/v1/artifacts/${artifactId}/content`);
  if (!response.ok) return null;
  return response.blob();
}

async function resolveUrl(artifactId) {
  const cached = urlCache.get(artifactId);
  if (cached) return cached;
  const blob = await loadArtifactContent(artifactId);
  if (!blob) return null;
  const url = URL.createObjectURL(blob);
  urlCache.set(artifactId, url);
  return url;
}

function ensurePlayer() {
  if (sharedPlayer instanceof HTMLAudioElement) return sharedPlayer;
  sharedPlayer = document.getElementById("segment-list-player");
  if (!(sharedPlayer instanceof HTMLAudioElement)) {
    sharedPlayer = document.createElement("audio");
    sharedPlayer.id = "segment-list-player";
    sharedPlayer.preload = "none";
    sharedPlayer.hidden = true;
    document.body.appendChild(sharedPlayer);
  }
  sharedPlayer.addEventListener("ended", () => setButtonState(activeButton, false));
  sharedPlayer.addEventListener("pause", () => {
    if (sharedPlayer?.ended) return;
    if (activeButton && sharedPlayer?.paused) setButtonState(activeButton, false);
  });
  sharedPlayer.addEventListener("play", () => setButtonState(activeButton, true));
  return sharedPlayer;
}

function setButtonState(button, playing) {
  if (!(button instanceof HTMLButtonElement)) return;
  button.setAttribute("aria-pressed", playing ? "true" : "false");
  button.classList.toggle("active", playing);
  const icon = button.querySelector("i");
  if (icon) {
    icon.classList.toggle("bi-play-fill", !playing);
    icon.classList.toggle("bi-pause-fill", playing);
  }
  button.title = playing ? t("Pause") : t("Play segment audio");
}

function resetOtherButtons(except) {
  document.querySelectorAll("[data-play-artifact]").forEach((btn) => {
    if (btn !== except) setButtonState(btn, false);
  });
}

async function togglePlay(button) {
  const artifactId = button.getAttribute("data-play-artifact");
  if (!artifactId) return;
  const player = ensurePlayer();

  if (activeButton === button && !player.paused && player.dataset.artifactId === artifactId) {
    player.pause();
    setButtonState(button, false);
    return;
  }

  button.disabled = true;
  const url = await resolveUrl(artifactId);
  button.disabled = false;
  if (!url) {
    button.title = t("Could not load artifact audio.");
    return;
  }

  resetOtherButtons(button);
  activeButton = button;
  player.dataset.artifactId = artifactId;
  if (player.src !== url) {
    player.src = url;
  }
  try {
    await player.play();
    setButtonState(button, true);
  } catch {
    setButtonState(button, false);
    button.title = t("Could not play audio.");
  }
}

function setupSegmentListAudio() {
  const buttons = document.querySelectorAll("[data-play-artifact]");
  if (!buttons.length) return;
  ensurePlayer();
  buttons.forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      togglePlay(button);
    });
  });
  window.addEventListener("beforeunload", () => {
    for (const url of urlCache.values()) URL.revokeObjectURL(url);
    urlCache.clear();
  });
}

setupSegmentListAudio();
