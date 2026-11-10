const versions = ["v1", "v2", "v3"];
const descriptions = {
    v1: ["GA 检索与反思", "event / thought / chat · 衰减强化"],
    v2: ["纯 A-Mem", "记忆笔记 · 语义分析 · 关联演化"],
    v3: ["GA + A-Mem", "反思与关联结合 · 衰减强化"]
};
const $ = (id) => document.getElementById(id);
const previewOnly = location.protocol === "file:";
const data = {}, errors = {}, requestErrors = {}, inflight = {}, cards = {}, signatures = {}, selected = {};
let inspected = "v1", detailKey = "", polling = false;
let listKey = "", mobileVersion = "v1";
const compactLayout = matchMedia("(max-width: 950px)");

function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

async function api(path, body) {
    const response = await fetch(`/api/${path}`, body === undefined ? {} : {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
    });
    if (!(response.headers.get("content-type") || "").includes("application/json")) {
        throw new Error(`接口未返回 JSON（HTTP ${response.status}）。请通过 FastAPI 的网址打开页面，不要使用 IDE 的 63342 预览端口。`);
    }
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail));
    return result;
}

function targets() {
    return $("mode").value === "all" ? versions : [$("mode").value];
}

function notice(message = "") {
    $("notice").textContent = message;
}

function shortId(id) {
    return id.length > 22 ? `${id.slice(0, 8)}…${id.slice(-6)}` : id;
}

function ref(id, version) {
    const button = element("button", "memory-ref", shortId(id));
    button.type = "button";
    button.title = id;
    button.addEventListener("click", () => inspect(version, id));
    return button;
}

for (const version of versions) {
    const card = $("chat-template").content.firstElementChild.cloneNode(true);
    card.dataset.version = version;
    card.querySelector(".version-tag").textContent = version;
    card.querySelector("h2").textContent = descriptions[version][0];
    card.querySelector(".version-description").textContent = descriptions[version][1];
    card.querySelector(".messages").setAttribute("aria-label", `${version} 聊天记录`);
    cards[version] = card;
    $("chats").append(card);
}

function controls() {
    const busy = previewOnly || targets().some((version) => inflight[version] || data[version]?.activity);
    for (const id of ["send", "elapse", "reset"]) $(id).disabled = busy;
    $("send").firstChild.textContent = $("mode").value === "all" ? "发送给三版 " : `发送给 ${$("mode").value} `;
}

function message(role, text) {
    const block = element("div", `message ${role}`);
    block.append(element("div", "message-label", role === "user" ? "你" : "小忆"), element("div", "message-text", text));
    return block;
}

function renderChat(version) {
    const state = data[version], card = cards[version], area = card.querySelector(".messages");
    const errorMessage = requestErrors[version] || errors[version];
    card.querySelector(".card-stage").textContent = errorMessage ? "连接或操作失败" : state?.activity ? state.processing.stage : "准备好了";
    card.querySelector(".card-counts").textContent = state ? `${version === "v2" ? `笔记 ${state.counts.note}` : `事件 ${state.counts.event} · 认识 ${state.counts.thought} · 原话 ${state.counts.chat}`} · 已流逝 ${state.elapsed_days} 天` : "正在读取本版数据";
    const signature = JSON.stringify([state?.turns, state?.current_query, inflight[version], errorMessage]);
    if (signature === signatures[version]) return;
    signatures[version] = signature;
    const pinned = area.scrollHeight - area.scrollTop - area.clientHeight < 65;
    const scrollTop = area.scrollTop;
    area.replaceChildren();
    for (const turn of state?.turns || []) {
        area.append(message("user", turn.query));
        const answer = message("assistant", turn.reply.answer);
        const meta = element("div", "reply-meta");
        const outcomes = {answered: "普通回答", recalled: "采用了记忆", uncertain: "不确定", not_recalled: "没有想起"};
        const stage = {
            dialogue_processing: "同步处理记忆中",
            dialogue_complete: "本轮已完成",
            post_answer_failed: "记忆处理未完成",
            read_only_complete: "只读提问"
        };
        meta.append(element("span", "", `${outcomes[turn.reply.outcome]} · ${stage[turn.stage] || turn.stage}`));
        for (const id of new Set(turn.reply.used_memory_ids)) meta.append(ref(id, version));
        answer.append(meta);
        if (turn.retrieved?.length) {
            const details = element("details", "retrieved");
            details.append(element("summary", "", `查看本轮检索的 ${turn.retrieved.length} 条记忆`));
            const refs = element("div");
            for (const item of turn.retrieved) {
                const button = ref(item.node_id || item.id, version);
                button.title += `\n检索路径：${item.reason}\n评分：${item.score == null ? "关联扩展，无独立查询分数" : item.score.toFixed(3)}`;
                refs.append(button);
            }
            details.append(refs);
            answer.append(details);
        }
        if (turn.reflection) {
            const result = turn.reflection;
            const labels = {skipped: "未触发", complete: "已完成", complete_with_rejections: "部分引用未通过", failed: "失败", not_started: "尚未开始"};
            const details = element("details", "retrieved");
            details.append(element("summary", "", `反思：${labels[result.status] || result.status} · 新增 ${result.saved_ids?.length || 0} 条认识`));
            if (result.reason) details.append(element("p", "", result.reason));
            if (result.pending_events !== undefined) details.append(element("p", "muted", `待反思事件 ${result.pending_events} 条 · 重要性合计 ${result.importance}`));
            const refs = element("div");
            for (const id of result.saved_ids || []) refs.append(ref(id, version));
            details.append(refs);
            for (const item of result.rejected || []) details.append(element("p", "error", `${item.reason}：${item.refs.join("、")}\n${item.description}`));
            const raw = element("details");
            raw.append(element("summary", "", "引用映射与模型输出"), element("pre", "", JSON.stringify(result, null, 2)));
            details.append(raw);
            answer.append(details);
        }
        area.append(answer);
    }
    const pendingQuery = state?.current_query || inflight[version]?.message;
    // 轮询可能比 POST 的响应先读到正式记录；此时不再显示临时气泡。
    const latest = state?.turns?.at(-1);
    const alreadyRecorded = (inflight[version]?.message && (state?.turns?.length || 0) > inflight[version].previousTurns)
        || (state?.activity && latest?.stage === "dialogue_processing" && latest.query === state.current_query);
    if (pendingQuery && !alreadyRecorded) area.append(message("user", pendingQuery), element("p", "muted", "正在检索并生成回答……"));
    if (!(state?.turns?.length) && !pendingQuery) {
        const welcome = element("div", "welcome");
        welcome.append(element("strong", "", "从一句真实的聊天开始"), element("p", "", "这里没有预置记忆。\n整轮同步处理时，右侧会更新记忆和进度。"));
        area.append(welcome);
    }
    if (errorMessage) area.append(element("p", "error", errorMessage));
    area.scrollTop = pinned ? area.scrollHeight : scrollTop;
}

