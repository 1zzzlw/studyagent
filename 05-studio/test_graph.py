"""不启动 Agent Server，直接验证 Graph 能否调用。会产生一次模型费用。"""

from app import graph


def main() -> None:
    result = graph.invoke({
        "messages": [{"role": "user", "content": "只回复：Studio Graph 正常"}]
    })
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
