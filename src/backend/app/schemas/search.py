from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str


class Citation(BaseModel):
    file: str
    page: str | None = None
    uri: str


class RestrictedItem(BaseModel):
    file: str
    owner: str
    visibility: str
    action: str


class SearchResponse(BaseModel):
    answer: str
    citations: list[Citation]
    restricted: list[RestrictedItem]
