from pydantic import BaseModel, Field, ConfigDict, AwareDatetime
from typing import Literal


class MemoryNode(BaseModel):
    """
    记忆节点，包含以下字段：
    """

    # validate_assignment=True：
    # 创建对象后，重新给字段赋值时也进行校验。
    # 例如 node.attention = 2 会因为超出 0～1 而报错。
    # 注意：这不等于会自动检查 list.append() 等容器内部修改。
    #
    # allow_inf_nan=False：
    # 浮点数字段不允许出现无穷大或 NaN。
    model_config = ConfigDict(
        validate_assignment=True,
        allow_inf_nan=False,
    )

    # ==================== 1. 编号与记忆类型 ====================

    # 记忆的唯一 ID
    # filling、links、supersedes_id 都通过这个 ID 引用其他记忆
    node_id: str

    # 这条记忆在整个记忆集合中的创建序号。
    # 例如：先创建 event，再创建 chat，它们可以分别是第 1、2 条记忆。
    # 这是序号，不是当前记忆总数。
    node_count: int = Field(ge=1)

    # 这条记忆在同类型记忆中的序号。
    # 例如：整个集合中的第 10 条记忆，可能是第 3 条 thought。
    type_count: int = Field(ge=1)

    # event：从交流中提炼出的事件、经历或用户陈述。
    # thought：根据已有记忆反思、归纳形成的认识，可能包含推测。
    # chat：保存实际对话原话。
    type: Literal["event", "thought", "chat"] = "event"

    # 反思层级。
    # 当前代码中，普通 event、chat 通常为 0。
    # thought 的层级 = 它引用的证据中最大层级 + 1。
    # 表示认识的推导层次，不是 links 的数量或图上的距离。
    depth: int = Field(default=0, ge=0)

    # ==================== 2. 时间 ====================

    # 这条记忆形成的时间，必须带时区。
    # 它不一定等于事情发生的时间：
    # 今天听用户讲去年发生的事，created 通常仍然是今天。
    created: AwareDatetime

    # 有效截止时间；None 表示没有设置截止时间。
    # 当前代码会在选择记忆时排除已到期的节点。
    # 到期与强度衰减是两个不同的判断，也不会因此自动删除正文。
    expiration: AwareDatetime | None = None

    # 最近一次实际回忆的时间。
    # 初次创建时设置为 created，实际采用记忆后再更新。
    # 在你的引擎中，它也是计算时间衰减的基准时间。
    # 仅仅被检索为候选，不会因此更新这个时间。
    last_accessed: AwareDatetime

    # ==================== 3. 记忆的内容 ====================

    # 主体：谁。
    # 例如“用户”“小王”“角色自己”。
    subject: str = "用户"

    # 谓语：做了什么、表达了什么，或者存在什么关系。
    # 例如“喜欢”“邀请”“表示”“认为”。
    predicate: str = "表示"

    # 客体：动作或关系指向什么。
    # 例如“咖啡”“一起去图书馆”“最近面试很紧张”。
    object: str = "过去的经历"

    # 记忆正文，是这条记忆的主要自然语言表达。
    # 例如：“用户邀请我周六去书店，但我们尚未确认。”
    # subject/predicate/object 是简要结构，description 保存更多细节。
    description: str = Field(min_length=1)

    # 关键词，用于描述、索引和查找记忆。
    # 例如 {"面试", "紧张", "失眠"}。
    # set 会去重；default_factory=set 为每个对象创建自己的集合。
    keywords: set[str] = Field(default_factory=set)

    # 重要性评分，范围 1～10。
    # 表示这件事对角色有多重要。
    # 它与情绪反应强度不同：重要的事情也可能没有强烈情绪。
    poignancy: float = Field(default=5, ge=1, le=10)

    # ==================== 4. 来源与证据 ====================

    # 补充内容，当前代码根据 type 使用不同格式：
    #
    # chat：
    # 保存实际双方原话，例如：
    # [("用户", "我最近面试紧张"), ("小忆", "担心哪一部分？")]
    #
    # event：
    # 保存来源节点 ID，例如本轮 chat 的 ID、相关旧记忆的 ID。
    #
    # thought：
    # 保存支持这条认识的证据节点 ID。
    # 例如 ["event_001", "event_002"]。
    #
    # 所以 thought.filling 主要回答：“这个认识根据什么形成？”
    filling: list[str] | list[tuple[str, str]] = Field(
        default_factory=list
    )

    # 来源观察的编号。
    # 一轮交流可以形成多个节点，它们可以共用同一个 observation ID。
    # 用来表示这些记忆来自同一次观察。
    # 它与 node_id 不同，不一定对应某条可以直接读取的记忆。
    source_observation_id: str | None = None

    # 记忆的产生途径，与 type 分开记录：
    # seed：导入的初始记忆。
    # dialogue：实际对话产生的记忆。
    # reflection：反思生成的认识。
    origin: Literal["seed", "dialogue", "reflection"] = "dialogue"

    # ==================== 5. 衰减与强化 ====================

    # 形成记忆时，角色对内容的留意程度，范围 0～1。
    # 参与初始强度的计算。
    attention: float = Field(default=1, ge=0, le=1)

    # 内容带来的情绪反应强度，范围 0～1。
    # 这里只记录强弱，不区分开心、悲伤、恐惧等情绪类型。
    emotional_impact: float = Field(default=0, ge=0, le=1)

    # 记忆刚形成时的初始强度。
    # 当前引擎根据 attention、emotional_impact、poignancy 计算。
    # 用于保留这条记忆的初始状态。
    initial_strength: float = Field(default=1, ge=0, le=1)

    # 最近一次强化后，作为新一轮衰减起点的基准强度。
    # 刚创建时等于 initial_strength，成功回忆后可能增加。
    # 注意：它不是经过时间衰减后的“当前强度”。
    strength_after_recall: float = Field(default=1, ge=0, le=1)

    # 稳定性参数，单位为天。
    # 数值越大，遗忘越慢；实际回忆后可以增加。
    # 在当前指数公式中，经过 stability_days 天，
    # 强度约剩下本轮基准强度的 36.8%，不是减半。
    stability_days: float = Field(default=30, gt=0)

    # 实际回忆次数。
    # 当前流程在回答采用这条长期记忆后增加。
    # 不等于它被向量检索命中的次数。
    recall_count: int = Field(default=0, ge=0)

    # 当前记录的记忆状态：
    # active：比较清晰。
    # fading：正在淡忘。
    # forgotten：强度很低，但当前代码仍允许检索和唤起。
    # superseded：已经被明确纠正，不再作为有效认识使用。
    #
    # 这个字段需要由引擎更新，不会仅因为时间过去就自动变化。
    status: Literal[
        "active", "fading", "forgotten", "superseded"
    ] = "active"

    # 当前这条新记忆纠正了哪一条旧记忆。
    # 例如新记忆 B.supersedes_id = A.node_id，
    # 表示 B 纠正了 A，随后 A 被标记为 superseded。
    #
    # 当前设计用于明确纠正错误认识；
    # “以前喜欢咖啡，现在不喜欢”属于随时间变化，
    # 不应简单地把过去真实的偏好判为错误。
    supersedes_id: str | None = None

    # ==================== 6. 语义说明与普通关联 ====================

    # 对这条记忆的背景、主题和含义的补充说明。
    # 例如“用户近期求职经历中的压力表现”。
    # 这是单条记忆的背景描述，不是整段聊天上下文。
    context: str = ""

    # 主题标签，可以有多个。
    # 例如 ["求职", "压力", "睡眠"]。
    tags: list[str] = Field(default_factory=list)

    # 主要分类。
    # 例如“个人偏好”“共同经历”“近期计划”。
    # 相比 tags，它适合表达一个主要归属。
    category: str = ""

    # 与这条记忆相关的其他记忆 ID。
    # 主要回答：“还可以联系哪些记忆一起看？”
    #
    # links 表达相关，不自动代表因果或证据。
    # 当前 v3 对普通相关关系采用双向链接。
    links: list[str] = Field(default_factory=list)

    # 记忆整理、演化过程的记录。
    # 当前代码主要记录 context、tags 的修改：
    # 修改时间、触发修改的节点，以及修改前后的值。
    # 它不是所有字段变化的完整历史。
    evolution_history: list[dict] = Field(default_factory=list)

    # 是否已经完成过语义整理与关联分析。
    # True 表示处理过，不代表一定建立了 links。
    # 即使最终没有相关记忆，也可以是 True。
    association_ready: bool = False

    # 是否已经完成反思处理。
    # 主要用于避免同一批事件反复触发反思。
    # True 不代表一定产生了新 thought：
    # 处理后判断没有值得保存的新认识，也可能标记为 True。
    reflected: bool = False