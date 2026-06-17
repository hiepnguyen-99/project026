from openai import OpenAI

from ..core.config import settings

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Vector hóa danh sách văn bản (model hỗ trợ tiếng Việt, cấu hình qua .env)."""
    if not texts:
        return []
    resp = _get_client().embeddings.create(model=settings.EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in resp.data]
