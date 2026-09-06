"""通过 Agent Server API 调用本地 Graph。先运行 langgraph dev。"""

import asyncio

from langgraph_sdk import get_client


async def main() -> None:
    client = get_client(url="http://127.0.0.1:2024")
    result = await client.runs.wait(
        None,
        "study_agent",
        input={
            "messages": [
                {"role": "user", "content": "只回复：Agent Server API 正常"}
            ]
        },
    )
    print(result["messages"][-1]["content"])


if __name__ == "__main__":
    asyncio.run(main())
