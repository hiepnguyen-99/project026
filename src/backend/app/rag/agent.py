from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..models.user import User
from .prompts import SYSTEM_PROMPT
from .tools import build_tools


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


async def run_agent(db: AsyncSession, user: User, query: str) -> tuple[str, list[dict]]:
    """Chạy LangGraph agent (tool-use). Trả (answer, citations).

    Quyền vẫn được gác ở tầng tool/SQL — agent không tự cấp quyền.
    """
    citations_sink: list[dict] = []
    tools = build_tools(db, user, citations_sink)
    llm = ChatOpenAI(model=settings.LLM_MODEL, temperature=0, api_key=settings.OPENAI_API_KEY)
    llm_with_tools = llm.bind_tools(tools)

    async def agent_node(state: AgentState) -> dict:
        response = await llm_with_tools.ainvoke(
            [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]]
        )
        return {"messages": [response]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    compiled = graph.compile()

    result = await compiled.ainvoke({"messages": [HumanMessage(content=query)]})
    last = result["messages"][-1].content
    answer = last if isinstance(last, str) else str(last)

    # Khử trùng citation theo (title, page_ref).
    seen: set[tuple] = set()
    citations: list[dict] = []
    for c in citations_sink:
        key = (c.get("title"), c.get("page_ref"))
        if key not in seen:
            seen.add(key)
            citations.append(c)
    return answer, citations
