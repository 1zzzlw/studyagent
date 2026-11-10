"""每轮检查积累量；触发时一次归纳，用临时引用号映射真实证据。"""
from datetime import timedelta
from uuid import uuid4

from .models import ConceptNode, Insights, eligible


MIN_NEW_EVENTS = 3
IMPORTANCE_THRESHOLD = 15
MAX_EVIDENCE = 12


def reflect(runtime, source_ids, report=print, new_ids=()):
    nodes = runtime.store.nodes
    # 只用未处理的新对话事件触发；种子和 thought 不增加触发量。
    pending = sorted((node for node in nodes.values()
                      if node.type == "event" and node.origin == "dialogue" and not node.reflected
                      and eligible(node, nodes, runtime.now)), key=lambda node: node.node_count)[:MAX_EVIDENCE]
    importance = round(sum(node.poignancy for node in pending), 2)
    summary = {"status": "skipped", "pending_events": len(pending), "importance": importance,
               "event_threshold": MIN_NEW_EVENTS, "importance_threshold": IMPORTANCE_THRESHOLD,
               "saved_ids": [], "rejected": []}
    runtime.reflection_summary = summary
    observations = {node.source_observation_id or node.node_id for node in pending}
    if not new_ids:
        reason = "本轮没有新增事件"
    elif len(pending) < 2 or len(observations) < 2:
        reason = "至少需要两次不同观察中的新事件"
    elif len(pending) < MIN_NEW_EVENTS and importance < IMPORTANCE_THRESHOLD:
        reason = f"继续积累：新事件 {len(pending)}/{MIN_NEW_EVENTS}，重要性 {importance:g}/{IMPORTANCE_THRESHOLD}"
    else:
        reason = ""
    if reason:
        summary["reason"] = reason
        report(f"反思跳过：{reason}，未调用模型")
        return 0

    # 新事件优先，补入本轮已检索的相关旧记忆；不用再生成焦点问题、逐题向量检索。
    batch = {node.node_id: node for node in pending}
    for key in source_ids:
        node = nodes.get(key)
        if node and node.type != "chat" and eligible(node, nodes, runtime.now):
            batch.setdefault(key, node)
    evidence = {f"M{index}": node for index, node in enumerate(list(batch.values())[:MAX_EVIDENCE], 1)}
    pending_ids = {node.node_id for node in pending}
    summary.update(status="running", evidence_map={ref: node.node_id for ref, node in evidence.items()})
    report(f"反思：积累已达条件，一次归纳 {len(evidence)} 条资料，等待文字模型")
    result = runtime.gateway.ask(
        Insights,
        "根据候选资料形成最多三条有价值的新认识，可以返回空 thoughts。"
        "不必先生成问题；不要仅复述姓名、单个偏好，也不要强行把无关事件建立联系。"
        "每条认识至少引用两个不同的 ref，且至少一个来自 new_event=true 的新事件。"
        "evidence_refs 只能填写候选资料的 ref，例如 M1、M2；不填写原始记忆 ID 或来源 ID。"
        "保留人物、条件和不确定性，推测必须明确是可能性，不把邀请、计划当成已经发生的事。"
        "不推断未提供的隐私或动机。不重复已有认识。poignancy 是重要性，范围1到10。",
        {"候选资料": [{"ref": ref, "type": node.type, "description": node.description[:1600],
                       "formed_at": node.created.isoformat(), "new_event": node.node_id in pending_ids}
                      for ref, node in evidence.items()],
         "已有认识": [node.description[:800] for node in sorted(nodes.values(), key=lambda node: node.node_count, reverse=True)
                    if node.type == "thought" and eligible(node, nodes, runtime.now)][:5]},
        "归纳新认识并引用资料编号；没有值得保存的新认识就返回空列表",
    )
    summary["model_output"] = result.model_dump(mode="json")
    for thought in result.thoughts:
        refs = list(dict.fromkeys(ref.strip() for ref in thought.evidence_refs))
        invalid = [ref for ref in refs if ref not in evidence]
        if invalid or len(refs) < 2:
            reason = f"存在无效引用 {invalid}" if invalid else "不同的有效引用不足两条"
        elif not any(evidence[ref].node_id in pending_ids for ref in refs):
            reason = "未引用待反思的新事件"
        else:
            reason = ""
        if reason:
            summary["rejected"].append({"description": thought.description, "refs": refs, "reason": reason})
            report(f"反思：跳过一条认识：{reason}；原始引用 {refs}")
            continue
        ids = [evidence[ref].node_id for ref in refs]
        if any(node.type == "thought" and node.description == thought.description
               and set(node.filling) == set(ids) for node in runtime.store.nodes.values()):
            continue
        node = ConceptNode(
            node_id=f"thought_{uuid4().hex}", **runtime.store.next_fields("thought"),
            type="thought", description=thought.description, keywords=thought.keywords,
            created=runtime.now, last_accessed=runtime.now,
            expiration=runtime.now + timedelta(days=30),
            depth=1 + max(evidence[ref].depth for ref in refs), filling=ids,
            subject=runtime.assistant_name, predicate="认为", object="基于经历形成的认识",
            poignancy=thought.poignancy, origin="reflection", reflected=True,
            source_observation_id="reflection",
        )
        runtime.engine.register(node)
        runtime.store.add([node])
        summary["saved_ids"].append(node.node_id)
        report(f"反思：已保存第 {len(summary['saved_ids'])} 条新认识")
        runtime.enrich(node)
    # 有引用错误则保留待处理事件；下一次出现新事件时再尝试，不在本轮额外请求重试。
    if not summary["rejected"]:
        for node in pending:
            runtime.store.patch(node.node_id, reflected=True)
    summary["status"] = "complete_with_rejections" if summary["rejected"] else "complete"
    report(f"反思完成：新增认识 {len(summary['saved_ids'])} 条，跳过无效认识 {len(summary['rejected'])} 条")
    return len(summary["saved_ids"])
