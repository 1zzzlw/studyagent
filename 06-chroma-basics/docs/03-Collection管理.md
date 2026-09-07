# 第 3 章：Collection 管理

## 本章目标

掌握 Collection 的创建、获取、枚举、修改和删除，并区分“Collection 配置”与“Record Metadata”。

## 1. create_collection

~~~python
collection = client.create_collection(name="my_collection")
~~~

名称在同一个 Database 内必须唯一。当前官方规则包括：

- 长度为 3 到 512 个字符；
- 以小写字母或数字开始和结束；
- 中间可使用点、短横线和下划线；
- 不能包含连续两个点；
- 不能是合法 IP 地址。

同名集合已经存在时，create_collection 会报错。

## 2. get_collection

~~~python
collection = client.get_collection(name="my_collection")
~~~

它只获取已有集合；集合不存在时会失败。适合“数据库必须已经初始化”的场景。

## 3. get_or_create_collection

~~~python
collection = client.get_or_create_collection(
    name="my_collection",
    metadata={"purpose": "learning"},
)
~~~

集合不存在时创建，存在时直接返回。需要注意：集合已经存在时，创建参数不会重新覆盖已有配置。

## 4. list_collections 与 count_collections

~~~python
collections = client.list_collections(limit=100, offset=0)
count = client.count_collections()
~~~

list_collections 支持分页。不要默认认为一次调用永远返回全部集合。

## 5. Collection 自身信息

Collection 对象可查看 name、metadata、configuration 和 embedding_function。常用辅助方法：

~~~python
collection.count()
collection.peek()
~~~

count 返回记录总数；peek 用于快速查看前若干条记录。

## 6. modify

~~~python
collection.modify(
    name="new_collection_name",
    metadata={"purpose": "updated"},
)
~~~

modify 可以修改集合名称、集合级 Metadata，以及部分允许动态调整的配置。

集合级 Metadata 描述整个集合；Record Metadata 描述单条记录，两者不要混淆。

## 7. delete_collection

~~~python
client.delete_collection(name="my_collection")
~~~

这会删除整个 Collection 及其中全部向量、文档和 Metadata。它不同于 collection.delete，后者只删除符合条件的 Record。

## 8. 创建时的关键选项

~~~python
collection = client.create_collection(
    name="cosine_collection",
    metadata={"description": "learning"},
    configuration={
        "hnsw": {
            "space": "cosine"
        }
    },
)
~~~

embedding_function 也可以在创建 Collection 时指定，但它的模型原理放在第 07 模块学习。

## 9. 本章练习

完成 create、get、get_or_create、list、count、modify 和 delete_collection，每一步都打印 Collection 数量和名称，观察同名创建与不存在获取的异常。

参考：[Manage Collections](https://docs.trychroma.com/docs/collections/manage-collections)

