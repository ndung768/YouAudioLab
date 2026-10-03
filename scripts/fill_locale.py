"""Fill Vietnamese translations for all catalog entries and recompile .mo."""

from __future__ import annotations

import re
from pathlib import Path

import polib

ROOT = Path(__file__).resolve().parents[1]

VI_EXTRA = {
    "(you)": "(bạn)",
    "AI assist": "Trợ giúp AI",
    "AI provider disabled.": "Nhà cung cấp AI đang tắt.",
    "ASR jobs": "Job ASR",
    "ASR runs": "Lần chạy ASR",
    "ASR transcript": "Bản ghi ASR",
    "Account": "Tài khoản",
    "Account profile and ASR / AI provider configuration.": "Hồ sơ tài khoản và cấu hình ASR / AI.",
    "Actions": "Hành động",
    "Activate": "Kích hoạt",
    "Active": "Hoạt động",
    "Add annotation": "Thêm chú thích",
    "Add new label": "Thêm nhãn mới",
    "Add member": "Thêm thành viên",
    "Annotations": "Chú thích",
    "Applied": "Đã áp dụng",
    "Apply": "Áp dụng",
    "Apply my numbers": "Áp dụng số của tôi",
    "Apply to canonical transcript": "Áp dụng vào bản ghi chính",
    "Archive project": "Lưu trữ dự án",
    "Archive this project? It remains readable but writes stop.": "Lưu trữ dự án này? Vẫn đọc được nhưng ngừng ghi.",
    "Artifact id": "ID artifact",
    "Ask a project owner to create labels.": "Nhờ chủ dự án tạo nhãn.",
    "Assign a label to create the first episode.": "Gán một nhãn để tạo episode đầu tiên.",
    "Assign label": "Gán nhãn",
    "Cancel": "Hủy",
    "Channels": "Kênh",
    "Clear stored key": "Xóa khóa đã lưu",
    "Clear stored system key": "Xóa khóa hệ thống đã lưu",
    "Color": "Màu",
    "Create": "Tạo",
    "Create a taxonomy label to start annotating segments.": "Tạo nhãn phân loại để bắt đầu chú thích đoạn.",
    "Create a label in one of your projects to start annotating segments.": "Tạo nhãn trong dự án của bạn để bắt đầu chú thích đoạn.",
    "Create label": "Tạo nhãn",
    "Current": "Hiện tại",
    "Current artifact": "Artifact hiện tại",
    "Current artifact:": "Artifact hiện tại:",
    "Current audio": "Âm thanh hiện tại",
    "Current job:": "Job hiện tại:",
    "Current system defaults:": "Mặc định hệ thống hiện tại:",
    "Custom": "Tùy chỉnh",
    "Danger zone": "Vùng nguy hiểm",
    "Deactivate": "Vô hiệu hóa",
    "Description": "Mô tả",
    "Deactivating blocks new assignments; historical episodes remain.": "Vô hiệu hóa chặn gán mới; episode lịch sử vẫn giữ.",
    "Default model": "Mô hình mặc định",
    "Definition": "Định nghĩa",
    "Definition revision:": "Phiên bản định nghĩa:",
    "Device / compute": "Thiết bị / tính toán",
    "Discard draft": "Hủy bản nháp",
    "Download WAV": "Tải WAV",
    "Download is available after the artifact is verified.": "Có thể tải sau khi artifact được xác minh.",
    "Edit": "Sửa",
    "Effective:": "Hiệu lực:",
    "Enabled": "Bật",
    "Encoding": "Mã hóa",
    "Everyone": "Mọi người",
    "Format": "Định dạng",
    "From job": "Từ job",
    "Gate 0 D1 (ahead of React F6): project becomes ARCHIVED. Writes stop; research metadata remains.": "Gate 0 D1: dự án chuyển sang ARCHIVED. Ngừng ghi; metadata nghiên cứu vẫn giữ.",
    "Generate a machine transcript for the current verified artifact. Apply copies text into the canonical transcript (no revision bump).": "Tạo bản ghi máy cho artifact đã xác minh. Áp dụng sẽ chép vào bản ghi chính (không tăng phiên bản).",
    "Generate transcript": "Tạo bản ghi",
    "HTML5 player — no waveform in MVP.": "Trình phát HTML5 — chưa có dạng sóng trong MVP.",
    "Historical only — never current": "Chỉ lịch sử — không bao giờ là hiện tại",
    "History (removed)": "Lịch sử (đã gỡ)",
    "Inactive": "Không hoạt động",
    "Inactive in taxonomy": "Không hoạt động trong phân loại",
    "in use": "đang dùng",
    "Join or create a project to see labels here.": "Tham gia hoặc tạo dự án để xem nhãn tại đây.",
    "Jobs extract audio for a specific definition revision. Polling runs while queued or running. Retry creates a new job id.": "Job trích âm thanh theo một phiên bản định nghĩa. Tự làm mới khi đang xếp hàng/chạy. Thử lại tạo job id mới.",
    "Label name": "Tên nhãn",
    "Label settings": "Cài đặt nhãn",
    "Label added to project.": "Đã thêm nhãn vào dự án.",
    "Label removed from project.": "Đã bỏ nhãn khỏi dự án.",
    "Label created and added to project.": "Đã tạo nhãn và thêm vào dự án.",
    "Label deleted.": "Đã xóa nhãn.",
    "Inactive in catalog": "Không hoạt động trong danh mục",
    "Catalog": "Danh mục",
    "Display name override": "Ghi đè tên hiển thị",
    "Description override": "Ghi đè mô tả",
    "Color override": "Ghi đè màu",
    "Remove from project": "Gỡ khỏi dự án",
    "Remove this label from the project? Existing annotations keep their history.": "Gỡ nhãn này khỏi dự án? Chú thích hiện có vẫn giữ lịch sử.",
    "No labels added to this project yet.": "Chưa có nhãn nào trong dự án.",
    "Available label": "Nhãn có thể thêm",
    "Available labels": "Nhãn có thể thêm",
    "All active catalog labels are already in this project, or your catalog is empty.": "Mọi nhãn đang hoạt động đã có trong dự án, hoặc danh mục trống.",
    "Create label in catalog and add here": "Tạo nhãn trong danh mục và thêm vào đây",
    "Personal label catalog. Assign labels to projects from each project's label settings.": "Danh mục nhãn cá nhân. Gán nhãn vào dự án từ cài đặt nhãn của từng dự án.",
    "Projects": "Dự án",
    "Delete": "Xóa",
    "Delete this label from your catalog?": "Xóa nhãn này khỏi danh mục?",
    "Create labels here, then assign them to projects from project label settings.": "Tạo nhãn tại đây, rồi gán vào dự án từ cài đặt nhãn dự án.",
    "Note: Deactivating a label hides it from “available labels” when adding to new projects. Labels already assigned to projects stay usable. Labels in use cannot be deleted.": "Lưu ý: Vô hiệu hóa nhãn sẽ ẩn khỏi “nhãn có thể thêm” khi thêm vào dự án mới. Nhãn đã gán trong dự án vẫn dùng được. Nhãn đang dùng không thể xóa.",
    "Manage labels from your catalog (project owner) for this project.": "Quản lý nhãn từ danh mục của bạn (chủ dự án) cho dự án này.",
    "Read-only: only project owners can add or remove project labels.": "Chỉ đọc: chỉ chủ dự án mới thêm hoặc gỡ nhãn khỏi dự án.",
    "Active label in project": "Nhãn đang dùng trong dự án",
    "Active labels in project": "Nhãn đang dùng trong dự án",
    "Used in %(n)s annotation episode(s)": "Dùng trong %(n)s episode chú thích",
    "Labels across projects you belong to. Edit and manage labels in projects you own.": "Nhãn trong các dự án bạn tham gia. Chỉnh sửa nhãn ở dự án bạn sở hữu.",
    "Local compute type": "Kiểu tính toán local",
    "Local device": "Thiết bị local",
    "Local draft was kept.": "Bản nháp cục bộ đã được giữ.",
    "Local model": "Mô hình local",
    "Login": "Đăng nhập",
    "Loudness normalization": "Chuẩn hóa độ lớn",
    "Mine": "Của tôi",
    "Model": "Mô hình",
    "Model B: each row is one annotation episode": "Model B: mỗi dòng là một episode chú thích",
    "Model:": "Mô hình:",
    "Name (required)": "Tên (bắt buộc)",
    "Naming convention": "Quy ước đặt tên",
    "Need a transcript first.": "Cần có bản ghi trước.",
    "No AI assist candidates yet.": "Chưa có ứng viên trợ giúp AI.",
    "No ASR runs yet.": "Chưa có lần chạy ASR.",
    "No active annotations": "Không có chú thích đang dùng",
    "No active labels in this project.": "Chưa có nhãn đang hoạt động trong dự án.",
    "No active members": "Không có thành viên đang hoạt động",
    "No jobs yet": "Chưa có job",
    "No labels": "Chưa có nhãn",
    "No labels yet": "Chưa có nhãn",
    "Note: You can only edit or deactivate labels in projects you own. Labels with active annotations remain in history when deactivated.": "Lưu ý: Bạn chỉ có thể sửa hoặc vô hiệu hóa nhãn trong dự án bạn sở hữu. Nhãn đã dùng trong chú thích vẫn giữ trong lịch sử khi bị vô hiệu hóa.",
    "No processing jobs have been submitted for this segment.": "Chưa có job xử lý nào cho đoạn này.",
    "Off": "Tắt",
    "Ollama URL": "URL Ollama",
    "Ollama base URL": "URL gốc Ollama",
    "Ollama candidates for cleanup, labels, and metadata. Nothing writes until you Apply. This is not ASR.": "Ứng viên Ollama cho làm sạch, nhãn và metadata. Chỉ ghi khi bạn Áp dụng. Đây không phải ASR.",
    "Ollama model": "Mô hình Ollama",
    "On": "Bật",
    "Open on YouTube": "Mở trên YouTube",
    "OpenAI": "OpenAI",
    "OpenAI API key": "Khóa API OpenAI",
    "OpenAI base URL": "URL gốc OpenAI",
    "OpenAI default model": "Mô hình OpenAI mặc định",
    "OpenAI enabled": "Bật OpenAI",
    "OpenAI model": "Mô hình OpenAI",
    "OpenAI system key:": "Khóa OpenAI hệ thống:",
    "Output format": "Định dạng đầu ra",
    "Override provider/model for this job": "Ghi đè provider/model cho job này",
    "Paste a user UUID that already exists. Default role is ANNOTATOR.": "Dán UUID người dùng đã tồn tại. Vai trò mặc định là ANNOTATOR.",
    "Processing": "Xử lý",
    "Processing defaults": "Mặc định xử lý",
    "Active annotation episodes": "Episode chú thích đang hoạt động",
    "Active jobs": "Job đang chạy",
    "Active (queued/running)": "Đang xếp hàng/chạy",
    "Add YouTube source": "Thêm nguồn YouTube",
    "Annotated": "Đã chú thích",
    "Annotation summary": "Tóm tắt chú thích",
    "Annotator": "Người chú thích",
    "Annotator productivity": "Năng suất người chú thích",
    "Archive stops writes; research metadata remains readable.": "Lưu trữ ngừng ghi; metadata nghiên cứu vẫn đọc được.",
    "Audio pipeline and annotation metrics for this project.": "Chỉ số pipeline âm thanh và chú thích cho dự án này.",
    "Continue labeling": "Tiếp tục gán nhãn",
    "Edit settings": "Sửa cài đặt",
    "Episodes": "Episode",
    "Extract audio active": "Trích âm đang chạy",
    "Failed jobs": "Job thất bại",
    "Import a YouTube source and create segments before labeling.": "Nhập nguồn YouTube và tạo đoạn trước khi gán nhãn.",
    "Manage members": "Quản lý thành viên",
    "No annotations yet.": "Chưa có chú thích.",
    "Open workspace": "Mở workspace",
    "Processing jobs": "Job xử lý",
    "Profile": "Hồ sơ",
    "Progress": "Tiến độ",
    "Project labels assigned": "Nhãn đã gán trong dự án",
    "Project labels": "Nhãn dự án",
    "Quick overview": "Tổng quan nhanh",
    "Segment #%(idx)s — open the workspace to assign labels, run ASR, and review audio.": "Đoạn #%(idx)s — mở workspace để gán nhãn, chạy ASR và nghe âm thanh.",
    "Segment processing status": "Trạng thái xử lý đoạn",
    "Team": "Nhóm",
    "View all": "Xem tất cả",
    "View progress dashboard": "Xem bảng tiến độ",
    "With artifact": "Có artifact",
    "With transcript": "Có bản ghi",
    "All segments": "Tất cả đoạn",
    "ASR active": "ASR đang chạy",
    "Project": "Dự án",
    "Provider": "Nhà cung cấp",
    "Provider:": "Nhà cung cấp:",
    "Read-only for ANNOTATOR.": "Chỉ đọc đối với ANNOTATOR.",
    "Read-only — OWNER required to edit bounds.": "Chỉ đọc — cần OWNER để sửa biên.",
    "Read-only: only project owners can generate or apply ASR.": "Chỉ đọc: chỉ chủ dự án mới tạo hoặc áp dụng ASR.",
    "Read-only: only project owners can submit, cancel, or retry jobs.": "Chỉ đọc: chỉ chủ dự án mới gửi, hủy hoặc thử lại job.",
    "Read-only: only project owners can suggest or apply AI assists.": "Chỉ đọc: chỉ chủ dự án mới gợi ý hoặc áp dụng AI.",
    "Read-only: you are not an AI admin in this environment.": "Chỉ đọc: bạn không phải quản trị AI trong môi trường này.",
    "Read-only: you are not an ASR admin in this environment.": "Chỉ đọc: bạn không phải quản trị ASR trong môi trường này.",
    "Remove": "Gỡ",
    "Removed": "Đã gỡ",
    "Request cancellation": "Yêu cầu hủy",
    "Reset to environment": "Đặt lại theo môi trường",
    "Resolve / sanity check": "Resolve / kiểm tra nhanh",
    "Retry": "Thử lại",
    "Revision": "Phiên bản",
    "Revision conflict": "Xung đột phiên bản",
    "Revoke": "Thu hồi",
    "Settings": "Cài đặt",
    "Settings sections": "Mục cài đặt",
    "Run again": "Chạy lại",
    "Sample rate (Hz)": "Tần số lấy mẫu (Hz)",
    "Save": "Lưu",
    "Save definition": "Lưu định nghĩa",
    "Save preferences": "Lưu tùy chọn",
    "Save settings": "Lưu cài đặt",
    "Save system defaults": "Lưu mặc định hệ thống",
    "Save transcript": "Lưu bản ghi",
    "Scope": "Phạm vi",
    "Select a label…": "Chọn nhãn…",
    "Show removed history": "Hiện lịch sử đã gỡ",
    "Size": "Kích thước",
    "Soft-delete segment": "Xóa mềm đoạn",
    "Soft-delete this segment? It can remain in history lists later.": "Xóa mềm đoạn này? Có thể vẫn hiện trong danh sách lịch sử sau.",
    "Sort order": "Thứ tự",
    "Source detail": "Chi tiết nguồn",
    "Source duration:": "Thời lượng nguồn:",
    "Source:": "Nguồn:",
    "Stale": "Lỗi thời",
    "Stale — not applicable": "Lỗi thời — không áp dụng được",
    "Submit a job to extract audio for the current revision.": "Gửi job để trích âm thanh cho phiên bản hiện tại.",
    "Submit an extract job first — ASR needs a verified audio artifact.": "Hãy gửi job trích xuất trước — ASR cần artifact âm thanh đã xác minh.",
    "Submit job": "Gửi job",
    "Suggest cleanup": "Gợi ý làm sạch",
    "Suggest labels": "Gợi ý nhãn",
    "Suggest metadata": "Gợi ý metadata",
    "System": "Hệ thống",
    "System OpenAI API key": "Khóa API OpenAI hệ thống",
    "System:": "Hệ thống:",
    "Test connection / resolve": "Kiểm tra kết nối / resolve",
    "The server rejected": "Máy chủ từ chối",
    "Unexpected empty membership list for this project.": "Danh sách thành viên trống bất thường cho dự án này.",
    "Unverified": "Chưa xác minh",
    "Updated": "Cập nhật",
    "Use Download WAV on the audio player above.": "Dùng Tải WAV trên trình phát phía trên.",
    "Use system defaults": "Dùng mặc định hệ thống",
    "Use the ASR and AI tabs to configure transcription and assist providers for your workspace.": "Dùng tab ASR và AI để cấu hình chuyển lời và trợ giúp AI cho không gian làm việc.",
    "Usage count": "Số lần dùng",
    "User id": "ID người dùng",
    "User id (required)": "ID người dùng (bắt buộc)",
    "Verified": "Đã xác minh",
    "Wait for the active job to finish.": "Chờ job đang chạy hoàn tất.",
    "You have no active annotations on this segment.": "Bạn chưa có chú thích đang dùng trên đoạn này.",
    "Your labels": "Nhãn của bạn",
    "Your local draft was preserved. Choose Apply or Discard — nothing was written to the server.": "Bản nháp cục bộ đã được giữ. Chọn Áp dụng hoặc Hủy — chưa ghi gì lên máy chủ.",
    "configured": "đã cấu hình",
    "disabled": "tắt",
    "enabled": "bật",
    "no": "không",
    "not set": "chưa đặt",
    "optional": "tùy chọn",
    "unknown": "không rõ",
    "yes": "có",
    "•••• configured": "•••• đã cấu hình",
    "← Back to segments": "← Quay lại các đoạn",
    # status badges
    "Metadata pending": "Đang chờ metadata",
    "Ready": "Sẵn sàng",
    "Metadata failed": "Metadata thất bại",
    "Pending": "Chờ",
    "Completed": "Hoàn tất",
    "Failed": "Thất bại",
    "Queued": "Đang xếp hàng",
    "Running": "Đang chạy",
    "Succeeded": "Thành công",
    "Out of date": "Lỗi thời",
    "Cancelled": "Đã hủy",
    "Cancellation requested…": "Đã yêu cầu hủy…",
    # JS / common
    "Loading audio…": "Đang tải âm thanh…",
    "Could not load artifact audio.": "Không tải được âm thanh artifact.",
    "Artifact exists but is not verified yet.": "Artifact đã có nhưng chưa được xác minh.",
    "none": "không có",
    "bytes": "byte",
    "Peers can share the same label. Re-assign after remove creates a": "Người khác có thể dùng cùng nhãn. Gán lại sau khi gỡ sẽ tạo",
    "new": "mới",
    "episode.": "episode.",
    "Create labels on the Labels screen (F6), or via API.": "Tạo nhãn ở màn Nhãn (F6), hoặc qua API.",
    # views conflict
    "Someone else updated this segment. Your save was not applied.": "Người khác đã cập nhật đoạn này. Lưu của bạn chưa được áp dụng.",
    "This source already exists in the project.": "Nguồn này đã tồn tại trong dự án.",
    "Source imported (metadata pending). Fetch queued.": "Đã nhập nguồn (đang chờ metadata). Đã xếp hàng lấy dữ liệu.",
    "An active job already exists for this segment.": "Đã có job đang chạy cho đoạn này.",
    "That label is inactive. Choose an active label.": "Nhãn đó không hoạt động. Chọn nhãn đang dùng.",
    "This project is archived and cannot be modified.": "Dự án đã lưu trữ và không thể chỉnh sửa.",
    "This segment was soft-deleted.": "Đoạn này đã bị xóa mềm.",
    "Enter a valid user UUID (X-User-Id).": "Nhập UUID người dùng hợp lệ (X-User-Id).",
}


