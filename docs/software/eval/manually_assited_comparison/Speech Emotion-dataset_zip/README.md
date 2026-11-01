# Speech Emotion

- Language: vi
- Exported at: 2026-10-27T04:44:06.710162+00:00
- Schema: youaudiolab.research_dataset 1.2
- Ready-only filter: False
- Sources: 19
- Segments: 60
- Annotations: 71
- Project ID (opaque): `400047ef-349f-4b18-a127-41223d43aecc`
- Dataset version: `yal-5f371cd4b83e`
- Content hash: `5f371cd4b83e92a69ef08f8249c6db6076d84f63c34fe6638b90a74124c932f8`
- Supervision policy: majority
- Split: {'strategy': 'by_source', 'seed': 42, 'ratios': {'train': 0.8, 'val': 0.1, 'test': 0.1}, 'group_by': 'source_id'}

## Splits and supervision
- Prefer `by_source` splits so the same YouTube video never appears in both train and test.
- Do not randomly split by segment for speech tasks — that leaks acoustic content across folds.
- Training views use `supervised_labels` for the whole segment (majority by default; `gold` uses OWNER adjudication when present).
- `text_spans` / `spans.csv` are labels on words inside the transcript, such as a toxic token. They are separate from segment labels.
- `description` is the YouTube video description captured with metadata. Refresh metadata to fill it for older imports.
- Research JSON keeps full annotation episodes for IAA plus `gold_labels` when adjudicated.
- `dataset_version` / `content_hash` identify this snapshot; `exported_at` is not part of the hash.
- License: —
- Consent notes: —

## Segment keys
- `segment_key` is `{youtube_video_id}#{segment_index}` — stable human handle alongside opaque `segment_id`.
- Audio files use `segment_{youtube_video_id}_{index}.{ext}` when an artifact is present.

## Audio configuration
- Format: WAV
- Encoding: PCM
- Sample rate: 16000 Hz
- Channels: 1
- Loudness normalization: False

## Readiness policy
- Require audio review: True
- Require transcript: True
- Require annotation: True

## Label definitions
- **Anger**
  - Definition: Người nói thể hiện tức giận, khó chịu, bực bội, trách móc, đe dọa hoặc đối đầu.
  - Include: Quát, mắng, cáo buộc, tranh cãi, giọng căng và mạnh, thể hiện sự phản đối gay gắt.
  - Exclude: Không chọn cho câu phủ định hoặc bất đồng bình tĩnh; không chọn cho đùa mỉa nếu không có tức giận rõ ràng.
- **Sadness**
  - Definition: Người nói thể hiện buồn bã, thất vọng, đau khổ, tiếc nuối hoặc tuyệt vọng.
  - Include: Khóc, giọng trầm/yếu, than phiền vì mất mát, bày tỏ cô đơn, bất lực hoặc thất vọng.
  - Exclude: Không chọn cho giọng nhỏ do âm thanh kém; không chọn khi cảm xúc chính là sợ hãi hoặc tức giận.
- **Uncertain**
  - Definition: Không thể xác định đáng tin cậy một cảm xúc chính hoặc segment chứa nhiều cảm xúc/người nói đối lập.
  - Include: Nhiều người nói có cảm xúc khác nhau; cảm xúc thay đổi rõ trong clip; transcript/audio không đủ; âm thanh kém; mỉa mai khó xác định.
  - Exclude: Không dùng chỉ vì annotator hơi phân vân. Nếu một cảm xúc vẫn chiếm ưu thế rõ ràng thì chọn cảm xúc đó.
- **Neutral**
  - Definition: Người nói thể hiện trạng thái bình thường, tương đối điềm tĩnh, không có cảm xúc nổi trội.
  - Include: Hội thoại thông thường; cung cấp thông tin; giọng đều; phản ứng nhẹ; không có dấu hiệu rõ của vui, buồn, giận hoặc sợ.
  - Exclude: Không chọn nếu có cảm xúc khác nổi trội, ngay cả khi transcript có vẻ trung tính.
- **Joy**
  - Definition: Người nói thể hiện vui vẻ, hài lòng, thích thú, yêu thương hoặc phấn khởi.
  - Include: Cười, trêu đùa tích cực, khen ngợi, bày tỏ hạnh phúc, hào hứng hoặc trìu mến.
  - Exclude: Không chọn cho tiếng cười mỉa mai, chế giễu hoặc câu nói tích cực nhưng giọng đang tức giận.
- **Fear**
  - Definition: Người nói thể hiện sợ hãi, lo lắng, căng thẳng, hoảng loạn hoặc bất an.
  - Include: Giọng run, do dự vì lo sợ, cảnh báo nguy hiểm, lo lắng về hậu quả hoặc thể hiện hoảng hốt.
  - Exclude: Không chọn cho sự bất ngờ ngắn không kèm lo sợ; không chọn khi cảm xúc chính là buồn hoặc tức giận.

## Contents
- `audio/` — verified current artifacts when available
- `metadata.csv` — segment provenance, video title and description, audio path, transcript, and text spans
- `spans.csv` — one row per in-transcript label, with the YouTube link, times, title, description, audio path, and transcript
- `annotations.csv` — human annotation episodes for the whole segment
- `sources.csv` — YouTube source metadata, including description
