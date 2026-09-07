# 第 7 章：更新、Upsert 与删除

## 本章目标

区分 update、upsert、delete、delete_collection 和 reset，并理解哪些操作具有破坏性。

## 1. update

~~~python
collection.update(
    ids=["doc-1"],
    documents=["更新后的文本"],
    metadatas=[{"status": "reviewed"}],
)
~~~

update 只处理已经存在的 ID。ID 不存在时不会像 upsert 一样自动创建。

如果只提交 documents 而不提交 embeddings，并且 Collection 有 Embedding Function，Chroma 会重新计算向量。

## 2. upsert

~~~python
collection.upsert(
    ids=["doc-1", "doc-2"],
    documents=["可能已存在", "可能是新数据"],
)
~~~

upsert 的语义：

- ID 已存在：更新；
- ID 不存在：新增。

因此它适合重复运行的数据同步，但仍要设计稳定 ID，避免相同内容不断产生新记录。

## 3. 删除记录

按 ID 删除：

~~~python
collection.delete(ids=["doc-1", "doc-2"])
~~~

按 Metadata 删除：

~~~python
collection.delete(where={"status": "expired"})
~~~

也可以使用 where_document。delete 至少要提供 ID 或过滤条件，否则应视为危险操作。

## 4. 删除层级

| 操作 | 影响范围 |
| --- | --- |
| collection.delete | 删除符合条件的 Record |
| client.delete_collection | 删除整个 Collection |
| client.reset | 删除当前数据库中的全部 Collection 和数据 |
| 删除持久化目录 | 直接破坏本地数据库文件 |

生产代码应优先使用精确 ID 或过滤条件。delete_collection 和 reset 必须经过显式确认，不应藏在普通启动流程中。

## 5. 更新时的列式对齐

与 add 相同，update 和 upsert 的 ids、documents、embeddings、metadatas 等列表按下标对应，长度必须匹配。

## 6. 本章练习

创建三条记录，然后依次测试：

1. update 已存在 ID；
2. update 不存在 ID；
3. upsert 已存在 ID；
4. upsert 新 ID；
5. 按 ID 删除；
6. 按 Metadata 删除；
7. 对比删除 Record 与删除 Collection 后的 count 结果。

参考：[Update Data](https://docs.trychroma.com/docs/collections/update-data)、[Delete Data](https://docs.trychroma.com/docs/collections/delete-data)

