const versions = ["v1", "v2", "v3"];
const titles = {v1: "GA · 来源与反思证据", v2: "纯 A-Mem · 笔记关联", v3: "GA + A-Mem · 关联与证据"};
const relationNames = {evidence: "来源 / 证据", link: "语义关联", supersedes: "纠正旧认识"};
const $ = id => document.getElementById(id);
const records = {}, boards = {}, selected = {};
const params = new URLSearchParams(location.search);
let inspected = versions.includes(params.get("version")) ? params.get("version") : "v1";
let reading = false, detailRequest = 0, listSignature = "";
selected[inspected] = params.get("node");

function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}
function svgElement(tag, attributes = {}, text) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text !== undefined) node.textContent = text;
    return node;
}
async function api(path) {
    const response = await fetch(`/api/${path}`);
    const type = response.headers.get("content-type") || "";
    if (!type.includes("application/json")) throw new Error(`接口未返回 JSON（HTTP ${response.status}）。请从 FastAPI 的网址打开页面，不要使用 IDE 的 63342 预览端口。`);
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail));
    return result;
}
function setView(version) {
    const {svg, view} = boards[version];
    svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
}
function fit(version) {
    const board = boards[version];
    board.view = {x: 0, y: 0, w: 1280, h: board.height || 360};
    setView(version);
}
function zoom(version, factor) {
    const view = boards[version].view;
    if (view.w * factor < 180 || view.w * factor > 6400) return;
    view.x += view.w * (1 - factor) / 2;
    view.y += view.h * (1 - factor) / 2;
    view.w *= factor;
    view.h *= factor;
    setView(version);
}
function focusSelected(version) {
    const board = boards[version], point = board.points?.get(selected[version]);
    if (!point) return;
    const bounds = board.svg.getBoundingClientRect();
    const width = 360, height = width * bounds.height / Math.max(1, bounds.width);
    board.view = {x: point.x - width / 2, y: point.y - height / 2, w: width, h: height};
    setView(version);
}
function updateScope() {
    const scope = $("graph-mode").value;
    $("graph-cards").classList.toggle("single", scope !== "all");
    for (const version of versions) boards[version].card.hidden = scope !== "all" && scope !== version;
    if (scope !== "all") inspected = scope;
    renderInspector();
    if (records[inspected]) loadDetail();
}
function selectNode(version, id, scroll = false) {
    inspected = version;
    selected[version] = id;
    for (const item of versions) draw(item);
    renderInspector();
    loadDetail();
    if (scroll && matchMedia("(max-width: 950px)").matches) $("graph-memory-detail").scrollIntoView({block: "start"});
}

