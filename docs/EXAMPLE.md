# Example: one YouTube cut through YouAudioLab

This walk-through follows one YouTube cut and the records written for that cut.
It is documentation for the repository, not an evaluation and not a timed user
study. The SoftwareX manuscript points here instead of embedding screenshots
in the article.

The narrative uses labels `speech`, `music`, and `overlap` on a cut from
**12.0 s to 18.5 s**. The interface figures below are from a live
Vietnamese-language project that follows the same path
(import → cut → verify → accept transcript → export); that project uses
regional speech labels (`Miền bắc`, `Miền nam`, `Miền trung`) on a 0–10 s
segment.

## 1. Protocol

1. Create a project and set the language.
2. Leave audio defaults at **WAV / PCM / 16 kHz / mono**.
3. Turn readiness gates on so a segment needs a transcript and at least one
   label before export.
4. Keep **blind labelling** on.
5. Enter a licence string and a short consent note on project settings (both
   are copied into research JSON and the quality report).
6. Add annotators as project members (**owner** vs **annotator**).
7. Only users on the system allowlist can change the global recognition
   endpoint (`ASR_ADMIN_USER_IDS`).

## 2. A cut and a candidate transcript

1. Import a YouTube URL. After metadata returns, the source appears in the
   project source list.

   ![Source list after a YouTube URL has been imported and metadata has returned.](software/figures/appendix/figure-a4-sources.png)

2. Create a segment from **12.0 s to 18.5 s** and queue **extract**.
3. When a verified WAV is the current artifact, queue **recognition**.
4. Listen, then **apply** the run you accept on the segment workspace.

   ![Segment workspace: cut bounds, verified audio, recognition candidates, and the accepted transcript.](software/figures/appendix/figure-a5-workspace.png)

5. If you later change the end time, `definition_revision` increases. A job
   still running against the old revision cannot become the current artifact.

## 3. Labels on the same cut

1. Assign the segment to two annotators.
2. Each selects `speech`. One also selects `overlap` (whole-segment scope).
3. With blind labelling on, neither sees the other’s row.
4. The owner saves gold as `speech`, or adopts the majority. Annotator rows
   remain.
5. Pairwise Jaccard for `{speech}` vs `{speech, overlap}` is
   `|A ∩ B| / |A ∪ B| = 0.5`.
6. Optional text span: if the accepted transcript contains a token such as
   `dm`, drag that word and assign a text-scoped label. The resulting
   `TranscriptSpan` does not change whole-segment gold or the Jaccard figure
   above.

## 4. Export

1. Export a zip with supervision policy `gold`, split strategy `by_source`,
   seed `42`, and ratios `0.8 / 0.1 / 0.1`.

   ![Export form. The owner chooses the format, the supervision rule, and a by-source split; the zip writes each verified WAV under audio/.](software/figures/appendix/figure-a6-export.png)

2. The archive writes the verified WAV under `audio/` and points
   `metadata.csv` at that path beside the transcript, start/end times, video
   title and description, and active text spans.
3. `spans.csv` repeats the YouTube link and clip interval on each span row.
4. Research JSON describes the file by checksum and sample rate (no embedded
   waveform) and keeps annotator rows, gold names, `supervised_labels`, and
   `text_spans`.
5. For this segment the training view contains `speech` and not `overlap`.
6. A second video receives its own fold: the split is on video identifiers,
   then copied onto segments. Same inputs reproduce the same folds; the
   content hash is unchanged if only the export clock changes.

Word times from the recognition run are not written into these files. The
published item is the checksummed waveform with its bounds, transcript, and
optional character spans—not a text row alone.

## Related reading

- [README — Building a corpus](../README.md#building-a-corpus)
- [README — Export formats](../README.md#export-formats)
- SoftwareX manuscript drafts under [`software/`](software/)
