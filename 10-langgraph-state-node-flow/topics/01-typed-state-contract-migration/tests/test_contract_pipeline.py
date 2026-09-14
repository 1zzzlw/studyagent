"""专题测试：用可执行行为理解类型化 State 边界与 GenerationSpec。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import TypedDict

from pydantic import ValidationError


TOPIC_ROOT = Path(__file__).resolve().parents[1]
if str(TOPIC_ROOT) not in sys.path:
    sys.path.insert(0, str(TOPIC_ROOT))

from contract_pipeline import (  # noqa: E402
    DesignConflictError,
    DesignDocument,
    WorkflowState,
    apply_state_update,
    apply_width_patch,
    approve_node_update,
    architecture_node_update,
    compiler_node_update,
    legacy_read_width,
    merge_component_fragments,
)


def sample_document(*, status: str = "draft") -> dict:
    return {
        "schema_version": "design/1.0",
        "design_id": "design_office_001",
        "revision": 1,
        "status": status,
        "decisions": {
            "massing": {
                "width": 20,
                "depth": 12,
                "floors": 3,
                "modeled_floors": 3,
                "floor_height": 3.6,
            },
            "facades": {
                "front": {
                    "bays": 3,
                    "ground_pattern": ["window", "door", "window"],
                    "upper_pattern": ["window", "window", "window"],
                },
                "back": {
                    "bays": 3,
                    "ground_pattern": ["window", "window", "window"],
                    "upper_pattern": ["window", "window", "window"],
                },
                "left": {
                    "bays": 2,
                    "ground_pattern": ["window", "window"],
                    "upper_pattern": ["window", "window"],
                },
                "right": {
                    "bays": 2,
                    "ground_pattern": ["window", "window"],
                    "upper_pattern": ["window", "window"],
                },
            },
            "component_quota": {
                "door": {"min": 1, "max": 2},
                "window": {"min": 20, "max": 40},
            },
        },
    }


class OldDictFailureTests(unittest.TestCase):
    def test_typo_is_silently_converted_to_missing_value(self):
        old_plan = {"masssing": {"width": 20}}

        self.assertIsNone(legacy_read_width(old_plan))

    def test_shallow_reducer_preserves_distinct_keys_but_overwrites_same_key(self):
        left = {
            "door": [{"id": "door_a"}],
            "window": [{"id": "window_a"}],
        }
        right = {"door": [{"id": "door_b"}]}

        merged = merge_component_fragments(left, right)

        self.assertEqual(merged["door"], [{"id": "door_b"}])
        self.assertEqual(merged["window"], [{"id": "window_a"}])


class RuntimeContractTests(unittest.TestCase):
    def test_contract_rejects_misspelled_massing(self):
        raw = sample_document()
        raw["decisions"]["masssing"] = raw["decisions"].pop("massing")

        with self.assertRaises(ValidationError):
            DesignDocument.model_validate(raw)

    def test_contract_rejects_facade_pattern_that_does_not_match_bays(self):
        raw = sample_document()
        raw["decisions"]["facades"]["front"]["upper_pattern"] = ["window"]

        with self.assertRaises(ValidationError):
            DesignDocument.model_validate(raw)

    def test_contract_rejects_full_mode_floor_mismatch(self):
        raw = sample_document()
        raw["decisions"]["massing"]["modeled_floors"] = 2

        with self.assertRaises(ValidationError):
            DesignDocument.model_validate(raw)


class NodeBoundaryTests(unittest.TestCase):
    def test_architecture_node_returns_only_owned_fields_and_json_safe_data(self):
        update = architecture_node_update(sample_document())

        self.assertEqual(
            set(update),
            {"design_document", "design_review_status"},
        )
        self.assertEqual(update["design_review_status"], "pending")
        json.dumps(update)

    def test_partial_update_preserves_unrelated_workflow_fields(self):
        state: WorkflowState = {
            "request_id": "req_001",
            "user_message": "生成三层玻璃幕墙写字楼",
        }

        merged = apply_state_update(
            state,
            architecture_node_update(sample_document()),
        )

        self.assertEqual(merged["request_id"], "req_001")
        self.assertEqual(merged["design_document"]["revision"], 1)


class CompilerContractTests(unittest.TestCase):
    def test_compiler_rejects_unapproved_design(self):
        state = apply_state_update(
            {"request_id": "req_001"},
            architecture_node_update(sample_document()),
        )

        with self.assertRaisesRegex(ValueError, "approved"):
            compiler_node_update(state)

    def test_approved_design_compiles_to_traceable_generation_spec(self):
        state = apply_state_update(
            {"request_id": "req_001"},
            architecture_node_update(sample_document()),
        )
        state = apply_state_update(state, approve_node_update(state))
        state = apply_state_update(state, compiler_node_update(state))
        spec = state["generation_spec"]

        self.assertEqual(spec["schema_version"], "generation-spec/1.0")
        self.assertEqual(spec["design_revision"], 1)
        self.assertTrue(spec["design_hash"].startswith("sha256:"))
        self.assertEqual(spec["bounds"]["width"], 20)
        self.assertEqual(spec["component_quantities"]["door"], 1)
        self.assertGreaterEqual(spec["component_quantities"]["window"], 20)
        self.assertEqual(state["request_id"], "req_001")
        json.dumps(state)

    def test_same_approved_revision_produces_same_hash(self):
        state = apply_state_update(
            {},
            architecture_node_update(sample_document()),
        )
        state = apply_state_update(state, approve_node_update(state))

        first = compiler_node_update(state)["generation_spec"]["design_hash"]
        second = compiler_node_update(state)["generation_spec"]["design_hash"]

        self.assertEqual(first, second)


class RevisionTests(unittest.TestCase):
    def test_patch_increments_revision_and_invalidates_approval(self):
        approved = DesignDocument.model_validate(sample_document(status="approved"))

        changed = apply_width_patch(approved, base_revision=1, width=24)

        self.assertEqual(changed.revision, 2)
        self.assertEqual(changed.status, "draft")
        self.assertEqual(changed.decisions.massing.width, 24)

    def test_stale_patch_is_rejected(self):
        current = DesignDocument.model_validate(sample_document())

        with self.assertRaises(DesignConflictError):
            apply_width_patch(current, base_revision=99, width=24)


try:
    from langgraph.graph import END, StateGraph

    LANGGRAPH_IMPORT_ERROR: BaseException | None = None
except (ImportError, OSError) as exc:
    END = None
    StateGraph = None
    LANGGRAPH_IMPORT_ERROR = exc


class LangGraphAdapterTests(unittest.TestCase):
    @unittest.skipIf(
        LANGGRAPH_IMPORT_ERROR is not None,
        f"当前主机无法导入 LangGraph: {LANGGRAPH_IMPORT_ERROR}",
    )
    def test_real_graph_merges_validated_partial_updates(self):
        class GraphState(WorkflowState, total=False):
            pass

        def architecture(state: GraphState) -> dict:
            return architecture_node_update(state["design_document"])

        builder = StateGraph(GraphState)
        builder.add_node("architecture", architecture)
        builder.add_node("approve", approve_node_update)
        builder.add_node("compile", compiler_node_update)
        builder.set_entry_point("architecture")
        builder.add_edge("architecture", "approve")
        builder.add_edge("approve", "compile")
        builder.add_edge("compile", END)
        graph = builder.compile()

        result = graph.invoke({
            "request_id": "req_graph",
            "design_document": sample_document(),
        })

        self.assertEqual(result["request_id"], "req_graph")
        self.assertEqual(result["design_review_status"], "approved")
        self.assertEqual(result["generation_spec"]["design_revision"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

