"""学习用的类型化状态边界。

这是对 WildAgent 下一阶段迁移思路的缩小实现，不是生产代码副本。
它刻意把领域对象、编译产物和 LangGraph 运输 State 分开。
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class MassingDecision(ContractModel):
    width: float = Field(gt=0, le=500)
    depth: float = Field(gt=0, le=500)
    floors: int = Field(ge=1, le=200)
    modeled_floors: int = Field(ge=1, le=200)
    floor_height: float = Field(gt=0.5, le=20)
    representation_mode: Literal["full", "schematic"] = "full"

    @model_validator(mode="after")
    def floor_representation_is_valid(self):
        if self.modeled_floors > self.floors:
            raise ValueError("modeled_floors 不能大于 floors")
        if self.representation_mode == "full" and self.modeled_floors != self.floors:
            raise ValueError("full 模式必须完整建模所有楼层")
        return self


OpeningKind = Literal["door", "window", "empty"]
Facing = Literal["front", "back", "left", "right"]


class FacadeDecision(ContractModel):
    bays: int = Field(ge=1, le=32)
    ground_pattern: list[OpeningKind]
    upper_pattern: list[OpeningKind]

    @model_validator(mode="after")
    def pattern_matches_bays(self):
        if len(self.ground_pattern) != self.bays:
            raise ValueError("ground_pattern 长度必须等于 bays")
        if len(self.upper_pattern) != self.bays:
            raise ValueError("upper_pattern 长度必须等于 bays")
        if "door" in self.upper_pattern:
            raise ValueError("upper_pattern 不能包含 door")
        return self


class ComponentQuota(ContractModel):
    min: int = Field(ge=0, le=10_000)
    max: int = Field(ge=0, le=10_000)

    @model_validator(mode="after")
    def maximum_is_not_below_minimum(self):
        if self.max < self.min:
            raise ValueError("quota.max 不能小于 quota.min")
        return self


class ArchitectureDecisions(ContractModel):
    massing: MassingDecision
    facades: dict[Facing, FacadeDecision]
    component_quota: dict[str, ComponentQuota]

    @model_validator(mode="after")
    def all_facades_are_present(self):
        required = {"front", "back", "left", "right"}
        if set(self.facades) != required:
            raise ValueError("facades 必须恰好包含 front/back/left/right")
        return self


class DesignDocument(ContractModel):
    schema_version: Literal["design/1.0"] = "design/1.0"
    design_id: str = Field(min_length=1, max_length=120)
    revision: int = Field(ge=1)
    status: Literal["draft", "approved", "compiled"] = "draft"
    decisions: ArchitectureDecisions


class FacadeSlot(ContractModel):
    id: str
    facing: Facing
    floor: int = Field(ge=1)
    bay: int = Field(ge=1)
    type: Literal["door", "window"]
    offset: float = Field(ge=0)
    width: float = Field(gt=0)
    bottom: float = Field(ge=0)
    height: float = Field(gt=0)


class GenerationSpec(ContractModel):
    schema_version: Literal["generation-spec/1.0"] = "generation-spec/1.0"
    design_id: str
    design_revision: int = Field(ge=1)
    design_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    bounds: dict[Literal["width", "depth", "height"], float]
    levels: list[dict[Literal["floor", "base_y", "top_y"], float | int]]
    facade_slots: list[FacadeSlot]
    component_quantities: dict[str, int]


class WorkflowState(TypedDict, total=False):
    """LangGraph 运输层：只保留可序列化的节点交接数据。"""

    request_id: str
    user_message: str
    design_document: dict[str, Any]
    design_review_status: str
    generation_spec: dict[str, Any]
    component_fragments: dict[str, list[dict[str, Any]]]


class DesignConflictError(ValueError):
    pass


def legacy_read_width(plan: dict[str, Any]) -> float | None:
    """演示旧 dict 读取：key 拼错时只得到 None。"""

    massing = plan.get("massing")
    if not isinstance(massing, dict):
        return None
    width = massing.get("width")
    return float(width) if isinstance(width, (int, float)) else None


def merge_component_fragments(
    left: dict[str, list[dict[str, Any]]] | None,
    right: dict[str, list[dict[str, Any]]] | None,
) -> dict[str, list[dict[str, Any]]]:
    """模拟当前按组件类型进行的顶层浅合并 Reducer。"""

    merged = dict(left or {})
    merged.update(right or {})
    return merged


def apply_state_update(state: WorkflowState, update: dict[str, Any]) -> WorkflowState:
    """模拟普通 LangGraph channel 将节点局部返回写入完整 State。"""

    merged: WorkflowState = dict(state)
    merged.update(update)
    return merged


def architecture_node_update(raw_document: dict[str, Any]) -> dict[str, Any]:
    """节点边界先校验领域对象，再只返回本节点拥有的字段。"""

    document = DesignDocument.model_validate(raw_document)
    data = document.model_dump(mode="json")
    data["status"] = "draft"
    document = DesignDocument.model_validate(data)
    return {
        "design_document": document.model_dump(mode="json"),
        "design_review_status": "pending",
    }


def approve_node_update(state: WorkflowState) -> dict[str, Any]:
    """审核节点只负责批准当前设计，不偷偷编译几何。"""

    document = DesignDocument.model_validate(state.get("design_document"))
    data = document.model_dump(mode="json")
    data["status"] = "approved"
    approved = DesignDocument.model_validate(data)
    return {
        "design_document": approved.model_dump(mode="json"),
        "design_review_status": "approved",
    }


def apply_width_patch(
    document: DesignDocument | dict[str, Any],
    *,
    base_revision: int,
    width: float,
) -> DesignDocument:
    """用 base_revision 防止旧修改覆盖新设计。"""

    current = (
        document
        if isinstance(document, DesignDocument)
        else DesignDocument.model_validate(document)
    )
    if current.revision != base_revision:
        raise DesignConflictError(
            f"设计版本冲突：当前 r{current.revision}，修改基于 r{base_revision}"
        )
    data = deepcopy(current.model_dump(mode="json"))
    data["revision"] = current.revision + 1
    data["status"] = "draft"
    data["decisions"]["massing"]["width"] = width
    return DesignDocument.model_validate(data)


def _stable_design_hash(document: DesignDocument) -> str:
    payload = {
        "schema_version": document.schema_version,
        "design_id": document.design_id,
        "revision": document.revision,
        "decisions": document.decisions.model_dump(mode="json"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(raw.encode("utf-8")).hexdigest()


def compile_generation_spec(
    document: DesignDocument | dict[str, Any],
) -> GenerationSpec:
    """把已批准设计确定性编译为所有下游节点共同消费的协议。"""

    doc = (
        document
        if isinstance(document, DesignDocument)
        else DesignDocument.model_validate(document)
    )
    if doc.status != "approved":
        raise ValueError("只有 approved 设计才能编译 GenerationSpec")

    massing = doc.decisions.massing
    levels = [
        {
            "floor": floor,
            "base_y": round((floor - 1) * massing.floor_height, 3),
            "top_y": round(floor * massing.floor_height, 3),
        }
        for floor in range(1, massing.modeled_floors + 1)
    ]
    slots: list[FacadeSlot] = []
    for facing, facade in doc.decisions.facades.items():
        span = massing.width if facing in {"front", "back"} else massing.depth
        bay_width = span / facade.bays
        for level in levels:
            floor = int(level["floor"])
            pattern = facade.ground_pattern if floor == 1 else facade.upper_pattern
            for bay, opening_type in enumerate(pattern, start=1):
                if opening_type == "empty":
                    continue
                opening_width = round(min(bay_width * 0.62, bay_width - 0.3), 3)
                bottom_in_floor = 0.0 if opening_type == "door" else 1.0
                opening_height = 2.4 if opening_type == "door" else 1.8
                slots.append(FacadeSlot(
                    id=f"{facing}:floor_{floor}:{opening_type}:{bay}",
                    facing=facing,
                    floor=floor,
                    bay=bay,
                    type=opening_type,
                    offset=round((bay - 0.5) * bay_width - opening_width / 2, 3),
                    width=opening_width,
                    bottom=round(float(level["base_y"]) + bottom_in_floor, 3),
                    height=opening_height,
                ))

    quantities = {
        "door": sum(slot.type == "door" for slot in slots),
        "window": sum(slot.type == "window" for slot in slots),
    }
    for component_type, quota in doc.decisions.component_quota.items():
        actual = quantities.get(component_type, 0)
        if actual < quota.min or actual > quota.max:
            raise ValueError(
                f"{component_type} 数量 {actual} 不在批准范围 {quota.min}..{quota.max}"
            )

    return GenerationSpec(
        design_id=doc.design_id,
        design_revision=doc.revision,
        design_hash=_stable_design_hash(doc),
        bounds={
            "width": massing.width,
            "depth": massing.depth,
            "height": round(massing.floors * massing.floor_height, 3),
        },
        levels=levels,
        facade_slots=slots,
        component_quantities=quantities,
    )


def compiler_node_update(state: WorkflowState) -> dict[str, Any]:
    """编译节点只写 generation_spec，不复制或修改其他 State 字段。"""

    document = DesignDocument.model_validate(state.get("design_document"))
    spec = compile_generation_spec(document)
    return {"generation_spec": spec.model_dump(mode="json")}

