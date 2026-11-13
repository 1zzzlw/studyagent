"""模型网关协议回归：不访问真实模型，保留失败证据。"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from langchain_core.messages import AIMessage
from agent.infrastructure.llm.models import ModelGateway
from agent.systems.dialogue.domain.models import DialogueReply
from agent.systems.memory.domain.models import Formation


class ChatStub:
    def __init__(self, response):
        self.response = response
        self.options = {}
        self.calls = 0

    def bind(self, **options):
        self.options.update(options)
        return self

    def invoke(self, messages):
        self.calls += 1
        self.messages = messages
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class ModelGatewayTests(unittest.TestCase):
    def gateway(self, response):
        stub = ChatStub(response)
        with patch.dict(os.environ, {"LLM_MODEL": "test-model", "LLM_API_KEY": "not-a-real-key",
                                     "LLM_MAX_TOKENS": "4096", "LLM_REASONING_EFFORT": ""}):
            with patch("langchain_openai.ChatOpenAI", return_value=stub):
                gateway = ModelGateway()
        events = []
        gateway.observer = lambda stage, message, payload: events.append((stage, payload))
        return gateway, stub, events

    def test_json_constraint_is_sent_in_one_request(self):
        gateway, stub, _ = self.gateway(AIMessage(content='{"answer":"你好","used_memory_ids":[]}'))
        result = gateway.ask(DialogueReply, "请回复", {}, "dialogue")
        self.assertEqual(result.answer, "你好")
        self.assertEqual(stub.options.get("response_format"), {"type": "json_object"})
        self.assertEqual(stub.calls, 1)

    def test_plain_text_failure_has_visible_response_diagnostics(self):
        gateway, stub, events = self.gateway(AIMessage(content="你好，今天怎么样？",
                                                      response_metadata={"finish_reason": "stop"}))
        with self.assertRaises(ValueError):
            gateway.ask(DialogueReply, "请回复", {}, "dialogue")
        stage, diagnostic = events[-1]
        self.assertEqual(stage, "model_failed")
        self.assertEqual(diagnostic["finish_reason"], "stop")
        self.assertEqual(diagnostic["content_preview"], "你好，今天怎么样？")
        self.assertEqual(stub.calls, 1)

    def test_nested_formation_schema_is_inlined_and_distinguished_from_data(self):
        value = {"events": [{"description": "用户喜欢阅读", "subject": "用户", "predicate": "喜欢",
                             "object": "阅读", "importance": 7, "keywords": ["阅读"],
                             "context": "用户明确表达偏好", "tags": ["偏好"], "category": "兴趣"}],
                 "neighbor_updates": []}
        gateway, stub, _ = self.gateway(AIMessage(content=json.dumps(value)))
        result = gateway.ask(Formation, "整理记忆", {}, "memory_formation")
        self.assertEqual(result.events[0].description, "用户喜欢阅读")
        prompt = stub.messages[0].content
        self.assertNotIn('"$defs"', prompt)
        self.assertNotIn('"$ref"', prompt)
        self.assertIn("最外层字段：events、neighbor_updates", prompt)
        self.assertIn("不要返回 Schema 本身", prompt)
        self.assertEqual(stub.calls, 1)

    def test_schema_shaped_formation_is_rejected_without_losing_it_silently(self):
        value = {"$defs": {"MemoryDraft": {"description": "被错误放在格式定义中的记忆"}}}
        gateway, stub, events = self.gateway(AIMessage(content=json.dumps(value)))
        with self.assertRaisesRegex(ValueError, "extra_forbidden"):
            gateway.ask(Formation, "整理记忆", {}, "memory_formation")
        self.assertEqual(events[-1][0], "model_failed")
        self.assertIn("$defs", events[-1][1]["content_preview"])
        self.assertEqual(stub.calls, 1)

    def test_formation_still_checks_nested_fields_and_accepts_explicit_empty_arrays(self):
        for draft in ({"description": "缺少必要字段"},
                      {"description": "事件", "subject": "用户", "predicate": "说", "object": "阅读",
                       "importance": 11, "keywords": [], "context": "", "tags": [], "category": ""}):
            with self.subTest(draft=draft):
                gateway, _, _ = self.gateway(AIMessage(content=json.dumps({"events": [draft]})))
                with self.assertRaises(ValueError):
                    gateway.ask(Formation, "整理记忆", {}, "memory_formation")
        gateway, _, _ = self.gateway(AIMessage(content='{"events":[],"neighbor_updates":[]}'))
        self.assertEqual(gateway.ask(Formation, "整理记忆", {}, "memory_formation").events, [])

    def test_reasoning_only_truncation_is_not_misreported_as_normal_json_error(self):
        response = AIMessage(content="", additional_kwargs={"reasoning_content": "不应写入日志的隐藏推理"},
                             response_metadata={"finish_reason": "length"},
                             usage_metadata={"input_tokens": 100, "output_tokens": 4096, "total_tokens": 4196,
                                             "output_token_details": {"reasoning": 4096}})
        gateway, _, events = self.gateway(response)
        with self.assertRaisesRegex(ValueError, "截断"):
            gateway.ask(DialogueReply, "请回复", {}, "dialogue")
        diagnostic = events[-1][1]
        self.assertTrue(diagnostic["reasoning_present"])
        self.assertEqual(diagnostic["usage"]["output_token_details"]["reasoning"], 4096)
        self.assertNotIn("不应写入日志", json.dumps(events, ensure_ascii=False))

    def test_string_and_text_content_blocks_are_preserved(self):
        gateway, _, _ = self.gateway(AIMessage(content=['{"answer":', {"type": "text", "text": '"你好"}'}]))
        result = gateway.ask(DialogueReply, "请回复", {}, "dialogue")
        self.assertEqual(result.answer, "你好")

    def test_sdk_length_exception_is_logged_with_reasoning_usage(self):
        from openai import LengthFinishReasonError
        from openai.types.chat import ChatCompletion
        completion = ChatCompletion.model_validate({
            "id": "test-completion", "object": "chat.completion", "created": 0,
            "model": "test-model", "choices": [{"index": 0, "finish_reason": "length",
                "message": {"role": "assistant", "content": "", "reasoning_content": "不保存的隐藏推理"}}],
            "usage": {"prompt_tokens": 4043, "completion_tokens": 4096, "total_tokens": 8139,
                      "completion_tokens_details": {"reasoning_tokens": 4094}},
        })
        gateway, stub, events = self.gateway(LengthFinishReasonError(completion=completion))
        with self.assertRaisesRegex(ValueError, "4094"):
            gateway.ask(DialogueReply, "提取记忆", {}, "memory_formation")
        self.assertEqual(stub.calls, 1)
        self.assertEqual(events[-1][0], "model_failed")
        self.assertEqual(events[-1][1]["finish_reason"], "length")
        self.assertNotIn("不保存的隐藏推理", json.dumps(events, ensure_ascii=False))

    def test_explicit_budget_and_reasoning_effort_are_forwarded(self):
        with patch.dict(os.environ, {"LLM_MODEL": "glm-5.3", "LLM_API_KEY": "not-a-real-key",
                                     "LLM_MAX_TOKENS": "16384", "LLM_REASONING_EFFORT": "low"}):
            with patch("langchain_openai.ChatOpenAI") as constructor:
                gateway = ModelGateway()
        self.assertEqual(gateway.max_tokens, 16384)
        self.assertEqual(constructor.call_args.kwargs["max_tokens"], 16384)
        self.assertEqual(constructor.call_args.kwargs["reasoning_effort"], "low")


if __name__ == "__main__":
    unittest.main()
