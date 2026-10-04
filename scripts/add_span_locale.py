"""Add Vietnamese strings for text-span labelling to locale/vi and recompile .mo."""

from __future__ import annotations

from pathlib import Path

import polib

ROOT = Path(__file__).resolve().parents[1]

VI = {
    "Drag across one word or several words, then pick a label. Esc clears the selection.": "Kéo chọn một hoặc nhiều chữ rồi chọn nhãn. Esc để bỏ chọn.",
    "No text labels yet. On <a href=\"%(labels_url)s\">Labels</a>, set a label’s scope to “Text in transcript”.": "Chưa có nhãn chữ. Vào <a href=\"%(labels_url)s\">Nhãn</a> và đặt phạm vi của nhãn là “Chữ trong transcript”.",
    "Label this phrase": "Gán nhãn cho cụm chữ",
    "1–9 or click a label": "Bấm 1–9 hoặc chọn nhãn",
    "Remove this phrase label": "Gỡ nhãn của cụm chữ này",
    "Whole segment": "Cả đoạn audio",
    "Text in transcript": "Chữ trong transcript",
    "Both": "Cả hai",
    "Segment + text": "Đoạn + chữ",
    "Used for": "Dùng cho",
    "Text span assigned.": "Đã gán nhãn cho chữ.",
    "Text span removed.": "Đã gỡ nhãn của chữ.",
    "Personal label catalog. Set whether each label is for the whole audio segment, text in the transcript, or both. Assign labels to projects from each project's label settings.": "Katalog nhãn cá nhân. Chọn nhãn dùng cho cả đoạn audio, chữ trong transcript, hoặc cả hai. Gán nhãn vào dự án từ trang Nhãn của từng dự án.",
    "Also update this label in projects that already use it": "Cập nhật luôn nhãn này trong các dự án đang dùng",
    "Note: “Used for” controls whether the label appears on whole-segment chips, on the text-phrase bar, or both. Deactivating hides it from “available labels” when adding to new projects. Labels already assigned to projects stay usable. Labels in use cannot be deleted.": "Ghi chú: “Dùng cho” quyết định nhãn hiện ở chip cả đoạn, thanh gán chữ, hoặc cả hai. Vô hiệu hoá sẽ ẩn khỏi “nhãn có sẵn” khi thêm vào dự án mới. Nhãn đã gán vào dự án vẫn dùng được. Nhãn đang được dùng không xoá được.",
    "Whole segment = clip chips. Text in transcript = drag words then label. Both = either place.": "Cả đoạn audio = chip cả clip. Chữ trong transcript = kéo chọn chữ rồi gán. Cả hai = dùng được ở cả hai chỗ.",
    "Segment #%(idx)s": "Đoạn #%(idx)s",
    "Open the workspace to assign labels, run ASR, and review audio.": "Mở workspace để gán nhãn, chạy ASR và nghe âm thanh.",
}


def main() -> None:
    po_path = ROOT / "locale" / "vi" / "LC_MESSAGES" / "django.po"
    po = polib.pofile(str(po_path))
    for msgid, msgstr in VI.items():
        entry = po.find(msgid)
        if entry is None:
            po.append(polib.POEntry(msgid=msgid, msgstr=msgstr))
        else:
            entry.msgstr = msgstr
            if "fuzzy" in entry.flags:
                entry.flags.remove("fuzzy")
    po.save(str(po_path))
    po.save_as_mofile(str(po_path.with_suffix(".mo")))
    print(f"Updated {po_path}")


if __name__ == "__main__":
    main()