function inspect(version, id) {
    inspected = version;
    if (id) {
        selected[version] = id;
        $("search").value = "";
        $("type").value = "all";
    }
    detailKey = "";
    for (const button of $("version-tabs").children) button.setAttribute("aria-pressed", String(button.dataset.version === version));
    renderInspector();
}

function renderInspector() {
    const state = data[inspected];
    if (!state) {
        $("process-stage").textContent = errors[inspected] || "正在读取本版数据……";
        return;
    }
    const processing = state.processing;
    $("memory-count").textContent = state.memories.length;
    $("process-count").textContent = `文字模型 ${state.model_calls} 次`;
    $("process-stage").textContent = state.activity ? `${processing.stage} · 本轮已运行 ${processing.seconds} 秒` : "空闲 · 本轮同步处理完成后可继续对话";
    if (processing.last_error) $("process-stage").textContent += `\n最近失败：${processing.last_error}`;
    $("experiment-time").textContent = `实验时间 ${new Date(state.now).toLocaleString()} · 已推进 ${state.elapsed_days} 天`;
    const logs = $("progress-log"), pinned = logs.scrollHeight - logs.scrollTop - logs.clientHeight < 30;
    logs.replaceChildren(...state.events.map((entry) => element("li", "", `${entry.time}  ${entry.message}`)));
    if (pinned) logs.scrollTop = logs.scrollHeight;
    const query = $("search").value.trim().toLowerCase(), type = $("type").value;
    const memories = state.memories.filter((item) => (type === "all" || type === item.type) && `${item.description} ${item.node_id}`.toLowerCase().includes(query));
    if (!selected[inspected] && memories.length) selected[inspected] = memories[0].node_id;
    const list = $("memory-list");
    const nextListKey = JSON.stringify([inspected, query, type, memories, selected[inspected]]);
    if (listKey !== nextListKey) {
        listKey = nextListKey;
        const previousScroll = list.scrollTop;
        list.replaceChildren();
        for (const item of memories) {
            const button = element("button", `memory-item${item.node_id === selected[inspected] ? " selected" : ""}`);
            button.type = "button";
            const line = element("div");
            line.append(element("span", "type-chip", {
                event: "事件",
                thought: "认识",
                chat: "原话",
                note: "笔记"
            }[item.type]), element("small", "", item.type === "note" ? `检索访问 ${item.retrieval_count} 次` : `强度 ${item.current_strength.toFixed(3)} · 回忆 ${item.recall_count} 次`));
            button.append(line, element("p", "", item.description));
            button.addEventListener("click", () => inspect(inspected, item.node_id));
            list.append(button);
        }
        if (!memories.length) list.append(element("p", "empty-detail", state.memories.length ? "没有符合筛选的记忆。" : "还没有记忆，先聊几句吧。"));
        list.scrollTop = previousScroll;
    }
    const selectedMemory = state.memories.find((item) => item.node_id === selected[inspected]);
    if (!selectedMemory) {
        selected[inspected] = null;
        detailKey = "";
        delete $("memory-detail").dataset.record;
        $("memory-detail").replaceChildren(element("p", "empty-detail", "点选记忆，查看完整存储结构和关联。"));
        return;
    }
    const key = `${inspected}:${JSON.stringify(selectedMemory)}:${state.model_calls}:${state.events.length}:${processing.stage}`;
    if (key !== detailKey) {
        detailKey = key;
        loadDetail(inspected, selectedMemory.node_id, key);
    }
}