for (const version of versions) {
    const card = element("article", "graph-card");
    const header = element("header", "graph-card-head");
    const stats = element("p", "", "正在加载……");
    header.append(element("h2", "", `${version} · ${titles[version]}`), stats);
    const actions = element("div", "graph-actions");
    for (const [text, label, action] of [
        ["+", "放大关系图", () => zoom(version, .75)],
        ["−", "缩小关系图", () => zoom(version, 1.33)],
        ["适应全部", "显示本图全部节点", () => fit(version)],
        ["定位选中", "放大定位选中的记忆", () => focusSelected(version)],
    ]) {
        const button = element("button", "", text);
        button.type = "button";
        button.setAttribute("aria-label", label);
        button.addEventListener("click", action);
        actions.append(button);
    }
    const svg = svgElement("svg", {class: "graph-canvas", role: "group", tabindex: "0", "aria-label": `${version} 记忆关系图。方向键移动，使用放大缩小按钮调整视野，也可从下方列表选择节点。`});
    card.append(header, actions, svg);
    $("graph-cards").append(card);
    const board = boards[version] = {card, stats, svg, view: {x: 0, y: 0, w: 1280, h: 360}, signature: "", points: new Map()};
    setView(version);
    let drag = null;
    svg.addEventListener("pointerdown", event => {
        if (!event.isPrimary || event.button !== 0) return;
        drag = {pointer: event.pointerId, x: event.clientX, y: event.clientY, view: {...board.view}, node: event.target.closest("[data-node]")?.getAttribute("data-node"), moved: false};
        svg.setPointerCapture(event.pointerId);
    });
    svg.addEventListener("pointermove", event => {
        if (!drag || drag.pointer !== event.pointerId) return;
        const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
        if (Math.hypot(dx, dy) < 5 && !drag.moved) return;
        drag.moved = true;
        const matrix = svg.getScreenCTM();
        if (!matrix) return;
        board.view.x = drag.view.x - dx / matrix.a;
        board.view.y = drag.view.y - dy / matrix.d;
        setView(version);
    });
    svg.addEventListener("pointerup", event => {
        if (!drag || drag.pointer !== event.pointerId) return;
        const clicked = !drag.moved && drag.node;
        drag = null;
        if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
        if (clicked) selectNode(version, clicked, true);
    });
    svg.addEventListener("pointercancel", () => { drag = null; });
    svg.addEventListener("wheel", event => { event.preventDefault(); zoom(version, event.deltaY > 0 ? 1.15 : .87); }, {passive: false});
    svg.addEventListener("keydown", event => {
        const offsets = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]};
        if (!offsets[event.key]) return;
        event.preventDefault();
        board.view.x += offsets[event.key][0] * board.view.w * .12;
        board.view.y += offsets[event.key][1] * board.view.h * .12;
        setView(version);
    });
}

