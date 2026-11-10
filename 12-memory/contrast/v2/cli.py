"""纯 A-Mem 独立终端入口，与网页一样从空笔记开始。"""
import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from .llm import ModelGateway, create_embeddings, embedding_signature, load_environment
from .runtime import Runtime
from .store import ChromaStore


def run(version="v2"):
    parser = argparse.ArgumentParser(description="纯 A-Mem 记忆笔记实验")
    parser.add_argument("--question", help="只读提问，不保存新笔记或访问统计")
    args = parser.parse_args()
    load_environment()
    root = Path(__file__).resolve().parent.parent
    now = datetime.fromisoformat(os.getenv("EXPERIMENT_NOW", "2026-11-10T12:00:00+08:00"))
    if now.tzinfo is None:
        raise ValueError("EXPERIMENT_NOW 必须带时区")
    now = now.astimezone(timezone.utc)
    path = root / "storge" / "chromadb" / version
    store = ChromaStore(path, version, create_embeddings(), embedding_signature())
    runtime = Runtime(store, ModelGateway(), now, root / "storge" / version, version)
    print(f"\n{version}｜纯 A-Mem：笔记 · 语义分析 · 关联演化 · 语义检索")
    print(f"已有笔记 {len(store.nodes)} 条；不自动导入300条，也不加载衰减强化引擎。\nChroma：{path}")
    if args.question:
        runtime.chat(args.question, read_only=True)
        return
    while True:
        print("\n[1] 对话  [2] 时间流逝  [3] 统计  [4] 只读提问  [5] 清空笔记  [0] 退出")
        try:
            action = input("请选择 > ").strip()
            if action == "0":
                return
            if action in ("1", "4"):
                question = input("你 > ").strip()
                if question:
                    runtime.chat(question, read_only=action == "4")
            elif action == "2":
                runtime.elapse(float(input("已有笔记经过多少天 > ")))
            elif action == "3":
                print(f"笔记 {len(store.nodes)} 条｜有出链的笔记 {sum(bool(note.links) for note in store.nodes.values())} 条")
                print(f"文字模型调用 {runtime.model_calls} 次｜日志：{runtime.run_dir / 'results.jsonl'}")
            elif action == "5":
                if input("输入 RESET 清空本版笔记 > ").strip() == "RESET":
                    store.reset()
                    runtime.elapsed_days = 0
                    runtime.save_elapsed()
                    runtime.trace({"stage": "notes_cleared"})
                    print("笔记已清空，历史结果日志保留。")
            else:
                print("请输入菜单中的数字。")
        except (EOFError, KeyboardInterrupt):
            print("\n正在退出。已写入的内容会保留。")
            return
        except Exception as error:
            store.reload()
            print(f"本次操作未全部完成：{type(error).__name__}: {error}")
            print("已保存的回答与笔记保留，未完成部分可从处理记录查看。")
