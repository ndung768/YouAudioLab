/**
 * Inline transcript edit on Segments list (OWNER). Esc cancels; only one row open at a time.
 */
function closeAllTranscriptEditors(exceptCell) {
  document.querySelectorAll("[data-transcript-cell]").forEach((cell) => {
    if (cell === exceptCell) return;
    const view = cell.querySelector("[data-transcript-view]");
    const form = cell.querySelector("[data-transcript-form]");
    if (view) view.classList.remove("d-none");
    if (form) form.classList.add("d-none");
  });
}

function openTranscriptEditor(cell) {
  closeAllTranscriptEditors(cell);
  const view = cell.querySelector("[data-transcript-view]");
  const form = cell.querySelector("[data-transcript-form]");
  const area = form?.querySelector("textarea");
  if (view) view.classList.add("d-none");
  if (form) form.classList.remove("d-none");
  if (area instanceof HTMLTextAreaElement) {
    area.focus();
    area.setSelectionRange(area.value.length, area.value.length);
  }
}

function cancelTranscriptEditor(cell) {
  const view = cell.querySelector("[data-transcript-view]");
  const form = cell.querySelector("[data-transcript-form]");
  const area = form?.querySelector("textarea");
  const original = area?.defaultValue ?? "";
  if (area instanceof HTMLTextAreaElement) {
    area.value = original;
  }
  if (view) view.classList.remove("d-none");
  if (form) form.classList.add("d-none");
}

function setupTranscriptInlineEdit() {
  document.querySelectorAll("[data-transcript-cell]").forEach((cell) => {
    cell.querySelector("[data-transcript-edit]")?.addEventListener("click", (event) => {
      event.preventDefault();
      openTranscriptEditor(cell);
    });
    cell.querySelector("[data-transcript-cancel]")?.addEventListener("click", (event) => {
      event.preventDefault();
      cancelTranscriptEditor(cell);
    });
    cell.querySelector("[data-transcript-form]")?.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        cancelTranscriptEditor(cell);
      }
    });
  });
}

setupTranscriptInlineEdit();
