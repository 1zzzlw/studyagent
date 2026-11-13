"""v1 自己的启动、导入与菜单。首次只导入原始记忆，不调用文字模型。"""
import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from .engine import EbbinghausMemoryEngine
from .llm import ModelGateway, create_embeddings, embedding_signature, load_environment
from .runtime import Runtime
from .seed import atomic_json, file_hash, import_baseline, load_seeds
from .store import ChromaStore


def run(version="v1"):
    parser = argparse.ArgumentParser(description="GA 检索与反思对照实验")
    parser.add_argument("--import-only", action="store_true", help="只导入原始记忆，导入完成即退出")
    parser.add_argument("--question", help="独立只读提问，不写记忆、不强化、不使用短期历史")
    args = parser.parse_args()

    load_environment()
    root = Path(__file__).resolve().parent.parent
    data_file = root / "storge" / "memories.json"
    run_dir = root / "storge" / version

    seeds = load_seeds(data_file)  # 先完整校验，再调用向量接口。
    # 固定实验参考时刻，三个版本启动先后不会改变原始 300 条的年龄。
    now = datetime.fromisoformat(os.getenv("EXPERIMENT_NOW", "2026-11-10T12:00:00+08:00"))
    if now.tzinfo is None:
        raise ValueError("EXPERIMENT_NOW 必须带时区")

    now = now.astimezone(timezone.utc)
    store = ChromaStore(root / "storge" / "chromadb" / version, version,
                        create_embeddings(), embedding_signature())

    # 记忆衰减强化引擎
    engine = EbbinghausMemoryEngine()
    imported = import_baseline(store, seeds, now, engine, run_dir, file_hash(data_file))
    runtime = Runtime(store, ModelGateway(), now, run_dir, version)
    print(f"\n{version}｜GA 事件/想法/原话 · 多因素检索 · 反思 · 衰减强化")
    print(f"原始记忆本次新增 {imported} 条；库中共 {len(store.nodes)} 条；首次仅导入原始数据；正常对话后自动运行本版本的反思/关联流程。")
    print(f"Chroma：{root / 'storge' / 'chromadb' / version}")
    print(f"文字模型：{os.getenv('LLM_MODEL', '未配置')}｜向量模型：{os.getenv('EMBEDDING_MODEL', '未配置')}")
    print(f"实验现在：{now.isoformat()}｜累计手动流逝 {runtime.elapsed_days:g} 天")
    if args.import_only:
        return
    if args.question:
        runtime.chat(args.question, read_only=True, report=print)
        return
    while True:
        print("\n[1] 连续对话  [2] 时间流逝  [3] 统计")
        print("[4] 独立只读提问  [5] 恢复300条原始基线  [0] 退出")
        try:
            action = input("请选择 > ").strip()
            if action == "0":
                return
            if action in ("1", "4"):
                question = input("你 > ").strip()
                if question:
                    runtime.chat(question, read_only=action == "4", report=print)
            elif action == "2":
                days = float(input("已有记忆经过多少天（可小数）> "))
                runtime.elapse(days, report=print)
                print("已前移该版本现有记忆时间并清空短期原话。")
            elif action == "3":
                nodes = list(store.nodes.values())
                print(f"总数 {len(nodes)}｜事件 {sum(n.type == 'event' for n in nodes)}｜"
                      f"想法 {sum(n.type == 'thought' for n in nodes)}｜原话 {sum(n.type == 'chat' for n in nodes)}")
                print(f"已参与反思的来源 {sum(n.reflected for n in nodes)}")
                print(f"本次文字模型请求 {runtime.model_calls} 次；结果日志：{run_dir / 'results.jsonl'}")
            elif action == "5":
                if input("仅重置当前版本；输入 RESET 确认 > ").strip() == "RESET":
                    store.reset()
                    import_baseline(store, seeds, now, engine, run_dir, file_hash(data_file))
                    runtime.history.clear()
                    runtime.elapsed_days = 0
                    atomic_json(runtime.elapsed_path, {"elapsed_days": 0})
                    runtime.trace({"stage": "baseline_restored"})
                    print("已恢复原始300条；结果日志保留，后续正常对话将自动重新形成反思与关联。")
            else:
                print("请输入菜单中的数字。")
        except (EOFError, KeyboardInterrupt):
            print("\n正在退出。当前操作已写入的内容会保留。")
            return
        except Exception as error:
            store.reload()
            print(f"\n本次操作未全部完成：{type(error).__name__}: {error}")
            print("已完成的回答与数据库写入保留；技术错误不代表人物遗忘。")
