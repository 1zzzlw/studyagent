"""第五章：可由 Agent Server 和 LangSmith Studio 加载的最小聊天 Graph。"""

from dotenv import find_dotenv, load_dotenv

# Agent Server 导入本模块时先加载配置，避免 LangSmith/LangChain 缓存空环境变量。
env_path = find_dotenv(".env", usecwd=True)
if env_path:
    load_dotenv(env_path, override=True)

import os

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph


model = ChatOpenAI(
    model=os.environ["LLM_MODEL"],
    base_url=os.environ["LLM_BASE_URL"],
    api_key=os.environ["LLM_API_KEY"],
    temperature=0,
)


def call_model(state: MessagesState) -> dict:
    """读取历史消息，追加一条 AI 回复。"""
    response = model.invoke(state["messages"])
    return {"messages": [response]}


builder = StateGraph(MessagesState)
builder.add_node("call_model", call_model)
builder.add_edge(START, "call_model")
builder.add_edge("call_model", END)

# Agent Server 自己管理 Thread 和持久化，这里不传 MemorySaver。
graph = builder.compile()
