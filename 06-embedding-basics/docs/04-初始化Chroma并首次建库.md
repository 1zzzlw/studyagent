# 第 4 章：初始化 Chroma 并首次建库

## 本章目标

亲手完成第一次持久化建库，并知道每一步是否调用外部接口。

## 1. 建库前检查

确认 `studyAgent/.env` 包含：

```dotenv
LLM_BASE_URL=https://你的服务地址/v1
LLM_API_KEY=你的密钥
EMBEDDING_MODEL=你的向量模型名
```

代码不会打印或写入 API Key。`index_signature` 只包含模型名、接口地址和切块参数。

## 2. 执行首次同步

在项目根目录运行：

```powershell
uv run python 06-embedding-basics\run.py sync
```

这条命令会执行：

```text
load_documents()
  → MarkdownChunker.split_documents()
  → Chroma PersistentClient
  → get_or_create_collection()
  → 找出尚未存在的 chunk ID
  → 每 10 块调用一次 embed_documents()
  → collection.upsert()
```

终端会逐批显示：

```text
Embedding 第 1/N 批：10 个文本块
```

这意味着程序正在进行真实接口调用。若文档很多，首次同步需要等待，也可能产生供应商费用。

## 3. `PersistentClient` 与 collection

Chroma 有两层概念：

- `PersistentClient(path=...)`：指定数据库文件存放目录；
- collection：同一数据库里的逻辑集合，类似一张专门用于向量检索的表。

本教程使用：

```text
目录：06-embedding-basics/storage/chroma
集合：studyagent_wild_knowledge_v1
```

它不会读取或修改 WildAgent 的 `wild-server/storage/chroma`。

## 4. 为什么使用 `upsert`

`add` 遇到重复 ID 容易失败；`upsert` 表示：

- ID 不存在则新增；
- ID 已存在则更新。

不过本教程不会无脑把全部块重新 `upsert`。它先比较现有 ID，只对新增块调用 Embedding。这样第二次同步才能真正节省时间和费用。

## 5. 建库后检查

```powershell
uv run python 06-embedding-basics\run.py status
```

应该看到：

- `persist_dir`；
- 集合名；
- `count`；
- `index_signature`；
- 距离类型 `cosine`。

`status` 不调用 Embedding 模型，只读取本地数据库。

## 6. 何时使用 `--rebuild`

以下情况需要重建：

- 更换 Embedding 模型；
- 更换接口地址且它代表另一套模型服务；
- 修改 `chunk_size` 或 `chunk_overlap`；
- 明确想从零验证首次建库。

执行：

```powershell
uv run python 06-embedding-basics\run.py sync --rebuild
```

这是有范围的删除操作：只删除本教学模块的指定 collection，再重新创建；不会清空整个 Chroma 目录。

