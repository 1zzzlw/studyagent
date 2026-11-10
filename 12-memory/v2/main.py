"""在 studyAgent 根目录启动：.venv/Scripts/python.exe 12-memory/v2/main.py。"""

from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from associative_memory import AssociativeMemory
from engines import EbbinghausMemoryEngine
from llm import chat_once, create_model


class PersonState(BaseModel):
    """固定人物状态，只在此处修改；本版不实现自动情绪或行动更新。"""

    name: str
    mood: str
    energy: float = Field(ge=0, le=1)
    activity: str
    attention_focus: str
    environment: str
    current_intent: str


def show_memories(memory: AssociativeMemory, now: datetime):
    memory.refresh(now)
    print("\n" + "─" * 56)
    print(f"记忆概览｜共 {len(memory.id_to_node)} 条，展示最近 8 条（包括历史记录）")
    nodes = sorted(memory.id_to_node.values(), key=lambda node: node.node_count, reverse=True)[:8]
    for node in nodes:
        strength = memory.engine.get_current_strength(node, now) if memory.engine else None
        label = f"{strength:.3f}" if strength is not None else "未启用"
        print(f"{node.node_id} [{node.type}] 深度={node.depth} 回忆={node.recall_count} "
              f"强度={label} 状态={node.status}")
        print(f"  {node.description}")
        if node.type != "chat":
            print(f"  关联：{', '.join(node.filling) or '无'}")
    if not nodes:
        print("尚无记忆。请输入自己的对话，程序不会预置数据。")


def main():
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    storage_path = Path(__file__).resolve().parent / "storage" / "nodes.json"
    state = PersonState(
        name="小忆", mood="有点烦躁", energy=0.35, activity="赶作业，中途打开聊天",
        attention_focus="电脑上的作业", environment="已经读到用户发来的完整消息",
        current_intent="先交作业",
    )

    # 插件接入点：改成 AssociativeMemory() 即可停用衰减强化，记忆管理照常运行。
    memory = AssociativeMemory(engine=EbbinghausMemoryEngine())
    memory.load(storage_path)
    model = create_model()

    print("\n记忆结构实验 v2｜事件 · 想法 · 对话 · 可选衰减强化")
    print("使用真实文字模型；无向量模型、无向量检索、无预置记忆。")
    print(f"人物：{state.name}｜心情：{state.mood}｜当前活动：{state.activity}")
    print(f"插件：{'已启用' if memory.engine else '未启用'}｜已有记忆：{len(memory.id_to_node)} 条")
    print(f"存档：{storage_path}")
    while True:
        print("\n[1] 对话    [2] 时间流逝    [3] 记忆概览    [0] 保存退出")
        try:
            action = input("请选择 > ").strip()
            now = datetime.now(timezone.utc)
            if action == "0":
                memory.save(storage_path)
                print("已保存，再见。")
                return
            if action == "1":
                message = input("你 > ").strip()
                if message:
                    now = datetime.now(timezone.utc)
                    used_count, new_nodes = chat_once(model, state, memory, message, now)
                    print(f"\n本轮采用旧记忆 {used_count} 条，新增："
                          + "、".join(f"{node.node_id}({node.type})" for node in new_nodes))
            elif action == "2":
                days = float(input("让已有记忆经过多少天（支持小数，如 0.5）> "))
                memory.elapse(days, now)
                print(f"已有记忆的时间已前移 {days:g} 天；新对话仍按当前时间形成记忆。")
            elif action == "3":
                show_memories(memory, now)
            else:
                print("请输入 0、1、2 或 3。")
        except (EOFError, KeyboardInterrupt):
            memory.save(storage_path)
            print("\n已保存退出。")
            return
        except Exception as error:
            print(f"\n处理未全部完成：{type(error).__name__}: {error}")
            print("已完成的回答、原话和回忆记录会保留；处理错误不代表人物忘记。")
        # 每次操作保存，包含整理记忆失败前已记录的真实对话。
        memory.save(storage_path)


if __name__ == "__main__":
    main()