async function loadDetail(version, id, key) {
    try {
        const result = await api(`${version}/memories/${encodeURIComponent(id)}`);
        if (detailKey !== key || inspected !== version) return;
        MemoryDetail.render($("memory-detail"), result, version, linked => inspect(version, linked), {graphLink: true});
    } catch (error) {
        if (detailKey === key) {
            delete $("memory-detail").dataset.record;
            $("memory-detail").replaceChildren(element("p", "error", error.message));
        }
    }
}

async function refresh() {
    if (polling) return;
    polling = true;
    await Promise.all(versions.map(async (version) => {
        try {
            data[version] = await api(`${version}/state`);
            delete errors[version];
        } catch (error) {
            errors[version] = error.message;
        }
        renderChat(version);
    }));
    renderInspector();
    controls();
    polling = false;
}

async function operate(action, body = {}) {
    const scope = targets();
    notice("");
    const results = await Promise.all(scope.map(async (version) => {
        inflight[version] = body.message ? {
            message: body.message,
            previousTurns: data[version]?.turns?.length || 0
        } : {};
        delete requestErrors[version];
        controls();
        renderChat(version);
        try {
            await api(`${version}/${action}`, body);
            return true;
        } catch (error) {
            requestErrors[version] = error.message;
            notice(`${version}：${error.message}`);
            return false;
        } finally {
            delete inflight[version];
            renderChat(version);
            controls();
        }
    }));
    await refresh();
    return results.some(Boolean);
}

$("composer").addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = $("message").value.trim();
    if (!message || $("send").disabled) return;
    $("message").value = "";
    const accepted = await operate("chat", {message, read_only: $("readonly").checked});
    if (!accepted && !$("message").value) $("message").value = message;
    $("message").focus();
});
$("message").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        $("composer").requestSubmit();
    }
});
function updateChatVisibility() {
    const scope = targets();
    const tabbed = compactLayout.matches && scope.length > 1;
    $("mobile-view").hidden = !tabbed;
    $("chats").classList.toggle("single", scope.length === 1 || tabbed);
    for (const version of versions) cards[version].hidden = !scope.includes(version) || (tabbed && version !== mobileVersion);
    for (const button of $("mobile-view-tabs").children) button.setAttribute("aria-pressed", String(button.dataset.version === mobileVersion));
}
$("mode").addEventListener("change", () => {
    if ($("mode").value !== "all") {
        mobileVersion = $("mode").value;
        inspect(mobileVersion);
    }
    updateChatVisibility();
    controls();
});
for (const button of $("mobile-view-tabs").children) button.addEventListener("click", () => {
    mobileVersion = button.dataset.version;
    updateChatVisibility();
    inspect(mobileVersion);
});
compactLayout.addEventListener("change", updateChatVisibility);
updateChatVisibility();
for (const button of $("version-tabs").children) button.addEventListener("click", () => inspect(button.dataset.version));
$("search").addEventListener("input", renderInspector);
$("type").addEventListener("change", renderInspector);
$("elapse").addEventListener("click", () => {
    const days = Number($("days").value);
    if (!Number.isFinite(days) || days <= 0) {
        notice("请输入大于 0 的天数。");
        return;
    }
    operate("elapse", {days});
});
$("reset").addEventListener("click", () => {
    if (confirm(`清空 ${targets().join("、")} 的 Web 记忆和聊天？CLI 数据不受影响。`)) operate("reset");
});

async function poll() {
    try {
        await refresh();
    } finally {
        setTimeout(poll, 1000);
    }
}

if (previewOnly) {
    notice("当前仅预览页面样式。聊天和记忆功能请先运行 web.py，再打开 http://127.0.0.1:80。");
    for (const version of versions) {
        renderChat(version);
        cards[version].querySelector(".card-stage").textContent = "静态预览";
        cards[version].querySelector(".card-counts").textContent = "尚未连接 FastAPI 服务";
    }
    $("process-stage").textContent = "静态预览不读取服务端数据。";
    controls();
} else {
    poll();
}
