SYSTEM_PROMPT = (
    "Bạn là trợ lý tri thức của khoa. CHỈ trả lời dựa trên NGỮ CẢNH được cấp bên dưới. "
    "Đánh số nguồn [1], [2]... tương ứng thứ tự ngữ cảnh khi trích dẫn. "
    "Nếu ngữ cảnh không đủ thông tin, hãy nói rõ là bạn không tìm thấy thông tin trong kho — "
    "TUYỆT ĐỐI không bịa đặt."
)


def build_context_block(contexts: list[dict]) -> str:
    if not contexts:
        return "(không có ngữ cảnh liên quan)"
    parts = []
    for i, c in enumerate(contexts, start=1):
        page = f", trang {c['page_ref']}" if c.get("page_ref") else ""
        parts.append(f"[{i}] (Nguồn: {c['title']}{page})\n{c['content']}")
    return "\n\n".join(parts)
