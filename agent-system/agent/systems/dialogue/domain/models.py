from pydantic import Field
from ....common.models import Model


class DialogueReply(Model):
    answer: str = Field(min_length=1, description="直接发送的自然聊天正文，不含内部分析或系统参数")
    used_memory_ids: list[str] = Field(default_factory=list, description="真正采用的长期记忆ID；未采用时为空列表")
