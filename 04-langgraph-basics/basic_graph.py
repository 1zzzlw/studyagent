"""第四章：不调用 LLM 的最小 LangGraph，用于理解 State、Node、Edge 和分支。"""

from typing import Annotated, Literal
# 是 Python 内置标准库，封装大量底层运算符，把 `+ - * / > < and or []` 这些运算符变成**可调用函数对象**，常用于排序、lambda 替代、LangChain/LangGraph 节点合并
import operator

from typing_extensions import TypedDict
from langgraph.graph import END, START, StateGraph


class NumberState(TypedDict):
    number: int
    result: int
    steps: Annotated[list[str], operator.add]


def validate_input(state: NumberState) -> dict:
    number = state["number"]
    if not isinstance(number, int):
        raise TypeError("number 必须是整数")
    return {"steps": [f"收到数字 {number}"]}


def route_number(state: NumberState) -> Literal["double", "triple"]:
    return "double" if state["number"] % 2 == 0 else "triple"


def double_number(state: NumberState) -> dict:
    return {
        "result": state["number"] * 2,
        "steps": ["偶数乘以 2"],
    }


def triple_number(state: NumberState) -> dict:
    return {
        "result": state["number"] * 3,
        "steps": ["奇数乘以 3"],
    }


builder = StateGraph(NumberState)
builder.add_node("validate", validate_input)
builder.add_node("double", double_number)
builder.add_node("triple", triple_number)
builder.add_edge(START, "validate")
builder.add_conditional_edges("validate", route_number)
builder.add_edge("double", END)
builder.add_edge("triple", END)

graph = builder.compile()


if __name__ == "__main__":
    print(graph.invoke({"number": 4, "steps": []}))
    print(graph.invoke({"number": 5, "steps": []}))
