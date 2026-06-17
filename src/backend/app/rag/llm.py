from openai import OpenAI

from ..core.config import settings
from .prompts import SYSTEM_PROMPT, build_context_block

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def generate_answer(query: str, contexts: list[dict]) -> str:
    """Sinh câu trả lời tiếng Việt dựa trên ngữ cảnh đã truy xuất."""
    context_block = build_context_block(contexts)
    resp = _get_client().chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Câu hỏi: {query}\n\nNgữ cảnh:\n{context_block}"},
        ],
    )
    return resp.choices[0].message.content or ""
