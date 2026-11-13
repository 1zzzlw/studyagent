# 情感系统

负责角色自己的持续情绪与本次情感反应，直接影响对话，并为记忆形成提供评价。

初版实际文件为 `domain/models.py`、`application/service.py`、`engines/dynamics.py`；固定人格调节参数在引擎内，下表的进一步拆分保留为规划。

## 内部分层与规划文件

| 层 | 文件 | 职责 |
| --- | --- | --- |
| `domain` | `state.py` | EmotionState 与 EmotionSnapshot |
| `domain` | `appraisal.py` | 本次观察的 EmotionAppraisal |
| `domain` | `parameters.py` | 人格调节与恢复参数，先作为初始化配置 |
| `application` | `appraisal.py` | 结合角色与经历，评价消息对角色的影响 |
| `application` | `service.py` | 组织评价、调用引擎、存取情绪并提供快照 |
| `engines` | `dynamics.py` | Sentimo 风格的平滑混合、调节与基线恢复 |

模型接口由统一技术适配层传入，情感系统不自行读取 API Key。

## 参考 Sentimo 的部分

本地 Sentimo 的 `src/state.py` 定义了：

- 六种情绪：joy、sadness、anger、fear、trust、curiosity。
- Personality 参数：sensitivity 与若干人格维度。
- `apply_emotion_vector`：融合新的情绪向量。
- `decay`：向基线恢复。

这些用于构建情绪动态的第一版规则。它们是可调整的工程模拟，不直接代表真实人格或临床测量。

## 分清“当前状态”和“这次反应”

`EmotionState` 保存角色当前的六种情绪值、基线、最近更新时间与角色 ID。

`EmotionAppraisal` 保存本次观察的：

- `observation_id`。
- 角色对这次内容的反应向量。
- `emotional_impact`：这次内容引起的冲击程度。
- 简短的评价依据。

当前情绪很强，不代表每条新消息都带来很强冲击。`emotional_impact` 不能直接取当前最大的情绪值，也不能简单等同于用户消息的情绪强度。

## 从用户情绪到角色反应

Sentimo 原有分类主要从消息提取情绪线索。本框架的评价需要额外输入：

~~~text
用户实际表达
+ 角色初始化设定
+ 角色原有情绪
+ 当前人物状态
+ 相关经历
    ↓
角色对这次观察的反应
~~~

用户难过时，角色可能表现出关切和担忧；不能把用户的悲伤数值原样复制成角色自身状态。

需要时可使用一次结构化模型评价，但回复正文仍交给对话系统。

## 更新步骤

1. 按统一时间处理已有情绪的恢复。
2. 评价本次内容对角色的反应。
3. 由引擎进行人格调节和平滑混合。
4. 通过情感服务保存新状态。
5. 输出快照与本次评价。

一轮只应用一次本次反应，避免在记忆整理阶段再次重复增加同一消息的情绪影响。

原 Sentimo 的 `decay` 是按轮迭代。后续若实现按时间推进，需要明确恢复时间尺度，不能只把每轮系数直接当作“每天系数”。

## 与其他系统的接口

~~~text
appraise(observation, character_state, relevant_memories, now)
    -> EmotionAppraisal

apply(appraisal, now) -> EmotionSnapshot
snapshot(character_id, now) -> EmotionSnapshot
advance_time(now) -> EmotionSnapshot
~~~

情绪快照直接影响回复语气与表达倾向；本次 emotional_impact 另行交给记忆形成。

当前 trust 表达角色的信任感，尚不承担针对每个人长期维护的关系数据。
