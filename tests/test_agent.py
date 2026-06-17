import json

import pytest

from src.backend.app.rag.tools import build_tools


def _get_tool(tools, name):
    return next(t for t in tools if t.name == name)


@pytest.mark.asyncio
async def test_tool_search_respects_permission(session_factory, seed_docs, patch_embeddings, requester):
    """search_documents (tool agent gọi) chỉ trả tài liệu được phép — không lộ Private người khác."""
    async with session_factory() as db:
        sink: list[dict] = []
        tools = build_tools(db, requester, sink)
        result = await _get_tool(tools, "search_documents").ainvoke({"query": "noi dung"})

    titles = [c["title"] for c in sink]
    assert "Tai lieu PUBLIC" in titles
    assert "Tai lieu PRIVATE" not in titles
    assert "noi dung rieng tu" not in result  # nội dung Private KHÔNG xuất hiện


@pytest.mark.asyncio
async def test_tool_summarize_refuses_private(session_factory, seed_docs, requester):
    """summarize_document từ chối tài liệu Private của người khác."""
    async with session_factory() as db:
        tools = build_tools(db, requester, [])
        result = await _get_tool(tools, "summarize_document").ainvoke(
            {"document_title": "Tai lieu PRIVATE"}
        )
    assert "không có quyền" in result.lower() or "không tìm thấy" in result.lower()


@pytest.mark.asyncio
async def test_tool_list_documents_only_permitted(session_factory, seed_docs, requester):
    async with session_factory() as db:
        tools = build_tools(db, requester, [])
        result = await _get_tool(tools, "list_documents").ainvoke({})
    titles = json.loads(result)
    assert "Tai lieu PUBLIC" in titles
    assert "Tai lieu PRIVATE" not in titles