def extract_blocktrans() -> dict[str, str]:
    """Map English msgid (with %(var)s) → empty; collect from templates."""
    found: dict[str, str] = {}
    pat = re.compile(
        r"\{%\s*blocktrans(?:\s+with\s+[^%]+)?\s*%\}(.*?)\{%\s*endblocktrans\s*%\}",
        re.DOTALL,
    )
    var_pat = re.compile(r"\{\{\s*(\w+)\s*\}\}")
    for path in (ROOT / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        for body in pat.findall(text):
            msgid = var_pat.sub(r"%(\1)s", " ".join(body.split()))
            found[msgid] = ""
    return found


BLOCKTRANS_VI = {
    "Segment #%(n)s": "Đoạn #%(n)s",
    "Duration %(d)s": "Thời lượng %(d)s",
    "Duration %(d)ss": "Thời lượng %(d)s",
    "No current audio artifact for definition revision %(n)s. Submit a processing job to produce one.": "Chưa có artifact âm thanh cho phiên bản định nghĩa %(n)s. Gửi job xử lý để tạo.",
    "Server bounds: %(a)ss – %(b)ss · Your draft: %(c)ss – %(d)ss": "Biên máy chủ: %(a)ss – %(b)ss · Bản nháp: %(c)ss – %(d)ss",
    "Signed in as <strong>%(name)s</strong>": "Đã đăng nhập với tên <strong>%(name)s</strong>",
    "Edit “%(name)s”": "Sửa “%(name)s”",
    "Edit \"%(name)s\"": "Sửa \"%(name)s\"",
    "You (%(name)s)": "Bạn (%(name)s)",
    "Annotator %(id)s": "Người chú thích %(id)s",
    "rev %(n)s": "rev %(n)s",
    "attempt %(n)s": "lần thử %(n)s",
    "Format %(fmt)s": "Định dạng %(fmt)s",
    "Size %(n)s bytes": "Kích thước %(n)s byte",
    "Someone else updated this segment (now revision %(current)s). Your save was not applied.": "Người khác đã cập nhật đoạn này (phiên bản %(current)s). Lưu của bạn chưa được áp dụng.",
    "Segment #%(idx)s — open the workspace to assign labels, run ASR, and review audio.": "Đoạn #%(idx)s — mở workspace để gán nhãn, chạy ASR và nghe âm thanh.",
    "%(n)s active member in this project.": "%(n)s thành viên đang hoạt động trong dự án.",
    "%(n)s active members in this project.": "%(n)s thành viên đang hoạt động trong dự án.",
    "%(n)s segment(s)": "%(n)s đoạn",
}


def fill_po(lang: str) -> None:
    path = ROOT / "locale" / lang / "LC_MESSAGES" / "django.po"
    po = polib.pofile(str(path)) if path.exists() else polib.POFile()
    if not path.exists():
        po.metadata = {
            "Project-Id-Version": "YouAudioLab_Django",
            "Language": lang,
            "MIME-Version": "1.0",
            "Content-Type": "text/plain; charset=UTF-8",
            "Content-Transfer-Encoding": "8bit",
        }

    existing = {e.msgid: e for e in po}

    # Load prior VI from build_locale if present in current msgstr
    # Add any missing msgids from templates via simple trans extract
    trans_pat = re.compile(r"""\{%\s*trans\s+["'](.*?)["']\s*%\}""")
    msgids = set()
    for p in (ROOT / "templates").rglob("*.html"):
        msgids.update(trans_pat.findall(p.read_text(encoding="utf-8")))
    msgids.update(VI_EXTRA.keys())
    msgids.update(BLOCKTRANS_VI.keys())
    msgids.update(extract_blocktrans().keys())
    # badge + js strings
    for s in [
        "Metadata pending", "Ready", "Metadata failed", "Active", "Archived",
        "Pending", "Processing", "Completed", "Failed", "Inactive",
        "Queued", "Running", "Succeeded", "Out of date", "Cancelled",
        "Cancellation requested…", "Loading audio…",
        "Could not load artifact audio.", "Artifact exists but is not verified yet.",
    ]:
        msgids.add(s)

    for msgid in sorted(msgids):
        if not msgid:
            continue
        if msgid not in existing:
            entry = polib.POEntry(msgid=msgid, msgstr="")
            po.append(entry)
            existing[msgid] = entry

    if lang == "vi":
        for entry in po:
            if not entry.msgid:
                continue
            if entry.msgid in BLOCKTRANS_VI:
                entry.msgstr = BLOCKTRANS_VI[entry.msgid]
            elif entry.msgid in VI_EXTRA:
                entry.msgstr = VI_EXTRA[entry.msgid]
            # keep existing non-empty msgstr from previous fill / build_locale

    mo_path = path.with_suffix(".mo")
    po.save(str(path))
    po.save_as_mofile(str(mo_path))
    empty = sum(1 for e in po if e.msgid and not e.msgstr)
    print(f"{lang}: {len(po)} entries, empty={empty} → {mo_path.name}")


def main() -> None:
    # Merge with existing translations already in vi.po
    fill_po("vi")
    fill_po("en")


if __name__ == "__main__":
    main()
