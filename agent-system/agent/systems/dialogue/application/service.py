from ..domain.models import DialogueReply
from ..prompting.builder import INSTRUCTIONS


class DialogueService:
    def __init__(self, model):
        self.model = model

    def generate(self, context):
        # 一次生成同时返回正文和使用的记忆ID，无二次润色或自动重试。
        reply = self.model.ask(DialogueReply, INSTRUCTIONS, context, purpose="dialogue")
        allowed = {item["node_id"] for item in context["长期回忆"]}
        if not set(reply.used_memory_ids).issubset(allowed):
            raise ValueError("回答引用了未提供的长期记忆 ID")
        return reply
