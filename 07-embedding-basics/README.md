# 07 · Embedding 与 Chroma 持久化入门

这一模块不是再做一遍普通 RAG，而是专门拆开 WildAgent 中最容易混在一起的三件事：

1. Embedding 模型怎样把文本变成向量；
2. 知识文档怎样切块并写入 Chroma；
3. 服务重启后怎样复用索引，以及用户提问时怎样完成召回。

## 建议学习顺序

| 章节 | 你要解决的问题 | 是否调用真实 Embedding |
|---|---|---|
| [第 1 章：先看完整链路](docs/01-先看完整链路.md) | 数据到底经过了哪些步骤？ | 否 |
| [第 2 章：认识 Embedding](docs/02-认识Embedding模型.md) | 向量是什么，文档与问题向量为何必须同源，Protocol 为什么不需要显式继承？ | 是，只有主动运行真实接口示例时 |
| [第 3 章：扫描文档与切块](docs/03-扫描文档与切块.md) | 为什么不能把整个 Markdown 直接入库？ | 否 |
| [第 4 章：初始化 Chroma 并首次建库](docs/04-初始化Chroma并首次建库.md) | 第一次建库实际做了什么？ | 是 |
| [第 5 章：持久化、启动与增量同步](docs/05-持久化启动与增量同步.md) | 为什么重启不必重复向量化？ | 仅有新块时 |
| [第 6 章：查询与召回](docs/06-查询与召回.md) | 用户问题如何变成 Top-K 文本块？ | 是，每次查询一次 |
| [第 7 章：回到 WildAgent 看生产链路](docs/07-WildAgent生产链路对照.md) | 教学代码和生产代码如何一一对应？ | 否 |
| [第 8 章：排错、验证与练习](docs/08-排错验证与练习.md) | 结果不对时从哪里查？ | 按练习而定 |
| [第 9 章：切换 Embedding 模型实战](docs/09-切换Embedding模型实战.md) | 怎样迁移、验证、切换和回滚？ | 是，迁移时全量调用 |
| [第 10 章：腾讯向量服务与配置解耦](docs/10-腾讯向量服务与配置解耦.md) | 怎样让聊天模型与腾讯向量模型使用不同地址和密钥？ | 是，仅探针 Cell |

先按顺序读，不建议直接跳到 WildAgent 的 `RAGSpecLoader`。生产代码还包含后台线程、重试、门禁、安全过滤、追踪和降级策略，这些会遮住最基本的数据流。

## 本模块的动手方式

这一版采用“文档给详细代码，你亲手写进 Notebook”的方式：

- 文档会给出足够完整的练习代码和预期结果；
- 你在自己维护的 `01.basic.ipynb` 中按 Cell 逐段手写；
- 仓库不会替你填充 Notebook，也不会让你另建 `.py` 测试文件；
- 每个代码块对应一个独立 Cell，不要一次复制整章；
- 每完成一段，先解释输入和输出，再继续下一段；
- 已有 `embedding_lab/` 是参考实现，不要求你一开始就全部读懂。

建议在 `01.basic.ipynb` 中为每章建立一个一级 Markdown 标题：

| 章节 | Notebook 区域 | 是否联网 | 主要观察 |
|---|---|---|---|
| 01 | `# 第 1 章：完整链路` | 否 | 文档、Chunk 和 metadata 怎样流动 |
| 02 | `# 第 2 章：真实 Embedding` | 是 | 批量向量、问题向量、维度和相似度 |
| 03 | `# 第 3 章：扫描与切块` | 否 | 扫描、frontmatter、标题路径和稳定 ID |
| 04 | `# 第 4 章：首次建库` | 否 | 临时 Chroma 的首次写入 |
| 05 | `# 第 5 章：增量同步` | 否 | 新增、未变化和失效块怎样处理 |
| 06 | `# 第 6 章：查询与召回` | 否 | 问题向量、metadata 过滤和 Top-K |
| 07 | `# 第 7 章：生产链路对照` | 否 | 只读定位 WildAgent 的真实入口 |
| 08 | `# 第 8 章：排错实验` | 否 | 主动触发并分层识别错误 |
| 09 | `# 第 9 章：模型迁移` | 否 | 用双集合演练切换和回滚 |
| 10 | `# 第 10 章：腾讯向量服务` | 是 | 双 Client、配置门禁和连接探针 |

