# Pilot sample metadata (N=60)

`sample_segments.csv` is the **redistributed metadata** for the SoftwareX N=60
pilot (seed 42): segment ids, canonical YouTube URLs, bounds, and durations.

| Redistributed | Not redistributed |
| --- | --- |
| `sample_segments.csv` (this folder) | Local MP3 clips under `YOUAUDIOLAB_AUDIO_ROOT` |
| Synthetic WAVs in `fixtures/` | Full local `audio_manifest.csv` used only to regenerate the sample |

Column `audio_relpath` is a portable placeholder (`audio/<segment_id>.mp3`).
Eval scripts resolve it with `--audio-root` or env `YOUAUDIOLAB_AUDIO_ROOT`,
matching files by basename.

Regenerate the same 60-row sample from a local manifest (not published):

```bash
python docs/software/eval/select_sample.py --manifest path/to/audio_manifest.csv --n 60 --seed 42
```
