"""公共消息与观察；不持有人物、情绪的可变状态。"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, field_validator

# 项目处理现代北京时间，固定 UTC+08:00，不依赖服务器系统时区或 Windows tzdata。
BEIJING = timezone(timedelta(hours=8), "Asia/Shanghai")


def beijing_now() -> datetime:
    return datetime.now(BEIJING)


def as_beijing(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间缺少时区，不能确定其实际时间点")
    return value.astimezone(BEIJING)


def beijing_record_times(value):
    """只转换结构化时间字段，不修改原话、正文或其他普通字符串。"""
    fields = {"created_at", "updated_at", "expires_at", "anchor_at", "last_recalled_at",
              "started_at", "finished_at", "now", "当前时间", "观察时间"}
    if isinstance(value, dict):
        return {key: as_beijing(datetime.fromisoformat(item)).isoformat()
                if key in fields and isinstance(item, str) else beijing_record_times(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [beijing_record_times(item) for item in value]
    return value

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @field_validator("*")
    @classmethod
    def normalize_time(cls, value):
        return as_beijing(value) if isinstance(value, datetime) else value

class Message(Model):
    id: int
    message_id: str
    conversation_id: str
    role: str
    content: str
    created_at: datetime
    reply_to_message_id: str | None = None
