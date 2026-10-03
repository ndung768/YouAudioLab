/**
 * Source Workspace: YouTube IFrame API + Set Start/End + S/E/Space shortcuts.
 */
let ytPlayer = null;
let ytReady = false;

function roundTime(value) {
  return Math.round(Number(value) * 1000) / 1000;
}

function currentTime() {
  if (!ytReady || !ytPlayer || typeof ytPlayer.getCurrentTime !== "function") {
    return 0;
  }
  return roundTime(ytPlayer.getCurrentTime());
}

function updateDurationDisplay() {
  const startInput = document.querySelector("[data-start-input]");
  const endInput = document.querySelector("[data-end-input]");
  const display = document.querySelector("[data-duration-display]");
  if (!(startInput instanceof HTMLInputElement) || !(endInput instanceof HTMLInputElement)) {
    return;
  }
  const start = Number(startInput.value);
  const end = Number(endInput.value);
  if (display instanceof HTMLElement && Number.isFinite(start) && Number.isFinite(end) && end > start) {
    display.textContent = `Duration ${roundTime(end - start)}s`;
  } else if (display instanceof HTMLElement) {
    display.textContent = "";
  }
}

function setStartFromPlayer() {
  const startInput = document.querySelector("[data-start-input]");
  if (!(startInput instanceof HTMLInputElement)) return;
  startInput.value = String(currentTime());
  updateDurationDisplay();
}

function setEndFromPlayer() {
  const endInput = document.querySelector("[data-end-input]");
  if (!(endInput instanceof HTMLInputElement)) return;
  endInput.value = String(currentTime());
  updateDurationDisplay();
}

function togglePlay() {
  if (!ytReady || !ytPlayer) return;
  const state = ytPlayer.getPlayerState?.();
  // 1 = playing
  if (state === 1) {
    ytPlayer.pauseVideo?.();
  } else {
    ytPlayer.playVideo?.();
  }
}

function isTypingTarget(target) {
  return (
    target instanceof HTMLElement &&
    (target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.tagName === "SELECT" ||
      target.isContentEditable)
  );
}

function setupShortcuts() {
  document.addEventListener("keydown", (event) => {
    if (isTypingTarget(event.target)) return;
    const root = document.querySelector("[data-source-workspace]");
    if (!root) return;

    if (event.key === "s" || event.key === "S") {
      event.preventDefault();
      setStartFromPlayer();
      return;
    }
    if (event.key === "e" || event.key === "E") {
      event.preventDefault();
      setEndFromPlayer();
      return;
    }
    if (event.code === "Space" || event.key === " ") {
      event.preventDefault();
      togglePlay();
    }
  });
}

function setupButtons() {
  document.querySelector("[data-set-start]")?.addEventListener("click", (event) => {
    event.preventDefault();
    setStartFromPlayer();
  });
  document.querySelector("[data-set-end]")?.addEventListener("click", (event) => {
    event.preventDefault();
    setEndFromPlayer();
  });
  document.querySelector("[data-start-input]")?.addEventListener("input", updateDurationDisplay);
  document.querySelector("[data-end-input]")?.addEventListener("input", updateDurationDisplay);
  updateDurationDisplay();
}

window.onYouTubeIframeAPIReady = function onYouTubeIframeAPIReady() {
  const root = document.querySelector("[data-source-workspace]");
  const mount = document.getElementById("yt-player");
  if (!(root instanceof HTMLElement) || !(mount instanceof HTMLElement)) return;
  const videoId = root.getAttribute("data-youtube-id");
  if (!videoId) return;

  ytPlayer = new window.YT.Player("yt-player", {
    videoId,
    playerVars: {
      rel: 0,
      modestbranding: 1,
      enablejsapi: 1,
    },
    events: {
      onReady: () => {
        ytReady = true;
      },
    },
  });
};

setupButtons();
setupShortcuts();

// If the IFrame API script already finished before this module ran.
if (window.YT && typeof window.YT.Player === "function" && !ytPlayer) {
  window.onYouTubeIframeAPIReady();
}
