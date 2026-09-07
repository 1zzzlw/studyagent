"""教学模块命令行入口。"""

from __future__ import annotations

import argparse

from .service import EmbeddingLabService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="学习 Markdown → Embedding → Chroma → 查询 的完整链路"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="扫描并预览切块，不联网")
    inspect_parser.add_argument("--limit", type=int, default=5)

    sync_parser = subparsers.add_parser("sync", help="增量同步知识库到 Chroma")
    sync_parser.add_argument(
        "--rebuild",
        action="store_true",
        help="删除并重建本教学集合；模型或切块参数变化后使用",
    )

    subparsers.add_parser(
        "probe",
        help="只测试 Embedding 配置和接口，不读取或修改 Chroma",
    )

    subparsers.add_parser("status", help="查看已持久化的集合，不调用 Embedding")

    query_parser = subparsers.add_parser("query", help="把问题向量化并查询 Top-K")
    query_parser.add_argument("question")
    query_parser.add_argument("--k", type=int, default=3)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = EmbeddingLabService()

    if args.command == "inspect":
        documents, chunks = service.build_chunks()
        print(f"扫描文档：{len(documents)}")
        print(f"生成文本块：{len(chunks)}")
        for index, chunk in enumerate(chunks[:max(0, args.limit)], start=1):
            print(f"\n--- chunk {index} ---")
            print(f"id: {chunk.id[:16]}")
            print(f"source: {chunk.metadata['source']}")
            print(f"heading: {chunk.metadata['heading']}")
            print(chunk.text[:700])
        return 0

    if args.command == "status":
        status = service.store.status()
        print(f"persist_dir: {status['persist_dir']}")
        print(f"collection: {status['collection']}")
        print(f"count: {status['count']}")
        print(f"metadata: {status['metadata']}")
        return 0

    if args.command == "probe":
        embeddings = service.create_embeddings()
        vector = embeddings.embed_query("studyAgent 腾讯向量模型连接测试")
        print(f"model: {service.settings.embedding_model}")
        print(f"base_url: {service.settings.embedding_base_url}")
        print(f"dimension: {len(vector)}")
        print("Embedding 连接测试成功；本命令没有读取或修改 Chroma。")
        return 0

    if args.command == "sync":
        documents, chunks = service.build_chunks()
        print(f"扫描到 {len(documents)} 份文档，切成 {len(chunks)} 个文本块")
        embeddings = service.create_embeddings()
        stats = service.store.sync(
            chunks,
            embeddings,
            rebuild=args.rebuild,
            batch_size=service.settings.embedding_batch_size,
            progress=print,
        )
        print(
            f"同步完成：total={stats.total}, added={stats.added}, deleted={stats.deleted}"
        )
        return 0

    if args.command == "query":
        embeddings = service.create_embeddings()
        hits = service.store.query(args.question, embeddings, k=args.k)
        if not hits:
            print("没有召回结果")
            return 0
        for rank, hit in enumerate(hits, start=1):
            distance = f"{hit.distance:.4f}" if hit.distance is not None else "unknown"
            print(f"\n--- Top {rank} | distance={distance} ---")
            print(f"source: {hit.metadata.get('source', 'unknown')}")
            print(f"heading: {hit.metadata.get('heading', 'unknown')}")
            print(f"chunk_id: {hit.id}")
            print(hit.text)
        return 0

    raise AssertionError(f"未处理的命令：{args.command}")
