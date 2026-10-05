# Redistributable validation fixtures

Synthetic PCM WAV clips (`clip_01.wav`, `clip_02.wav`) for software-invariant
regression tests that must not depend on YouTube retrieval or the copyrighted
pilot MP3 sample.

The SoftwareX N=60 timing/integrity pilot uses local MP3s referenced by
portable metadata in `../sample_segments.csv` (`audio_relpath`). The MP3 bytes
themselves are **not redistributed**. Reviewers can still reproduce:

- revision / stale-publication invariants (`pytest`, Docker Compose stack)
- application-level artifact checksum contract
- annotation, split, and export provenance
- ASR stale completion and late-apply rejection

with the packaged fixtures and the automated test suite, without live download.
