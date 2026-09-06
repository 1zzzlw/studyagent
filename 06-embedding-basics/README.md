# 06 · Embedding 与 Chroma 持久化入门

这一模块不是再做一遍普通 RAG，而是专门拆开 WildAgent 中最容易混在一起的三件事：

1. Embedding 模型怎样把文本变成向量；
2. 知识文档怎样切块并写入 Chroma；
3. 服务重启后怎样复用索引，以及用户提问时怎样完成召回。

## 建议学习顺序

| 章节 | 你要解决的问题 | 是否调用真实 Embedding |
|---|---|---|
| [第 1 章：先看完整链路](docs/01-先看完整链路.md) | 数据到底经过了哪些步骤？ | 否 |
| [第 2 章：认识 Embedding](docs/02-认识Embedding模型.md) | 向量是什么，文档向量和问题向量为何必须同源？ | 是，只有主动运行示例时 |
| [第 3 章：扫描文档与切块](docs/03-扫描文档与切块.md) | 为什么不能把整个 Markdown 直接入库？ | 否 |
| [第 4 章：初始化 Chroma 并首次建库](docs/04-初始化Chroma并首次建库.md) | 第一次建库实际做了什么？ | 是 |
| [第 5 章：持久化、启动与增量同步](docs/05-持久化启动与增量同步.md) | 为什么重启不必重复向量化？ | 仅有新块时 |
| [第 6 章：查询与召回](docs/06-查询与召回.md) | 用户问题如何变成 Top-K 文本块？ | 是，每次查询一次 |
| [第 7 章：回到 WildAgent 看生产链路](docs/07-WildAgent生产链路对照.md) | 教学代码和生产代码如何一一对应？ | 否 |
| [第 8 章：排错、验证与练习](docs/08-排错验证与练习.md) | 结果不对时从哪里查？ | 按练习而定 |
| [第 9 章：切换 Embedding 模型实战](docs/09-切换Embedding模型实战.md) | 怎样迁移、验证、切换和回滚？ | 是，迁移时全量调用 |

先按顺序读，不建议直接跳到 WildAgent 的 `RAGSpecLoader`。生产代码还包含后台线程、重试、门禁、安全过滤、追踪和降级策略，这些会遮住最基本的数据流。

## 最小运行路径

在项目根目录执行：

```powershell
cd E:\AgentProject\studyAgent

# 1. 只扫描和切块，不联网、不写数据库
uv run python 06-embedding-basics\run.py inspect --limit 3

# 2. 首次建库。会调用真实 Embedding 接口
uv run python 06-embedding-basics\run.py sync

# 3. 查看持久化索引，不调用 Embedding
uv run python 06-embedding-basics\run.py status

# 4. 查询。只对问题调用一次 Embedding
uv run python 06-embedding-basics\run.py query "玻璃幕墙应该怎样挂接到墙体？" --k 3

# 5. 再次同步。文档未变化时应显示 added=0
uv run python 06-embedding-basics\run.py sync
```

`.env` 复用项目已有配置：

```dotenv
LLM_BASE_URL=https://你的服务地址/v1
LLM_API_KEY=你的密钥
EMBEDDING_MODEL=你的向量模型名
```

不要把 API Key 写进 Notebook、代码、Chroma metadata 或 Git。

## 代码地图

```text
06-embedding-basics/
├── embedding_lab/
│   ├── config.py       # 路径、环境变量、切块参数
│   ├── documents.py    # 递归扫描 Markdown
│   ├── chunking.py     # 标题切块 + 长文本兜底切分
│   ├── embeddings.py   # OpenAI-compatible Embedding 请求
│   ├── vector_store.py # Chroma 创建、同步、查询
│   └── service.py      # 串起“文档 → 块 → 向量库 → 召回”
├── docs/               # 分章节教程
├── storage/
│   ├── knowledge_base/ # 你复制的 WildAgent 知识文档
│   └── chroma/         # 本地生成，不提交 Git
├── 01.basic.ipynb      # 3 条文本的最小实验
└── run.py              # 所有命令的统一入口
```

## 学完后应该能回答

- Chroma 保存的不只是向量，还保存什么？
- 为什么查询也必须调用 Embedding 模型？
- 为什么 `sync` 第二次运行通常不再请求所有文档的向量？
- 修改 `EMBEDDING_MODEL` 或切块参数后，为何旧索引不能直接复用？
- 检索错误和大模型回答错误应该怎样分开定位？

这些问题都能独立讲清楚，才算真正掌握本模块。
