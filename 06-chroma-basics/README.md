# 06 · Chroma 向量数据库基础

本模块是独立的 Chroma 学习内容，只介绍 Chroma 自身的概念、Python API 和运行方式。

当前项目锁定的依赖版本是 chromadb 1.5.9。文档以 Chroma 1.5.x 的 Python API 和官方资料为准。

## 模块边界

本模块只回答下面的问题：

- Chroma 有哪些客户端创建方式？
- 怎样创建、获取、修改、列出和删除 Collection？
- 一条 Record 由哪些字段组成？
- add、upsert、update 和 delete 有什么区别？
- get、query、peek 和 count 分别适合什么场景？
- 怎样使用 metadata、文档内容、ID、分页条件过滤数据？
- 怎样选择内存、本地持久化、服务端和 Cloud 模式？
- HNSW、cosine、l2 和 ip 是什么？

文本怎样转换成向量、怎样选择或切换向量模型，属于后续独立的 [07-embedding-basics](../07-embedding-basics/README.md)。

## 学习顺序

| 章节 | 核心内容 |
| --- | --- |
| [第 1 章：认识 Chroma](docs/01-认识Chroma.md) | 安装、定位、对象层级和 API 全景 |
| [第 2 章：客户端创建方式](docs/02-客户端创建方式.md) | Ephemeral、Persistent、HTTP、Async HTTP、Cloud |
| [第 3 章：Collection 管理](docs/03-Collection管理.md) | 创建、获取、列出、修改、删除和索引配置 |
| [第 4 章：数据插入方式](docs/04-数据插入方式.md) | Record 结构、add、不同输入组合和批量规则 |
| [第 5 章：读取与向量查询](docs/05-读取与向量查询.md) | get、query、peek、count、include 和距离 |
| [第 6 章：过滤、分页与返回结构](docs/06-过滤分页与返回结构.md) | where、where_document、逻辑操作符和分页 |
| [第 7 章：更新、Upsert 与删除](docs/07-更新Upsert与删除.md) | update、upsert、记录删除和破坏性操作 |
| [第 8 章：持久化、服务端与 Cloud](docs/08-持久化服务端与Cloud.md) | 四种运行形态、CLI、Docker 和异步客户端 |
| [第 9 章：索引配置、常见错误与练习](docs/09-索引配置常见错误与练习.md) | HNSW、距离空间、排错清单和单元练习 |

## 推荐学习方法

每章按下面的流程学习：

1. 先阅读概念和方法签名。
2. 在你自己的 01.basic.ipynb 中只练习本章 API。
3. 打印返回对象，观察真实数据结构。
4. 故意制造重复 ID、错误维度、错误过滤条件等异常。
5. 写下“输入、返回值、是否持久化、是否调用向量计算”四项结论。

本模块只提供文档和练习要求，不替你完成单元代码。

## 官方资料

- [Chroma Python Client](https://docs.trychroma.com/reference/python/client)
- [管理 Collection](https://docs.trychroma.com/docs/collections/manage-collections)
- [添加数据](https://docs.trychroma.com/docs/collections/add-data)
- [Query 与 Get](https://docs.trychroma.com/docs/querying-collections/query-and-get)
- [Metadata Filtering](https://docs.trychroma.com/docs/querying-collections/metadata-filtering)
- [配置 Collection](https://docs.trychroma.com/docs/collections/configure)
