from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user
from ...db.session import get_db
from ...models.user import User
from ...rag.agent import run_agent
from ...rag.retriever import find_restricted
from ...schemas.search import Citation, RestrictedItem, SearchRequest, SearchResponse

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(
    payload: SearchRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Hỏi đáp tiếng Việt: LangGraph agent (đã gác quyền) → answer + citations + restricted."""
    answer, contexts = await run_agent(db, user, payload.query)
    restricted = await find_restricted(db, user)

    citations = [
        Citation(file=c["title"], page=c.get("page_ref"), uri=c["storage_uri"]) for c in contexts
    ]
    return SearchResponse(
        answer=answer,
        citations=citations,
        restricted=[RestrictedItem(**r) for r in restricted],
    )
