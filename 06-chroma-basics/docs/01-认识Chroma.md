# 第 1 章：认识 Chroma

## 本章目标

知道 Chroma 解决什么问题、核心对象是什么，以及后续应该按照什么顺序练习 API。

## 1. 安装与版本

当前 studyAgent 使用：

~~~toml
chromadb>=1.5.9
~~~

安装或同步依赖：

~~~powershell
uv add chromadb
uv sync
~~~

查看实际版本：

~~~python
import chromadb

print(chromadb.__version__)
~~~

学习 Chroma 时要记录版本。网上很多旧教程使用已经变化的配置方式，不能只复制代码而不核对当前 API。

## 2. Chroma 是什么

Chroma 是面向向量数据的数据库。它能够保存向量以及关联的 ID、原文、Metadata、URI 等信息，并提供相似度查询、条件过滤和持久化能力。

Chroma 返回的是记录或候选结果，不负责生成最终自然语言答案。

## 3. 核心对象层级

~~~text
Client
└── Tenant
    └── Database
        └── Collection
            └── Record
                ├── id
                ├── embedding
                ├── document
                ├── metadata
                └── uri / data
~~~

入门阶段重点掌握 Client、Collection 和 Record。Tenant、Database 主要在服务端或 Cloud 多租户场景中使用。

## 4. API 全景

| 分类 | 常用方法 |
| --- | --- |
| 客户端 | heartbeat、version、reset |
| Collection 管理 | create_collection、get_collection、get_or_create_collection |
| Collection 列表 | list_collections、count_collections |
| Collection 修改 | modify、delete_collection |
| 写入记录 | add、upsert |
| 读取记录 | get、peek、count |
| 相似度查询 | query |
| 修改记录 | update |
| 删除记录 | delete |

## 5. 本章练习

在自己的 Notebook 中完成：

1. 打印 chromadb 版本。
2. 创建一个内存客户端。
3. 调用 heartbeat 和 version。
4. 打印客户端对象类型。
5. 不查资料，画出 Client、Collection、Record 的关系。

参考：[Chroma Python Client](https://docs.trychroma.com/reference/python/client)

