"""A-Mem 检索：正文语义召回，再沿已有 links 补充一跳邻居。"""
from .models import Candidate


def retrieve(store, query, limit=8):
    if limit <= 0:
        return []
    # 预留最多三个位置给邻居，避免原项目先填满 k 条再截断时丢掉全部邻居。
    direct = store.search(query, limit=limit)
    result = list(direct[:max(1, limit - 3)])
    seen = {item.id for item in result}
    notes = store.nodes
    by_id = {item.id: item for item in direct}
    for parent in list(result):
        for key in notes[parent.id].links:
            if len(result) >= limit:
                break
            if key in seen or key not in notes:
                continue
            # 未直接命中的邻居没有查询相似分，不能把父节点分数当成它的分数。
            result.append(Candidate(id=key, score=by_id[key].score if key in by_id else None,
                                    reason=f"link:{parent.id}"))
            seen.add(key)
    for item in direct:
        if len(result) >= limit:
            break
        if item.id not in seen:
            result.append(item)
            seen.add(item.id)
    return result
