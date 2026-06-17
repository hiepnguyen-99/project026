from __future__ import annotations

import os
import re

from mcp.server.fastmcp import FastMCP

from .database import connection, transaction
from .services import ask, list_documents, rag_documents

mcp = FastMCP("EduVault Knowledge Base")


def _resolve_user(db, token: str) -> dict | None:
    row = db.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.code=s.user_code WHERE s.token=? AND u.active=1",
        (token,),
    ).fetchone()
    return dict(row) if row else None


def _token() -> str:
    token = os.getenv("EDUVAULT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("EDUVAULT_TOKEN chưa được thiết lập. Thêm biến môi trường EDUVAULT_TOKEN vào cấu hình MCP client.")
    return token


@mcp.tool()
def ask_assistant(question: str) -> str:
    """Đặt câu hỏi và nhận câu trả lời AI từ kho tri thức EduVault của bạn.

    Bao gồm trích dẫn nguồn tài liệu liên quan.
    """
    with transaction() as db:
        user = _resolve_user(db, _token())
        if not user:
            return "Lỗi: session token không hợp lệ hoặc đã hết hạn. Đăng nhập lại vào EduVault và cập nhật EDUVAULT_TOKEN."
        try:
            result = ask(db, user, question)
        except Exception as exc:
            return f"Lỗi khi truy vấn kho tri thức: {exc}"
        answer = result.get("answer", "Không tìm thấy câu trả lời.")
        citations = result.get("citations", [])
        if citations:
            sources = "\n".join(f"  - [{c['topic']}] {c['title']}" for c in citations)
            return f"{answer}\n\nNguồn tài liệu tham khảo:\n{sources}"
        return answer


@mcp.tool()
def list_accessible_documents() -> str:
    """Liệt kê tất cả tài liệu bạn có quyền truy cập trong EduVault.

    Bao gồm tài liệu của bạn, tài liệu công khai, và tài liệu được chia sẻ đã duyệt.
    """
    with connection() as db:
        user = _resolve_user(db, _token())
        if not user:
            return "Lỗi: session token không hợp lệ hoặc đã hết hạn."
        docs = list_documents(db, user)
        if not docs:
            return "Không tìm thấy tài liệu nào trong phạm vi truy cập của bạn."
        lines = [
            f"  - [{d['doc_type']}] {d['title']} | Chủ đề: {d['topic']} | Quyền: {d['visibility']}"
            for d in docs
        ]
        return f"Tìm thấy {len(docs)} tài liệu:\n" + "\n".join(lines)


@mcp.tool()
def search_knowledge_base(query: str) -> str:
    """Tìm kiếm tài liệu theo từ khoá hoặc chủ đề trong EduVault.

    Trả về danh sách tài liệu phù hợp nhất (tối đa 10).
    """
    with connection() as db:
        user = _resolve_user(db, _token())
        if not user:
            return "Lỗi: session token không hợp lệ hoặc đã hết hạn."
        docs = rag_documents(db, user)
        if not docs:
            return "Không có tài liệu nào trong phạm vi truy cập của bạn."
        words = {w for w in re.findall(r"\w+", query.lower(), re.UNICODE) if len(w) > 2}
        if not words:
            return "Từ khoá tìm kiếm quá ngắn (cần ít nhất 3 ký tự)."
        matched: list[tuple[int, dict]] = []
        for doc in docs:
            searchable = f"{doc['title']} {doc['topic']} {doc['doc_type']} {doc.get('summary', '')}".lower()
            score = sum(1 for w in words if w in searchable)
            if score:
                matched.append((score, doc))
        matched.sort(key=lambda x: x[0], reverse=True)
        if not matched:
            return f"Không tìm thấy tài liệu nào phù hợp với '{query}'."
        lines = [
            f"  - [{d['doc_type']}] {d['title']} | Chủ đề: {d['topic']}"
            for _, d in matched[:10]
        ]
        return f"Tìm thấy {len(matched)} tài liệu phù hợp với '{query}':\n" + "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
