# 第 8 章：持久化、服务端与 Cloud

## 本章目标

理解 Chroma 的不同运行形态，以及本地嵌入式数据库和独立服务之间的边界。

## 1. 四种常见形态

| 形态 | Client | 数据位置 | 适用场景 |
| --- | --- | --- | --- |
| 临时内存 | EphemeralClient | 当前进程 | 单元测试、短期实验 |
| 本地持久化 | PersistentClient | 本机目录 | 个人学习、本地开发 |
| 独立服务 | HttpClient / AsyncHttpClient | Chroma Server | 多进程、多应用访问 |
| 托管服务 | CloudClient | Chroma Cloud | 托管数据库 |

## 2. PersistentClient

~~~python
client = chromadb.PersistentClient(path="./storage/chroma")
~~~

数据会自动持久化并在下一次连接相同目录时加载。路径、Collection 名称、Tenant 和 Database 共同决定你最终读取的是哪批数据。

## 3. CLI 服务端模式

~~~powershell
chroma run --path ./storage/chroma-server
~~~

~~~python
client = chromadb.HttpClient(host="localhost", port=8000)
client.heartbeat()
~~~

Client 和 Server 的版本应保持兼容。服务端模式下，应用进程退出不等于 Chroma 数据库停止或数据消失。

## 4. Docker

~~~powershell
docker run -v ./chroma-data:/data -p 8000:8000 chromadb/chroma
~~~

~~~python
client = chromadb.HttpClient(host="localhost", port=8000)
~~~

容器重新创建后是否保留数据取决于是否正确挂载持久化目录。

## 5. AsyncHttpClient

异步 Client 适合异步 Web 服务。所有远程方法需要 await，并且应在应用生命周期内复用 Client，而不是每次请求都创建连接。

## 6. CloudClient

CloudClient 需要 API Key，并可配置 Tenant 和 Database。凭证应放入环境变量或密钥管理服务。

## 7. 生命周期检查

建议为每种模式检查：

- heartbeat 是否成功；
- version 是否符合预期；
- Tenant 和 Database 是否正确；
- Collection 是否存在；
- count 是否符合预期；
- 重启后数据是否保留；
- 多个进程是否连接到同一服务。

## 8. 本章练习

依次使用 EphemeralClient、PersistentClient 和 HttpClient 完成同一组 create/add/get 操作，重启进程后比较差异。CloudClient 只阅读配置方式，不必为了学习强行开通服务。

参考：[Chroma Clients](https://docs.trychroma.com/docs/run-chroma/clients)、[Client-Server Mode](https://docs.trychroma.com/docs/run-chroma/client-server)、[Docker](https://docs.trychroma.com/guides/deploy/docker)

