# 对话系统

接收其他系统提供的信息，组织提示词并调用一次回复模型。

初版实际文件为 `domain/models.py`、`application/service.py`、`prompting/builder.py`。上下文由 `application/runtime.py` 组织；不另建润色、重试或流式生成链。下表保留为规划参考。

## 内部分层与规划文件

| 层 | 文件 | 职责 |
| --- | --- | --- |
| `domain` | `context.py` | 本轮 DialogueContext |
| `domain` | `reply.py` | DialogueReply：正文与采用的记忆 ID |
| `application` | `service.py` | generate，一次调用生成回复 |
| `prompting` | `builder.py` | 组织上下文、数据说明和表达约束 |
| `prompting` | `reply.txt` | 可直接阅读的固定回复要求 |

## 本轮输入

`DialogueContext` 包含：

- 角色名字及简短固定设定。
- 当前时间。
- 用户本轮原话与有限的近期对话。
- CharacterStateSnapshot。
- EmotionSnapshot。
- 记忆系统输出的有限 RecallItem。

这里装的是本轮快照和视图，不直接获得四个系统的可变仓库。

## 怎样影响回答

| 信息 | 主要影响 |
| --- | --- |
| 人物状态 | 对话投入、回复篇幅、是否适合继续展开 |
| 当前情绪 | 感受、语气和表达倾向 |
| 记忆内容 | 可以参考哪些经历与背景 |
| 回忆清晰程度 | 哪些信息明确、哪些需要保留模糊或请求确认 |

这几种输入独立提供，不都压成一个记忆强度分数。

## 输出契约

~~~text
DialogueReply
    answer: 实际回复正文
    used_memory_ids: 本轮真正用于组织回答的记忆 ID
~~~

程序检查 IDs 必须来自本轮允许集合，然后把它们交回记忆系统登记回忆。

第一版不让回复模型同时负责提炼新记忆、生成反思和维护人物状态。那些动作各自有明确的输入、输出和处理时机。

## 一次模型调用的含义

~~~text
generate(context)
    ↓
构建提示词
    ↓
一次结构化回复调用
    ↓
得到 answer 与 used_memory_ids
~~~

不额外增加 Planner、回复润色、重试生成或回复后的二次审查调用。调用或解析失败时明确报告，由上层决定如何处理。

其他系统可能各自使用模型；它们的调用不能隐藏在“对话只调用一次”这个说法里。
