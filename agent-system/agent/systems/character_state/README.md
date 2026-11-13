# 人物状态系统

回答“角色现在处于什么处境、能够投入多少精力和注意力”。

初版实际文件为 `domain/models.py`、`application/service.py`、`engines/attention.py`。通过界面手动更新状态，尚未自动模拟生活活动或精力恢复；下表的进一步拆分保留为规划。

## 内部分层与规划文件

| 层 | 文件 | 职责 |
| --- | --- | --- |
| `domain` | `state.py` | CharacterState 与只读快照 |
| `domain` | `attention.py` | 本次观察的 AttentionAppraisal |
| `domain` | `changes.py` | 显式状态变化及其来源 |
| `application` | `service.py` | 初始化、读取快照、应用变化、评价观察 |
| `engines` | `attention.py` | 根据角色处境与观察分配注意力 |
| `engines` | `recovery.py` | 根据明确活动和时间规则计算精力等变化 |

Sentimo 的 typed state、规则更新和快照组织方式可借鉴；精力、活动、环境等并非 Sentimo 已有的完整实现，需要结合当前需求设计。

## 人物当前状态

`CharacterState` 初步规划：

- `character_id`：状态属于谁。
- `energy`：角色精力，0～1。
- `activity`：角色当前活动。
- `attention_focus`：目前注意力焦点。
- `environment`：已知环境。
- `busyness`：忙碌程度，0～1。
- `current_intent`：眼下意图。
- `updated_at`：最近一次有依据的更新。

当前情绪不再重复放成 `mood` 字段，避免这里和情感系统各自维护一份冲突的情绪。

第一版可以在初始化配置中给出固定状态，并通过显式事件或手动操作更新。模型没有环境信息时，不自行编造角色去了哪里、做了什么。

## 本次注意力评价

`AttentionAppraisal` 初步包含：

- `observation_id`：正在评价的观察。
- `attention`：对本次内容的实际留意程度。
- `reason`：供调试阅读的简短解释。

`attention` 不等于 `attention_focus`：

- focus 说明当前关注什么。
- attention 说明这次内容实际获得多少注意。

评价结果交给记忆形成流程；不把人物当前状态整体复制进每条记忆。

## 情感怎样影响人物状态

情感系统可以给出本轮的状态影响建议，例如“担忧使注意力更集中在某个问题”。更新仍通过人物状态服务执行，并记录来源。

不能因为用户自己说疲惫，就直接修改角色的精力；用户状态和角色状态需区分。

## 对外接口草图

~~~text
snapshot(character_id, now) -> CharacterStateSnapshot
apply_change(change, now) -> CharacterStateSnapshot
appraise_attention(observation, emotion_snapshot, now) -> AttentionAppraisal
advance_time(now) -> CharacterStateSnapshot
~~~

注意力、精力恢复和情绪影响的具体参数后续再实现与调整，本轮不假定存在公认的唯一计算公式。
