"""读取同一份 300 条 JSON；每个版本独立缓存向量、独立导入。"""
import hashlib
import json
import math
from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .models import ConceptNode


class MemorySeed(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    memory_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    created_days_ago: float = Field(ge=0)
    initial_strength: float = Field(ge=0, le=1)
    strength_after_recall: float = Field(ge=0, le=1)
    stability_days: float = Field(gt=0)
    recall_count: int = Field(ge=0)
    last_recalled_days_ago: float | None = Field(default=None, ge=0)
    status: str = "active"
    supersedes_id: str | None = None


def load_seeds(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    seeds = [MemorySeed.model_validate(item) for item in data["memories"]]
    ids = {seed.memory_id for seed in seeds}
    if len(seeds) != 300 or len(ids) != 300:
        raise ValueError("对照数据必须包含 300 条不同 ID 的记忆")
    for seed in seeds:
        age = seed.last_recalled_days_ago
        if (seed.recall_count == 0) != (age is None):
            raise ValueError(f"{seed.memory_id} 的回忆次数和回忆时间不一致")
        if age is not None and age > seed.created_days_ago:
            raise ValueError(f"{seed.memory_id} 的回忆早于形成时间")
        if seed.supersedes_id and (seed.supersedes_id not in ids or seed.supersedes_id == seed.memory_id):
            raise ValueError("纠正关系引用了无效 ID")
    return seeds


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def seed_nodes(seeds, now, engine):
    nodes = []
    for number, seed in enumerate(seeds, 1):
        created = now - timedelta(days=seed.created_days_ago)
        accessed = now - timedelta(days=seed.last_recalled_days_ago) if seed.last_recalled_days_ago is not None else created
        node = ConceptNode(
            node_id=seed.memory_id, node_count=number, type_count=number,
            description=seed.content, created=created, last_accessed=accessed,
            origin="seed", source_observation_id=f"seed_{seed.memory_id}",
            # 数据没有独立重要性评分；三版使用相同代理值，不能当成真实标注。
            poignancy=max(1, 10 * seed.initial_strength),
            initial_strength=seed.initial_strength, strength_after_recall=seed.strength_after_recall,
            stability_days=seed.stability_days, recall_count=seed.recall_count,
            status="superseded" if seed.status == "superseded" else "active",
            supersedes_id=seed.supersedes_id,
        )
        engine.step(node, now)  # 已有历史不能重新 register，否则会抹掉强化记录。
        nodes.append(node)
    by_id = {node.node_id: node for node in nodes}
    for node in nodes:
        if node.supersedes_id:
            by_id[node.supersedes_id].status = "superseded"
    return nodes


def import_baseline(store, seeds, now, engine, cache_dir, source_hash, report=print):
    cache_dir = Path(cache_dir)
    manifest_path = cache_dir / "experiment.json"
    manifest = {"source_sha256": source_hash, "embedding_signature": store.signature,
                "reference_time": now.isoformat()}
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("该版本已有实验的数据、向量配置或参考时间不同；请使用新的实验目录")
    else:
        if store.nodes:
            raise ValueError("数据库存在记录但缺少实验清单，拒绝混入新的基线")
        atomic_json(manifest_path, manifest)
    cache_path = cache_dir / "seed_vectors.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    existing = store.nodes
    nodes = [node for node in seed_nodes(seeds, now, engine) if node.node_id not in existing]
    for start in range(0, len(nodes), 10):
        batch = nodes[start:start + 10]
        keys = [hashlib.sha256(node.description.encode()).hexdigest() for node in batch]
        missing = {key: node.description for key, node in zip(keys, batch) if key not in cache}
        if missing:
            vectors = store.embeddings.embed_documents(list(missing.values()))
            for key, vector in zip(missing, vectors, strict=True):
                if not vector or not all(math.isfinite(value) for value in vector):
                    raise ValueError("向量模型返回空向量或非法数值")
                cache[key] = vector
            atomic_json(cache_path, cache)
        store.add(batch, [cache[key] for key in keys])
        report(f"  导入原始记忆 {min(start + 10, len(nodes))}/{len(nodes)}")
    return len(nodes)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
