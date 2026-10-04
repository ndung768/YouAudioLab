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

function currentSpanSelection() {
  if (typeof window.youAudioLabSpanSelection === "function") {
    return window.youAudioLabSpanSelection();
  }
  return null;
}

function postTextSpan(labelId, range) {
  const tokenInput = document.querySelector("[name=csrfmiddlewaretoken]");
  if (!(tokenInput instanceof HTMLInputElement) || !range) return;
  const body = new FormData();
  body.set("csrfmiddlewaretoken", tokenInput.value);
  body.set("action", "assign_span");
  body.set("label_id", labelId);
  body.set("start_char", range.start);
  body.set("end_char", range.end);
  fetch(window.location.pathname, {
    method: "POST",
    body,
    credentials: "same-origin",
  }).then(() => {
    window.location.reload();
  });
}

function setupTranscriptSpans() {
  const root = document.getElementById("transcript-tokens");
  if (!root) return;

  const bar = document.getElementById("span-label-bar");
  const preview = bar?.querySelector("[data-span-preview]");
  const removeButton = bar?.querySelector("[data-remove-selected-span]");
  let anchor = null;
  let selecting = false;
  let dragged = false;

  function words() {
    return [...root.querySelectorAll("[data-token]")];
  }

  function selectedWords() {
    return words().filter((el) => el.classList.contains("is-selected"));
  }

  function clearSelection() {
    words().forEach((el) => el.classList.remove("is-selected"));
    bar?.classList.add("d-none");
    if (removeButton instanceof HTMLButtonElement) {
      removeButton.classList.add("d-none");
      delete removeButton.dataset.spanId;
    }
  }

  function selectIndexes(lo, hi) {
    const all = words();
    all.forEach((el, index) => {
      el.classList.toggle("is-selected", index >= lo && index <= hi);
    });
  }

  function selectRange(from, to) {
    const all = words();
    const start = all.indexOf(from);
    const end = all.indexOf(to);
    if (start < 0 || end < 0) return;
    selectIndexes(Math.min(start, end), Math.max(start, end));
  }

  function currentRange() {
    const selected = selectedWords();
    if (!selected.length) return null;
    return {
      start: selected[0].getAttribute("data-start") || "",
      end: selected[selected.length - 1].getAttribute("data-end") || "",
    };
  }

  function sharedSpanId() {
    const selected = selectedWords();
    const ids = selected.map((el) => el.dataset.spanId || "").filter(Boolean);
    if (!ids.length || ids.length !== selected.length) return "";
    return ids.every((id) => id === ids[0]) ? ids[0] : "";
  }

  function showBar() {
    const range = currentRange();
    if (!bar || !range) {
      bar?.classList.add("d-none");
      return;
    }
    bar.classList.remove("d-none");
    if (preview) {
      preview.textContent = selectedWords().map((el) => el.textContent || "").join(" ");
    }
    const spanId = sharedSpanId();
    if (removeButton instanceof HTMLButtonElement) {
      removeButton.classList.toggle("d-none", !spanId);
      if (spanId) removeButton.dataset.spanId = spanId;
    }
  }

  window.youAudioLabSpanSelection = currentRange;
  window.youAudioLabClearSpanSelection = clearSelection;

  root.addEventListener("pointerdown", (event) => {
    const token = event.target.closest("[data-token]");
    if (!(token instanceof HTMLElement) || !root.contains(token)) return;
    event.preventDefault();
    selecting = true;
    dragged = false;
    anchor = token;
    selectRange(token, token);
    if (root.setPointerCapture) root.setPointerCapture(event.pointerId);
  });

  root.addEventListener("pointermove", (event) => {
    if (!selecting || !(anchor instanceof HTMLElement)) return;
    const hit = document.elementFromPoint(event.clientX, event.clientY);
    const token = hit?.closest?.("[data-token]");
    if (!(token instanceof HTMLElement) || !root.contains(token)) return;
    if (token !== anchor) dragged = true;
    selectRange(anchor, token);
  });

  function finishSelection() {
    if (!selecting) return;
    const token = anchor;
    const moved = dragged;
    selecting = false;
    anchor = null;
    if (!moved && token instanceof HTMLElement && token.dataset.spanId) {
      const mates = words().filter((el) => el.dataset.spanId === token.dataset.spanId);
      if (mates.length) selectRange(mates[0], mates[mates.length - 1]);
    }
    showBar();
  }

  root.addEventListener("pointerup", finishSelection);
  root.addEventListener("pointercancel", finishSelection);

  document.addEventListener("pointerdown", (event) => {
    if (!(event.target instanceof Node)) return;
    if (root.contains(event.target) || bar?.contains(event.target)) return;
    if (selecting) return;
    clearSelection();
  });

  bar?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-span-label]");
    if (!(button instanceof HTMLButtonElement)) return;
    const range = currentRange();
    if (!range) return;
    postTextSpan(button.dataset.labelId || "", range);
  });

  removeButton?.addEventListener("click", () => {
    const spanId = removeButton.dataset.spanId;
    if (!spanId) return;
    const match = document.querySelector(
      `[data-testid=text-span-list] [name=span_id][value="${spanId}"]`,
    );
    const form = match?.closest("form");
    if (form instanceof HTMLFormElement) form.submit();
  });
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
    if (key === "Escape") {
      window.youAudioLabClearSpanSelection?.();
      return;
    }
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
      const range = currentSpanSelection();
      const spanButton = document.querySelector(
        `[data-span-label][data-hotkey="${key}"]`,
      );
      if (range && spanButton instanceof HTMLButtonElement) {
        event.preventDefault();
        postTextSpan(spanButton.dataset.labelId || "", range);
        return;
      }
      const chip = document.querySelector(`[data-label-chip][data-hotkey="${key}"]`);
      if (chip instanceof HTMLButtonElement) {
        event.preventDefault();
        chip.click();
      }
    }
  });
}

setupConflictPanel();
setupTranscriptSpans();
setupLabelingHotkeys();