function draw(version) {
    const state = records[version], board = boards[version];
    if (!state) return;
    const focus = selected[version];
    const nearby = new Set([focus]);
    if ($("neighborhood").checked && focus) {
        for (const edge of state.edges) if (edge.source === focus || edge.target === focus) {
            nearby.add(edge.source); nearby.add(edge.target);
        }
    }
    const nodes = $("neighborhood").checked && focus ? state.nodes.filter(node => nearby.has(node.id)) : state.nodes;
    const ids = new Set(nodes.map(node => node.id));
    const edges = state.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target));
    const query = $("graph-search").value.toLowerCase().trim();
    const signature = JSON.stringify([nodes, edges, focus, query]);
    board.stats.textContent = `显示 ${nodes.length}/${state.nodes.length} 个节点 · ${edges.length}/${state.edges.length} 条关系 · ${state.activity ? `同步处理中：${state.processing.stage}` : "空闲"}`;
    if (signature === board.signature) return;
    board.signature = signature;
    const svg = board.svg;
    svg.replaceChildren();
    board.points = new Map();
    const groups = version === "v2"
        ? [0, 1, 2].map(column => nodes.filter((node, index) => index % 3 === column))
        : ["chat", "event", "thought"].map(type => nodes.filter(node => node.type === type));
    board.height = Math.max(360, Math.max(...groups.map(group => group.length)) * 76 + 130);
    if (!board.initialized) { fit(version); board.initialized = nodes.length > 0; }
    const defs = svgElement("defs");
    for (const [kind, color] of [["evidence", "#486aa1"], ["supersedes", "#af5528"], ["link", "#08766b"]]) {
        const marker = svgElement("marker", {id: `${version}-${kind}`, viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse"});
        marker.append(svgElement("path", {d: "M 0 0 L 10 5 L 0 10 z", fill: color}));
        defs.append(marker);
    }
    svg.append(defs);
    groups.forEach((group, column) => {
        const x = 200 + column * 400;
        svg.append(svgElement("text", {x, y: 35, "text-anchor": "middle", class: "graph-column-label"}, version === "v2" ? `A-Mem 笔记 · ${column + 1}` : ["原话 chat", "事件 event", "认识 thought"][column]));
        group.forEach((node, index) => board.points.set(node.id, {x, y: 86 + index * 76}));
    });
    for (const edge of edges) {
        const a = board.points.get(edge.source), b = board.points.get(edge.target);
        const direction = Math.sign(b.x - a.x);
        const ax = a.x + (direction || 1) * 114, bx = b.x - (direction || -1) * 114;
        const mid = direction ? (ax + bx) / 2 : ax + Math.min(140, 50 + Math.abs(a.y - b.y) * .1);
        const path = svgElement("path", {d: `M ${ax} ${a.y} C ${mid} ${a.y}, ${mid} ${b.y}, ${bx} ${b.y}`, class: `graph-edge ${edge.type}${edge.source === focus || edge.target === focus ? " highlight" : ""}`});
        if (edge.type !== "link" || edge.directed) path.setAttribute("marker-end", `url(#${version}-${edge.type})`);
        path.append(svgElement("title", {}, `${relationNames[edge.type]}：${edge.source} → ${edge.target}`));
        svg.append(path);
    }
    for (const node of nodes) {
        const point = board.points.get(node.id);
        const match = query && `${node.description} ${node.id}`.toLowerCase().includes(query);
        const meta = node.type === "note" ? `检索访问 ${node.retrieval_count} 次 · note` : `强度 ${node.strength.toFixed(3)} · 回忆 ${node.recall_count} 次 · ${node.type}`;
        const group = svgElement("g", {class: `graph-node ${node.type}${node.id === focus || match ? " selected" : ""}${node.status === "superseded" ? " superseded" : ""}`, transform: `translate(${point.x}, ${point.y})`, tabindex: "0", role: "button", "aria-label": `${node.type}：${node.description}，${meta}。点选查看全部字段。`, "data-node": node.id});
        group.append(svgElement("title", {}, `${node.id}\n${node.description}`), svgElement("rect", {x: -110, y: -26, width: 220, height: 52, rx: 7}),
            svgElement("text", {x: 0, y: -3, "text-anchor": "middle"}, [...node.description.replace(/\s+/g, " ")].slice(0, 14).join("") + ([...node.description].length > 14 ? "…" : "")),
            svgElement("text", {x: 0, y: 15, "text-anchor": "middle", class: "node-meta"}, meta));
        group.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectNode(version, node.id, true); }
        });
        svg.append(group);
    }
    if (!nodes.length) svg.append(svgElement("text", {x: 640, y: 180, "text-anchor": "middle", class: "graph-empty"}, "尚无记忆，请先到聊天页交流。"));
    setView(version);
}

