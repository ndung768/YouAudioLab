"""Build vi/en django.po + .mo without GNU gettext (uses polib)."""

from __future__ import annotations

import re
from pathlib import Path

import polib

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"

# English msgid → Vietnamese msgstr
VI = {
    "Language": "Ngôn ngữ",
    "Audio research workspace": "Không gian nghiên cứu âm thanh",
    "Primary": "Chính",
    "Projects": "Dự án",
    "New Project": "Dự án mới",
    "Preferences": "Tuỳ chọn",
    "ASR": "ASR",
    "AI": "AI",
    "Admin": "Quản trị",
    "System ASR": "ASR hệ thống",
    "System AI": "AI hệ thống",
    "Login": "Đăng nhập",
    "Logout": "Đăng xuất",
    "Close": "Đóng",
    "Project navigation": "Điều hướng dự án",
    "Sources": "Nguồn",
    "Segments": "Đoạn",
    "Workspace": "Không gian làm việc",
    "Labels": "Nhãn",
    "Members": "Thành viên",
    "Settings": "Cài đặt",
    "Detail": "Chi tiết",
    "Archived": "Đã lưu trữ",
    "Overview": "Tổng quan",
    "Sign in": "Đăng nhập",
    "Register": "Đăng ký",
    "Continue to projects": "Tiếp tục tới dự án",
    "Login identifier": "Tên đăng nhập",
    "Password": "Mật khẩu",
    "Enter your login": "Nhập tên đăng nhập",
    "Enter your password": "Nhập mật khẩu",
    "Show password": "Hiện mật khẩu",
    "Display name": "Tên hiển thị",
    "Your name": "Tên của bạn",
    "Choose a login": "Chọn tên đăng nhập",
    "At least 8 characters": "Ít nhất 8 ký tự",
    "Create account": "Tạo tài khoản",
    "Legacy bootstrap (development)": "Bootstrap cũ (phát triển)",
    "Create without password": "Tạo không mật khẩu",
    "User UUID": "UUID người dùng",
    "Use this identity": "Dùng danh tính này",
    "YouAudioLab": "YouAudioLab",
    "My Projects": "Dự án của tôi",
    "No description": "Không có mô tả",
    "Open": "Mở",
    "Created": "Tạo lúc",
    "You don't have any projects yet. Click <strong>New Project</strong> to get started.": "Bạn chưa có dự án nào. Bấm <strong>Dự án mới</strong> để bắt đầu.",
    "Create an audio research workspace.": "Tạo không gian nghiên cứu âm thanh.",
    "Back": "Quay lại",
    "Name": "Tên",
    "Description": "Mô tả",
    "Create project": "Tạo dự án",
    "Import source": "Nhập nguồn",
    "Archive this project?": "Lưu trữ dự án này?",
    "Archive": "Lưu trữ",
    "Quick import": "Nhập nhanh",
    "Add & fetch": "Thêm & lấy",
    "source(s) in this project.": "nguồn trong dự án này.",
    "No sources yet.": "Chưa có nguồn.",
    "View sources": "Xem nguồn",
    "Recent jobs": "Công việc gần đây",
    "No jobs yet.": "Chưa có công việc.",
    "Import is OWNER-only. New sources start as Metadata pending.": "Chỉ OWNER được nhập. Nguồn mới bắt đầu ở trạng thái chờ metadata.",
    "Title": "Tiêu đề",
    "Channel": "Kênh",
    "Duration": "Thời lượng",
    "Status": "Trạng thái",
    "Duration unknown": "Chưa biết thời lượng",
    "<strong>No sources yet.</strong> Use Add source below.": "<strong>Chưa có nguồn.</strong> Dùng Thêm nguồn bên dưới.",
    "<strong>No sources yet.</strong> Ask a project OWNER to import a YouTube URL.": "<strong>Chưa có nguồn.</strong> Nhờ OWNER dự án nhập URL YouTube.",
    "Add source": "Thêm nguồn",
    "Duplicate video ids in this project return a conflict.": "Trùng video id trong dự án sẽ bị xung đột.",
    "YouTube URL": "URL YouTube",
    "Import": "Nhập",
    "Cross-source index for this project (merged from per-source lists).": "Danh mục đoạn trên mọi nguồn của dự án.",
    "Segment": "Đoạn",
    "Source": "Nguồn",
    "Bounds": "Biên",
    "Rev": "Rev",
    "No segments yet": "Chưa có đoạn",
    "Open a source to create a segment (OWNER).": "Mở một nguồn để tạo đoạn (OWNER).",
    "Project taxonomy for Model B annotations. Deactivating blocks new assignments; history remains.": "Phân loại nhãn cho annotation Model B. Vô hiệu hoá chặn gán mới; lịch sử vẫn giữ.",
    "Read-only: only project owners can create, edit, or activate labels.": "Chỉ đọc: chỉ OWNER mới tạo, sửa hoặc kích hoạt nhãn.",
    "Filter": "Lọc",
    "All": "Tất cả",
    "Active": "Đang dùng",
    "Inactive": "Ngừng",
    "Active membership. Add people by existing user UUID (Identity / ops bootstrap).": "Thành viên đang hoạt động. Thêm bằng UUID người dùng đã có.",
    "Read-only: only project owners can add or revoke members.": "Chỉ đọc: chỉ OWNER mới thêm hoặc thu hồi thành viên.",
    "User": "Người dùng",
    "Role": "Vai trò",
    "Processing defaults (Gate 0 D4: WAV / PCM / 16 kHz / mono / loudness off).": "Mặc định xử lý (Gate 0 D4: WAV / PCM / 16 kHz / mono / tắt loudness).",
    "Read-only: only project owners can change settings.": "Chỉ đọc: chỉ OWNER mới đổi cài đặt.",
    "ASR preferences": "Tuỳ chọn ASR",
    "System defaults or custom provider settings (Gate W7.1).": "Mặc định hệ thống hoặc cấu hình nhà cung cấp riêng (Gate W7.1).",
    "System ASR admin": "Quản trị ASR hệ thống",
    "AI preferences": "Tuỳ chọn AI",
    "Ollama settings for assist features (Gate W8.1).": "Cấu hình Ollama cho tính năng hỗ trợ (Gate W8.1).",
    "System AI admin": "Quản trị AI hệ thống",
    "System ASR defaults": "Mặc định ASR hệ thống",
    "Admin defaults for “system defaults” users (Gate W7.3).": "Mặc định quản trị cho người dùng “system defaults” (Gate W7.3).",
    "Account ASR preferences": "Tuỳ chọn ASR tài khoản",
    "System AI defaults": "Mặc định AI hệ thống",
    "Admin defaults for Ollama assists (Gate W8.1).": "Mặc định quản trị cho hỗ trợ Ollama (Gate W8.1).",
    "Account AI preferences": "Tuỳ chọn AI tài khoản",
    "Create Segment is unavailable until source duration is known.": "Không tạo đoạn được cho đến khi biết thời lượng nguồn.",
    "Metadata is still pending.": "Metadata vẫn đang chờ.",
    "Metadata fetch failed — try Refresh metadata.": "Lấy metadata thất bại — thử Làm mới metadata.",
    "Refresh metadata": "Làm mới metadata",
    "Start": "Bắt đầu",
    "End": "Kết thúc",
    "No segments on this source yet.": "Nguồn này chưa có đoạn.",
    "View all project segments": "Xem mọi đoạn của dự án",
    "Create segment": "Tạo đoạn",
    "Bounds are source-relative seconds. OWNER only. Opens Segment Workspace after create.": "Biên tính theo giây trên nguồn. Chỉ OWNER. Mở Workspace sau khi tạo.",
    "Transcript": "Bản chép",
    "Signed in.": "Đã đăng nhập.",
    "Account created.": "Đã tạo tài khoản.",
    "Identity created.": "Đã tạo danh tính.",
    "Unknown or inactive user": "Người dùng không tồn tại hoặc không hoạt động",
    "Identity selected.": "Đã chọn danh tính.",
    "Identity cleared.": "Đã xoá danh tính.",
    "Project created.": "Đã tạo dự án.",
    "Project archived.": "Đã lưu trữ dự án.",
    "Segment created.": "Đã tạo đoạn.",
    "Metadata refresh queued.": "Đã xếp hàng làm mới metadata.",
    "Invalid segment bounds.": "Biên đoạn không hợp lệ.",
    "Segment not found": "Không tìm thấy đoạn",
    "Saved.": "Đã lưu.",
    "Transcript saved.": "Đã lưu bản chép.",
    "Segment deleted.": "Đã xoá đoạn.",
    "Annotation assigned.": "Đã gán annotation.",
    "Annotation removed.": "Đã gỡ annotation.",
    "Processing job queued.": "Đã xếp hàng xử lý.",
    "Cancellation requested.": "Đã yêu cầu huỷ.",
    "Retry queued.": "Đã xếp hàng thử lại.",
    "ASR job queued.": "Đã xếp hàng ASR.",
    "Reused equivalent ASR result.": "Dùng lại kết quả ASR tương đương.",
    "ASR text applied to transcript.": "Đã áp văn bản ASR vào bản chép.",
    "AI assist candidate ready.": "Ứng viên hỗ trợ AI đã sẵn sàng.",
    "AI assist applied.": "Đã áp hỗ trợ AI.",
    "Invalid form values.": "Giá trị biểu mẫu không hợp lệ.",
    "Label created.": "Đã tạo nhãn.",
    "Label saved.": "Đã lưu nhãn.",
    "Label deactivated.": "Đã vô hiệu hoá nhãn.",
    "Label activated.": "Đã kích hoạt nhãn.",
    "Invalid label values.": "Giá trị nhãn không hợp lệ.",
    "Member added.": "Đã thêm thành viên.",
    "Cannot revoke your own membership in the UI.": "Không thể tự thu hồi tư cách thành viên trên giao diện.",
    "Member revoked.": "Đã thu hồi thành viên.",
    "Settings saved. Existing jobs keep their snapshots.": "Đã lưu cài đặt. Việc đang chạy giữ snapshot cũ.",
    "Invalid settings values.": "Giá trị cài đặt không hợp lệ.",
    "ASR preferences saved.": "Đã lưu tuỳ chọn ASR.",
    "Only ASR admins can update system defaults.": "Chỉ quản trị ASR mới cập nhật mặc định hệ thống.",
    "System ASR reset to environment defaults.": "Đã đặt lại ASR hệ thống về mặc định môi trường.",
    "System ASR defaults saved.": "Đã lưu mặc định ASR hệ thống.",
    "AI provider is disabled.": "Nhà cung cấp AI đang tắt.",
    "AI preferences saved.": "Đã lưu tuỳ chọn AI.",
    "Only AI admins can update system defaults.": "Chỉ quản trị AI mới cập nhật mặc định hệ thống.",
    "System AI reset to environment defaults.": "Đã đặt lại AI hệ thống về mặc định môi trường.",
    "System AI defaults saved.": "Đã lưu mặc định AI hệ thống.",
    "Signed in as <strong>%(name)s</strong>": "Đã đăng nhập với tên <strong>%(name)s</strong>",
    "Segment #%(n)s": "Đoạn #%(n)s",
}


