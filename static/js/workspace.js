function setupConflictPanel() {
  const panel = document.getElementById("conflict-panel");
  if (!panel) return;

  const root = document.querySelector("[data-segment-workspace]");
  const startInput = document.getElementById("start-seconds");
  const endInput = document.getElementById("end-seconds");
  const expectedInput = document.getElementById("expected-definition-revision");
  const revisionLabel = document.getElementById("definition-revision");
  const applyBtn = document.getElementById("apply-draft");
  const discardBtn = document.getElementById("discard-draft");

  const draftStart = startInput?.value;
  const draftEnd = endInput?.value;
  const serverStart = root?.getAttribute("data-server-start") ?? "";
  const serverEnd = root?.getAttribute("data-server-end") ?? "";
  const currentRevision = expectedInput?.value ?? "";

  applyBtn?.addEventListener("click", () => {
    if (startInput) startInput.value = draftStart;
    if (endInput) endInput.value = draftEnd;
    if (expectedInput) expectedInput.value = currentRevision;
    if (revisionLabel) revisionLabel.textContent = currentRevision;
    panel.classList.add("d-none");
  });

  discardBtn?.addEventListener("click", () => {
    if (startInput) startInput.value = serverStart;
    if (endInput) endInput.value = serverEnd;
    if (expectedInput) expectedInput.value = currentRevision;
    if (revisionLabel) revisionLabel.textContent = currentRevision;
    panel.classList.add("d-none");
  });
}

function replaySegmentAudio() {
  const player = document.getElementById("artifact-player");
  if (!(player instanceof HTMLAudioElement) || !player.src) return;
  player.currentTime = 0;
  player.play().catch(() => {});
}

function setupLabelingHotkeys() {
  const root = document.querySelector("[data-segment-workspace]");
  if (!root) return;

  const replayBtn = document.getElementById("replay-segment");
  replayBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    replaySegmentAudio();
  });

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    if (
      target instanceof HTMLElement &&
      (target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable)
    ) {
      return;
    }

    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      const saveNext = document.querySelector("[data-save-next]");
      if (saveNext instanceof HTMLButtonElement) {
        event.preventDefault();
        saveNext.click();
        return;
      }
      const nextAssigned = document.getElementById("nav-next-assigned");
      if (nextAssigned instanceof HTMLAnchorElement) {
        event.preventDefault();
        nextAssigned.click();
        return;
      }
      const next = document.getElementById("nav-next");
      if (next instanceof HTMLAnchorElement) {
        event.preventDefault();
        next.click();
      }
      return;
    }

    const key = event.key;
    if (key === "r" || key === "R") {
      event.preventDefault();
      replaySegmentAudio();
      return;
    }
    if (key === "n" || key === "N") {
      const next = document.getElementById("nav-next");
      if (next instanceof HTMLAnchorElement) {
        event.preventDefault();
        next.click();
      }
      return;
    }
    if (key === "p" || key === "P") {
      const prev = document.getElementById("nav-prev");
      if (prev instanceof HTMLAnchorElement) {
        event.preventDefault();
        prev.click();
      }
      return;
    }
    if (/^[1-9]$/.test(key)) {
      const chip = document.querySelector(`[data-label-chip][data-hotkey="${key}"]`);
      if (chip instanceof HTMLButtonElement) {
        event.preventDefault();
        chip.click();
      }
    }
  });
}

setupConflictPanel();
setupLabelingHotkeys();