function renderInspector() {
    for (const button of $("graph-tabs").children) button.setAttribute("aria-pressed", String(button.dataset.version === inspected));
    const state = records[inspected];
    if (!state) return;
    $("graph-count").textContent = state.nodes.length;
    $("relation-summary").textContent = inspected === "v2"
        ? `v2：A-Mem 笔记 ${state.nodes.length} 条，有向语义关联 ${state.edges.length} 条。所有笔记保留，可筛选或点选。`
        : `${inspected}：来源/证据 ${state.edges.filter(edge => edge.type === "evidence").length} 条，语义关联 ${state.edges.filter(edge => edge.type === "link").length} 条，纠正 ${state.edges.filter(edge => edge.type === "supersedes").length} 条。所有节点保留，可筛选或点选。`;
    const query = $("graph-search").value.toLowerCase().trim(), type = $("node-type").value;
    const nodes = state.nodes.filter(node => (type === "all" || node.type === type) && `${node.description} ${node.id}`.toLowerCase().includes(query));
    const key = JSON.stringify([inspected, nodes, selected[inspected]]);
    const list = $("graph-node-list");
    if (key !== listSignature) {
        listSignature = key;
        const scroll = list.scrollTop;
        list.replaceChildren();
        for (const node of nodes) {
            const button = element("button", `memory-item${node.id === selected[inspected] ? " selected" : ""}`);
            button.type = "button";
            button.append(element("span", "type-chip", node.type), element("small", "", node.type === "note" ? `检索访问 ${node.retrieval_count} 次` : `强度 ${node.strength.toFixed(3)} · 回忆 ${node.recall_count} 次`), element("p", "", node.description));
            const version = inspected;
            button.addEventListener("click", () => { selectNode(version, node.id, true); focusSelected(version); });
            list.append(button);
        }
        if (!nodes.length) list.append(element("p", "empty-detail", "暂无符合条件的节点。"));
        list.scrollTop = scroll;
    }
    const id = selected[inspected];
    const incidents = id ? state.edges.filter(edge => edge.source === id || edge.target === id) : [];
    $("incident-panel").hidden = !id;
    const relations = $("incident-list");
    relations.replaceChildren();
    const byId = new Map(state.nodes.map(node => [node.id, node]));
    for (const edge of incidents) {
        const other = edge.source === id ? edge.target : edge.source;
        const row = element("div", "incident");
        const direction = edge.type === "link" && !edge.directed ? "语义相关（图中不区分方向）" : edge.source === id ? "出边：本记忆指向对方" : "入边：对方指向本记忆";
        const version = inspected;
        row.append(element("h3", "", relationNames[edge.type]), element("p", "", direction), MemoryDetail.ref(other, linked => selectNode(version, linked, true)), element("p", "", byId.get(other)?.description || "对应记录不在当前库中"));
        relations.append(row);
    }
    if (id && !incidents.length) relations.append(element("p", "empty-detail", "这条记忆目前没有入边或出边。"));
}

async function loadDetail() {
    const version = inspected, id = selected[version], request = ++detailRequest;
    if (!id) {
        const area = $("graph-memory-detail");
        delete area.dataset.record;
        area.replaceChildren(element("p", "empty-detail", "点选节点，查看完整记忆和关联。"));
        return;
    }
    try {
        const detail = await api(`${version}/memories/${encodeURIComponent(id)}`);
        if (request !== detailRequest) return;
        MemoryDetail.render($("graph-memory-detail"), detail, version, linked => selectNode(version, linked, true));
    } catch (error) {
        if (request === detailRequest) {
            delete $("graph-memory-detail").dataset.record;
            $("graph-memory-detail").replaceChildren(element("p", "error", error.message));
        }
    }
}
async function refresh() {
    if (reading) return;
    reading = true;
    try {
        const failures = [];
        await Promise.all(versions.map(async version => {
            try { records[version] = await api(`${version}/graph`); draw(version); }
            catch (error) { failures.push(`${version}：${error.message}`); boards[version].stats.textContent = error.message; }
        }));
        $("graph-notice").textContent = failures.join("\n");
        renderInspector();
        await loadDetail();
    } finally { reading = false; }
}

$("graph-mode").value = params.has("version") || matchMedia("(max-width: 950px)").matches ? inspected : "all";
$("graph-mode").addEventListener("change", updateScope);
$("graph-search").addEventListener("input", () => { for (const version of versions) draw(version); renderInspector(); });
$("node-type").addEventListener("change", renderInspector);
$("neighborhood").addEventListener("change", () => { for (const version of versions) { draw(version); fit(version); } });
$("refresh-graph").addEventListener("click", refresh);
for (const button of $("graph-tabs").children) button.addEventListener("click", () => {
    inspected = button.dataset.version;
    if ($("graph-mode").value !== "all") {
        $("graph-mode").value = inspected;
        updateScope();
    } else {
        renderInspector(); loadDetail();
    }
});
updateScope();
if (location.protocol === "file:") {
    $("graph-notice").textContent = "当前为静态预览。请启动 web.py，通过 http://127.0.0.1:80 打开页面后查看真实记忆。";
    $("refresh-graph").disabled = true;
} else {
    (async function poll() { try { await refresh(); } finally { setTimeout(poll, 3000); } })();
}