def collect_msgids() -> set[str]:
    found: set[str] = set(VI.keys())
    pat = re.compile(r"""\{%\s*trans\s+["'](.*?)["']\s*%\}""")
    for path in TEMPLATES.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        found.update(pat.findall(text))
    return found


def write_po(lang: str, translations: dict[str, str]) -> None:
    po = polib.POFile()
    po.metadata = {
        "Project-Id-Version": "YouAudioLab_Django",
        "Language": lang,
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
        "Plural-Forms": "nplurals=1; plural=0;" if lang == "vi" else "nplurals=2; plural=(n != 1);",
    }
    for msgid in sorted(collect_msgids()):
        entry = polib.POEntry(msgid=msgid, msgstr=translations.get(msgid, "" if lang == "en" else translations.get(msgid, "")))
        if lang == "vi":
            entry.msgstr = VI.get(msgid, "")
        else:
            entry.msgstr = ""  # English source language
        po.append(entry)
    out_dir = ROOT / "locale" / lang / "LC_MESSAGES"
    out_dir.mkdir(parents=True, exist_ok=True)
    po_path = out_dir / "django.po"
    mo_path = out_dir / "django.mo"
    po.save(str(po_path))
    po.save_as_mofile(str(mo_path))
    print(f"Wrote {po_path} ({len(po)} entries) and {mo_path}")


def main() -> None:
    write_po("vi", VI)
    write_po("en", {})
    missing = [k for k in collect_msgids() if k not in VI]
    if missing:
        print(f"Missing VI translations ({len(missing)}):")
        for m in missing[:40]:
            print(f"  - {m!r}")


if __name__ == "__main__":
    main()