Notebook 最前面先创建一个公共初始化 Cell。后面十章都复用这里的 `PROJECT_ROOT` 和 `MODULE_ROOT`：

```python
from pathlib import Path
import sys

current_dir = Path.cwd().resolve()
if current_dir.name == "07-embedding-basics":
    MODULE_ROOT = current_dir
    PROJECT_ROOT = current_dir.parent
else:
    PROJECT_ROOT = current_dir
    MODULE_ROOT = PROJECT_ROOT / "07-embedding-basics"

assert MODULE_ROOT.exists(), f"没有找到 07 模块：{MODULE_ROOT}"
sys.path.insert(0, str(MODULE_ROOT))

print("Notebook 工作目录：", current_dir)
print("studyAgent 根目录：", PROJECT_ROOT)
print("07 模块目录：", MODULE_ROOT)
```

如果 Kernel 重启，先重新运行这个公共初始化 Cell，再从当前章节的第一个 Cell 依次向下运行。Notebook 中不使用 `__file__`。

## 版本与资料依据

- `chromadb>=1.5.9`：本地持久化、Collection、upsert 和向量查询；
- `openai>=3.8.0`：调用 OpenAI-compatible `/embeddings`；
- `numpy>=2.5.2`：在第 2 章手动计算 cosine similarity；
- Chroma 官方资料：[Python Client](https://docs.trychroma.com/reference/python/client)、[Collection](https://docs.trychroma.com/reference/python/collection)、[Query and Get](https://docs.trychroma.com/docs/querying-collections/query-and-get)；
- WildAgent 只作为第 7、9 章的只读生产链路对照，不在本模块练习中改动。

## 参考实现的命令行运行路径（可选）

下面用于快速观察仓库已有的参考实现，不是本模块的主要练习方式。你的主要练习仍然是在 `01.basic.ipynb` 中按各章 Cell 亲手输入和运行。

如需对照参考实现，可在项目根目录执行：

```powershell
cd E:\AgentProject\studyAgent

# 1. 只扫描和切块，不联网、不写数据库
uv run python 07-embedding-basics\run.py inspect --limit 3

# 2. 先测试模型与接口。不会读取或修改 Chroma
uv run python 07-embedding-basics\run.py probe

# 3. 探针成功后再首次建库。会调用真实 Embedding 接口
uv run python 07-embedding-basics\run.py sync

# 4. 查看持久化索引，不调用 Embedding
uv run python 07-embedding-basics\run.py status

# 5. 查询。只对问题调用一次 Embedding
uv run python 07-embedding-basics\run.py query "玻璃幕墙应该怎样挂接到墙体？" --k 3

# 6. 再次同步。文档未变化时应显示 added=0
uv run python 07-embedding-basics\run.py sync
```

`.env` 中聊天模型和向量模型使用不同变量。下面以腾讯云 TokenHub 文本向量模型为例：

```dotenv
# 聊天服务，保持你原来的配置
LLM_MODEL=你的聊天模型名
LLM_BASE_URL=https://你的聊天服务地址/v1
LLM_API_KEY=你的聊天服务密钥

# 腾讯云 TokenHub 向量服务
EMBEDDING_MODEL=kinfra-text-embedding-0.6b
EMBEDDING_BASE_URL=https://tokenhub.tencentmaas.com/v1
EMBEDDING_API_KEY=你的_TokenHub_API_Key
```

也可以把模型改为 `kinfra-text-embedding-4b`，但它与 `0.6b` 的向量维度不同，切换后必须重建集合。不要把 API Key 写进 Notebook、代码、Chroma metadata 或 Git。

## 代码地图

```text
07-embedding-basics/
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

各章提到的练习都由你写入自己的 `01.basic.ipynb`，模块不会生成额外 `.py` 测试文件。

## 学完后应该能回答

- Chroma 保存的不只是向量，还保存什么？
- 为什么查询也必须调用 Embedding 模型？
- 为什么 `sync` 第二次运行通常不再请求所有文档的向量？
- 修改 `EMBEDDING_MODEL` 或切块参数后，为何旧索引不能直接复用？
- 检索错误和大模型回答错误应该怎样分开定位？

这些问题都能独立讲清楚，才算真正掌握本模块。
