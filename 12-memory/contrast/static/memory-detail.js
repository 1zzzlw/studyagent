/* 聊天页和关联图共用完整字段展示；只读取，不修改记忆。 */
window.MemoryDetail = (() => {
    const labels = {
        id: "笔记 ID", timestamp: "形成时间", retrieval_count: "检索访问次数",
        node_id: "记忆 ID", node_count: "全局序号", type_count: "同类序号", type: "记忆类型",
        depth: "认识深度", created: "形成时间", last_accessed: "最后访问 / 回忆时间",
        expiration: "到期时间", subject: "主体", predicate: "动作 / 关系", object: "对象",
        description: "记忆正文", keywords: "关键词", poignancy: "重要性（1～10）",
        source_observation_id: "观察来源 ID", origin: "形成途径", attention: "留意程度（0～1）",
        emotional_impact: "情绪冲击（0～1）", initial_strength: "初始强度",
        strength_after_recall: "强化后的基准强度", stability_days: "稳定性（天）",
        recall_count: "成功回忆次数", status: "存储状态", context: "背景说明", tags: "标签",
        category: "分类", association_ready: "已整理语义关联", reflected: "已参与反思",
    };
    const groups = [
        ["笔记时间与访问统计", ["timestamp", "retrieval_count"]],
        ["强度与时间", ["initial_strength", "strength_after_recall", "stability_days", "recall_count", "created", "last_accessed", "expiration", "status"]],
        ["事实与来源", ["subject", "predicate", "object", "source_observation_id", "origin", "depth", "node_count", "type_count"]],
        ["记忆形成评价", ["attention", "emotional_impact", "poignancy"]],
        ["语义说明与维护状态", ["keywords", "context", "tags", "category", "association_ready", "reflected"]],
    ];
    function node(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;
        return element;
    }
    function value(key, item) {
        if (item === null || item === undefined || item === "") return "未设置";
        if (typeof item === "boolean") return item ? "是" : "否";
        if (Array.isArray(item)) return item.length ? item.join("、") : "空列表";
        if (["created", "timestamp", "last_accessed", "expiration"].includes(key)) return `${new Date(item).toLocaleString()}\n${item}`;
        return String(item);
    }
    function ref(id, onSelect) {
        const button = node("button", "memory-ref", id);
        button.type = "button";
        button.addEventListener("click", () => onSelect(id));
        return button;
    }
    function render(container, result, version, onSelect, {graphLink = false} = {}) {
        const signature = JSON.stringify([result, version]);
        if (container.dataset.record === signature) return;
        const wasOpen = container.querySelector(".raw-record")?.open || false;
        container.dataset.record = signature;
        const {stored, computed} = result;
        const isNote = version === "v2";
        container.replaceChildren(node("h3", "", isNote ? "A-Mem 笔记详情" : `记忆详情 · ${stored.type}`), node("span", "detail-id", stored.node_id || stored.id), node("p", "detail-body", stored.description || stored.content));
        if (!isNote) {
            const current = node("dl", "fields");
            current.append(node("dt", "", "当前计算强度"), node("dd", "", computed.current_strength.toFixed(5)),
                node("dt", "", "当前计算状态"), node("dd", "", computed.status),
                node("dt", "", "距形成天数"), node("dd", "", computed.age_days));
            container.append(current);
        }
        for (const [heading, keys] of groups) {
            const present = keys.filter(key => Object.hasOwn(stored, key));
            if (!present.length) continue;
            const fields = node("dl", "fields");
            for (const key of present) fields.append(node("dt", "", isNote && key === "last_accessed" ? "最后访问时间" : labels[key]), node("dd", "", value(key, stored[key])));
            container.append(node("h3", "detail-section", isNote && heading === "强度与时间" ? "访问时间" : heading), fields);
        }
        if (stored.type === "chat") {
            container.append(node("h3", "detail-section", "原始对话 filling"));
            for (const [speaker, text] of stored.filling) container.append(node("p", "detail-body", `${speaker}：${text}`));
        } else if (Object.hasOwn(stored, "filling")) {
            container.append(node("h3", "detail-section", "来源 / 证据 filling"));
            const sources = node("div", "relations");
            for (const id of stored.filling) sources.append(ref(id, onSelect));
            container.append(stored.filling.length ? sources : node("p", "muted", "没有来源链接"));
        }
        if (Object.hasOwn(stored, "links")) {
            container.append(node("h3", "detail-section", "语义关联 links"));
            const links = node("div", "relations");
            for (const id of stored.links) links.append(ref(id, onSelect));
            container.append(stored.links.length ? links : node("p", "muted", "尚未建立语义关联"));
        }
        if (Object.hasOwn(stored, "supersedes_id")) {
            container.append(node("h3", "detail-section", "纠正关系 supersedes_id"));
            container.append(stored.supersedes_id ? ref(stored.supersedes_id, onSelect) : node("p", "muted", "未纠正其他记忆"));
        }
        if (Object.hasOwn(stored, "evolution_history")) {
            container.append(node("h3", "detail-section", `关联维护记录 · ${stored.evolution_history.length} 次`));
            for (const entry of stored.evolution_history) container.append(node("pre", "", JSON.stringify(entry, null, 2)));
            if (!stored.evolution_history.length) container.append(node("p", "muted", "暂无维护记录"));
        }
        if (graphLink) {
            const link = node("a", "page-link", "在关联图中定位这条记忆 →");
            link.href = `./graph.html?${new URLSearchParams({version, node: stored.node_id || stored.id})}`;
            container.append(link);
        }
        const raw = node("details", "raw-record");
        raw.open = wasOpen;
        raw.append(node("summary", "", "全部原始存储字段"), node("pre", "", JSON.stringify(stored, null, 2)));
        container.append(raw);
    }
    return {render, ref};
})();
