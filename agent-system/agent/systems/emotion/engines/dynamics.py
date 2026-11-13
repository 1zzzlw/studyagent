"""借鉴 Sentimo 的人格调节和混合；时间恢复改为显式按小时计算。"""
import math
from datetime import datetime
from ..domain.models import EmotionState, EmotionVector

# 第一版固定的人格调节参数，避免新增第五个人格系统。
PERSONALITY = {"sensitivity": 0.85, "extraversion": 0.55,
               "neuroticism": 0.35, "agreeableness": 0.75,
               "openness": 0.7, "conscientiousness": 0.65}


def recover(state: EmotionState, now: datetime) -> EmotionState:
    hours = max(0.0, (now - state.updated_at).total_seconds() / 3600)
    factor = math.exp(-hours / 6.0)
    values = {key: state.baseline + (value - state.baseline) * factor
              for key, value in state.values.model_dump().items()}
    return EmotionState(values=EmotionVector(**values), baseline=state.baseline, updated_at=now)


def apply(state: EmotionState, reaction: EmotionVector, now: datetime) -> EmotionState:
    state = recover(state, now)
    p = PERSONALITY
    alpha = min(1.0, 0.2 * p["sensitivity"] * (1 + 0.5 * p["extraversion"]))
    values = {}
    for key, current in state.values.model_dump().items():
        target = getattr(reaction, key)
        blended = current + alpha * (target - current)
        values[key] = max(0.0, min(1.0, blended - 0.02 * p["conscientiousness"]
                                   * (blended - state.baseline)))
    return EmotionState(values=EmotionVector(**values), baseline=state.baseline, updated_at=now)
