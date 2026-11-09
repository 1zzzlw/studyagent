#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读取同目录的 05.memories.json，向量化后写入 05.chroma.py 使用的本地集合。

在 studyAgent 根目录运行：
    .venv/Scripts/python.exe 12-memory/05.import_memories.py

JSON 已经是整理好的记忆，不再调用语言模型提取，只调用真实向量模型。
固定 ID 用于重复导入时跳过旧记录，不覆盖已经发生的回忆强化和时间变化。
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import chromadb
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from pydantic import BaseModel, Field


SCRIPT_DIR = Path(__file__).resolve().parent
DATA_FILE = SCRIPT_DIR / "05.memories.json"
# 与 05.chroma.py 保持一致，导入后可直接启动 05 对话。
CHROMA_PATH = SCRIPT_DIR / "storge" / "chromadb"
COLLECTION_NAME = "hybrid_memory_05"
BATCH_SIZE = 10  # 每批只请求 10 条，兼容限制批量大小的向量接口。


class MemorySeed(BaseModel):
    """JSON 中的一条模拟记忆；相对时间会在首次导入时转成 UTC 时间。"""

    memory_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    created_days_ago: float = Field(ge=0, allow_inf_nan=False)
    initial_strength: float = Field(ge=0, le=1)
    strength_after_recall: float = Field(ge=0, le=1)
    stability_days: float = Field(gt=0, allow_inf_nan=False)
    recall_count: int = Field(ge=0)
    # null 表示从未成功回忆；7 表示上次成功回忆发生在 7 天前。
    last_recalled_days_ago: float | None = Field(default=None, ge=0)
    # 普通记录会重新计算状态；superseded 旧认识始终保持已被修正。
    status: Literal["active", "fading", "forgotten", "superseded"] = "active"
    supersedes_id: str | None = None


def load_memories():
    """先校验整个文件，再开始调用模型或写数据库，避免坏数据导入到一半。"""
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    seeds = [MemorySeed.model_validate(row) for row in payload["memories"]]
    ids = {seed.memory_id for seed in seeds}
    if not seeds or len(ids) != len(seeds):
        raise ValueError("记忆列表不能为空，memory_id 不能重复")
    for seed in seeds:
        recalled = seed.last_recalled_days_ago
        if (seed.recall_count == 0) != (recalled is None):
            raise ValueError(f"{seed.memory_id} 的回忆次数与回忆时间不一致")
        if recalled is not None and (
            not math.isfinite(recalled) or recalled > seed.created_days_ago
        ):
            raise ValueError(f"{seed.memory_id} 的回忆时间早于形成时间或无效")
        if seed.supersedes_id is not None and seed.supersedes_id not in ids:
            raise ValueError(f"{seed.memory_id} 引用的被纠正记忆不在 JSON 中")
    return seeds


def to_metadata(seed, now):
    """转换成 05 的 MemoryItem 可以直接读回的字段；正文单独放 documents。"""
    created_at = now - timedelta(days=seed.created_days_ago)
    recalled_at = (
        now - timedelta(days=seed.last_recalled_days_ago)
        if seed.last_recalled_days_ago is not None else None
    )
    days = (now - (recalled_at or created_at)).total_seconds() / 86400
    strength = seed.strength_after_recall * math.exp(-days / seed.stability_days)
    status = (
        "superseded" if seed.status == "superseded"
        else "active" if strength > 0.6
        else "fading" if strength > 0.2
        else "forgotten"
    )
    metadata = {
        "source_observation_id": f"obs_{seed.memory_id}",
        "created_at": created_at.isoformat(),
        "initial_strength": seed.initial_strength,
        "strength_after_recall": seed.strength_after_recall,
        "stability_days": seed.stability_days,
        "recall_count": seed.recall_count,
        "status": status,
    }
    # Chroma 中不保存 None；05 的数据类会把缺失的可选字段恢复为 None。
    if recalled_at is not None:
        metadata["last_recalled_at"] = recalled_at.isoformat()
    if seed.supersedes_id is not None:
        metadata["supersedes_id"] = seed.supersedes_id
    return metadata


def main():
    load_dotenv(SCRIPT_DIR.parent / ".env")
    seeds = load_memories()
    required = ["EMBEDDING_MODEL", "EMBEDDING_API_KEY"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise ValueError("项目根目录 .env 缺少：" + "、".join(missing))

    print("\n" + "=" * 72)
    print("  300 条模拟记忆 · 本地 Chroma 导入")
    print("=" * 72)
    print(f"  数据文件：{DATA_FILE}")
    print(f"  数据目录：{CHROMA_PATH}")
    print(f"  集合名称：{COLLECTION_NAME}")
    print(f"  读取记忆：{len(seeds)} 条")

    embeddings = OpenAIEmbeddings(
        model=os.environ["EMBEDDING_MODEL"],
        base_url=os.getenv("EMBEDDING_BASE_URL"),
        api_key=os.environ["EMBEDDING_API_KEY"],
        check_embedding_ctx_length=False, request_timeout=30, max_retries=0,
    )
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME, embedding_function=None,
        configuration={"hnsw": {"space": "cosine"}},
        metadata={"embedding_model": embeddings.model},
    )
    stored_model = (collection.metadata or {}).get("embedding_model")
    if stored_model != embeddings.model:
        raise ValueError(
            f"集合的向量模型是 {stored_model!r}，当前配置是 {embeddings.model!r}。"
            "请与 05 使用相同的模型和集合。"
        )

    # 这里只取 ID，不读取全库向量；已有记录不向量化、不覆盖、不重置时间。
    existing_ids = set(collection.get(
        ids=[seed.memory_id for seed in seeds], include=[],
    )["ids"])
    pending = [seed for seed in seeds if seed.memory_id not in existing_ids]
    print(f"  跳过已有：{len(existing_ids)} 条    待导入：{len(pending)} 条")

    # 所有新增记录使用同一个导入基准时间，避免批次速度影响年龄对照。
    now = datetime.now(timezone.utc)
    records = [(seed, to_metadata(seed, now)) for seed in pending]
    for offset in range(0, len(records), BATCH_SIZE):
        batch = records[offset:offset + BATCH_SIZE]
        vectors = embeddings.embed_documents([seed.content for seed, _ in batch])
        if len(vectors) != len(batch):
            raise ValueError("向量接口返回的数量与本批记忆数量不一致")
        # 同时传正文和已生成的向量，Chroma 不会另外调用默认嵌入模型。
        collection.add(
            ids=[seed.memory_id for seed, _ in batch],
            documents=[seed.content for seed, _ in batch],
            embeddings=vectors,
            metadatas=[metadata for _, metadata in batch],
        )
        finished = offset + len(batch)
        print(f"  [{finished:3d}/{len(records)}] 本批 {len(batch)} 条已保存")

    print("\n  导入完成。")
    print(f"  新增 {len(pending)} 条，跳过 {len(existing_ids)} 条，集合共 {collection.count()} 条。")
    print("  重复运行会保留已有记录的强化和时间变化，不会恢复为初始测试状态。")
    print("  接下来启动 05.chroma.py，按 05.测试提示词.md 中的消息进行对话。\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  已停止导入。已保存的批次保留，下次运行会跳过已有 ID。")
    except Exception as error:
        print(f"\n  [导入未完成] {type(error).__name__}: {error}")
        print("  已保存的批次保留；修正配置或文件后重新运行，会跳过已有 ID。")
        raise SystemExit(1)
