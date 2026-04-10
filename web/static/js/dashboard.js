const charts = {};
let refreshTimer = null;
let actionLoading = false;
let taskTimer = null;

const palette = {
    teal: "#0f766e",
    navy: "#1d4ed8",
    emerald: "#15803d",
    amber: "#b45309",
    rose: "#be185d",
    gold: "#a16207",
    plum: "#7c3aed",
    slate: "#475569",
    red: "#b91c1c",
    grid: "rgba(61, 71, 58, 0.12)",
};

function toNumber(value, fallback = 0) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : fallback;
}

function formatNumber(value, digits = 0) {
    return toNumber(value).toLocaleString("zh-CN", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    });
}

function formatPercent(value, digits = 2) {
    const numeric = toNumber(value);
    const sign = numeric > 0 ? "+" : "";
    return `${sign}${formatNumber(numeric, digits)}%`;
}

function signClass(value) {
    const numeric = toNumber(value);
    if (numeric > 0) return "text-positive";
    if (numeric < 0) return "text-negative";
    return "text-neutral";
}

function safeText(value, fallback = "--") {
    return value === null || value === undefined || value === "" ? fallback : value;
}

function activateStage(targetId) {
    if (!targetId) return;
    document.querySelectorAll("[data-stage-target]").forEach((item) => {
        item.classList.toggle("active", item.dataset.stageTarget === targetId);
    });
    document.querySelectorAll(".content-stage").forEach((section) => {
        section.classList.toggle("is-active", section.id === targetId);
    });
}

function formatTradeDateLabel(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    if (/^\d{8}$/.test(text)) {
        return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}收盘`;
    }
    return text;
}

function toneClass(value) {
    const numeric = toNumber(value);
    if (numeric > 0) return "tone-green";
    if (numeric < 0) return "tone-red";
    return "tone-slate";
}

function healthTone(status) {
    if (status === "healthy") return "tone-green";
    if (status === "degraded") return "tone-amber";
    if (status === "stale") return "tone-red";
    return "tone-slate";
}

function levelTone(label) {
    const text = String(label || "").toLowerCase();
    if (text.includes("强") || text.includes("推荐")) return "tone-green";
    if (text.includes("观察") || text.includes("谨慎")) return "tone-amber";
    return "tone-slate";
}

function severityTone(label) {
    const text = String(label || "").toLowerCase();
    if (text.includes("critical") || text.includes("error") || text.includes("严重")) return "tone-red";
    if (text.includes("warning") || text.includes("告警")) return "tone-amber";
    if (text.includes("healthy") || text.includes("ok")) return "tone-green";
    return "tone-slate";
}

function candidatePriority(row) {
    const score = toNumber(row.score);
    const poolType = String(row.pool_type || "").toLowerCase();
    const level = String(row.level || "");

    if (score >= 84 || level.includes("强烈")) {
        return {
            label: "主盯",
            tone: "tone-green",
            rowClass: "row-green",
            note: "开盘优先跟踪，只等盘中确认",
        };
    }
    if (score >= 80 || level.includes("推荐") || poolType === "core") {
        return {
            label: "观察",
            tone: "tone-amber",
            rowClass: "row-amber",
            note: "可以跟，但不是第一优先",
        };
    }
    return {
        label: "次要",
        tone: "tone-slate",
        rowClass: "row-slate",
        note: "不建议占用太多注意力",
    };
}

function holdingStatus(row) {
    const pnl = toNumber(row.unrealized_pct);
    if (pnl <= -8) return { label: "风险警戒", tone: "tone-red", rowClass: "row-red" };
    if (pnl < 0) return { label: "弱势观察", tone: "tone-amber", rowClass: "row-amber" };
    if (pnl >= 8) return { label: "浮盈保护", tone: "tone-green", rowClass: "row-green" };
    return { label: "正常持有", tone: "tone-green", rowClass: "row-green-soft" };
}

function signalStatus(row) {
    const type = String(row.signal_type || "");
    const suggestion = String(row.suggestion || "");
    const reason = String(row.trigger_reason || "");
    const merged = `${type} ${suggestion} ${reason}`;

    if (merged.includes("清仓") || merged.includes("止损") || merged.includes("风险")) {
        return { label: "立即处理", tone: "tone-red", rowClass: "row-red" };
    }
    if (merged.includes("卖") || merged.includes("减仓")) {
        return { label: "优先处理", tone: "tone-amber", rowClass: "row-amber" };
    }
    if (merged.includes("买") || merged.includes("突破") || merged.includes("回踩")) {
        return { label: "可执行", tone: "tone-green", rowClass: "row-green" };
    }
    return { label: "仅观察", tone: "tone-slate", rowClass: "row-slate" };
}

function openTradeStatus(row) {
    const score = toNumber(row.buy_score);
    const poolType = String(row.pool_type || "").toLowerCase();
    if (score >= 84) return { label: "强跟踪", tone: "tone-green", rowClass: "row-green" };
    if (score >= 78 || poolType === "core") return { label: "继续看", tone: "tone-amber", rowClass: "row-amber" };
    return { label: "低优先", tone: "tone-slate", rowClass: "row-slate" };
}

function pillHtml(text, tone = "tone-slate") {
    return `<span class="pill ${tone}">${safeText(text)}</span>`;
}

function miniPillHtml(text) {
    return `<span class="mini-pill">${safeText(text)}</span>`;
}

function actionNoteHtml(title, detail, tone = "tone-slate") {
    return `
        <div class="action-note ${tone}">
            <strong>${safeText(title)}</strong>
            <span>${safeText(detail, "")}</span>
        </div>
    `;
}

function openTradePriceHtml(row) {
    const buyPrice = row.buy_price !== null && row.buy_price !== undefined
        ? formatNumber(row.buy_price, 2)
        : "--";
    const lastPrice = row.last_price !== null && row.last_price !== undefined
        ? formatNumber(row.last_price, 2)
        : "--";
    return `
        <div class="cell-stack">
            <strong>${buyPrice}</strong>
            <span class="cell-note">最新 ${lastPrice}</span>
        </div>
    `;
}

function openTradePerformanceHtml(row) {
    const current = row.last_pnl_pct;
    const peak = row.peak_pnl_pct;
    const lowest = row.lowest_pnl_pct;
    const details = [];
    const tradeDateLabel = formatTradeDateLabel(row.last_trade_date);

    if (tradeDateLabel) {
        details.push(`按 ${tradeDateLabel}`);
    }
    if (peak !== null && peak !== undefined) {
        details.push(`最高 ${formatPercent(peak)}`);
    }
    if (lowest !== null && lowest !== undefined) {
        details.push(`最低 ${formatPercent(lowest)}`);
    }

    if (current === null || current === undefined) {
        return `
            <div class="cell-stack">
                <strong class="text-neutral">--</strong>
                ${details.length ? `<span class="cell-note">${details.join(" · ")}</span>` : ""}
            </div>
        `;
    }

    return `
        <div class="cell-stack">
            <strong class="${signClass(current)}">${formatPercent(current)}</strong>
            ${details.length ? `<span class="cell-note">${details.join(" · ")}</span>` : ""}
        </div>
    `;
}

function metricCardHtml(metric) {
    const tone = metric.tone || "slate";
    const rawValue = metric.isText
        ? safeText(metric.value)
        : metric.is_percentage
            ? formatPercent(metric.value)
            : formatNumber(metric.value, metric.digits || 0);
    const valueClass = metric.is_percentage ? signClass(metric.value) : "";
    const suffix = metric.isText ? "" : safeText(metric.unit, "");
    return `
        <article class="metric-card ${tone}">
            <span class="metric-label">${metric.label}</span>
            <strong class="metric-value ${valueClass}">${rawValue}${suffix && !metric.is_percentage ? `<small>${suffix}</small>` : ""}</strong>
            <span class="metric-note">${safeText(metric.note, "")}</span>
        </article>
    `;
}

function renderMetrics(metrics) {
    document.getElementById("metricsGrid").innerHTML = (metrics || []).map(metricCardHtml).join("");
}

function summaryListHtml(items) {
    const rows = (items || []).filter(Boolean);
    if (!rows.length) {
        return `<ul><li>暂无结论</li></ul>`;
    }
    return `<ul>${rows.map((item) => `<li>${safeText(item)}</li>`).join("")}</ul>`;
}

function systemMetricsSummaryHtml(metrics) {
    const m = metrics || {};
    const disk = m.disk || {};
    const proc = m.process || {};
    const mem = m.memory || {};

    const freePct = toNumber(disk.free_pct, NaN);
    const freeTone = Number.isFinite(freePct)
        ? (freePct < 10 ? "tone-red" : freePct < 18 ? "tone-amber" : "tone-green")
        : "tone-slate";

    const memUsed = toNumber(mem.used_pct, NaN);
    const memTone = Number.isFinite(memUsed)
        ? (memUsed > 92 ? "tone-red" : memUsed > 85 ? "tone-amber" : "tone-green")
        : "tone-slate";

    const rss = proc.rss_mb;
    const threads = proc.threads;

    const rows = [
        Number.isFinite(freePct)
            ? `磁盘可用：<span class="pill ${freeTone}">${formatNumber(freePct, 2)}%</span>（free ${formatNumber(disk.free_gb, 2)}GB / total ${formatNumber(disk.total_gb, 2)}GB）`
            : "磁盘：--",
        Number.isFinite(memUsed)
            ? `内存使用：<span class="pill ${memTone}">${formatNumber(memUsed, 2)}%</span>（available ${formatNumber(mem.available_gb, 2)}GB / total ${formatNumber(mem.total_gb, 2)}GB）`
            : "内存：--",
        rss !== undefined ? `进程RSS：${formatNumber(rss, 2)} MB` : "进程RSS：--",
        threads !== undefined ? `线程数：${formatNumber(threads, 0)}` : "线程数：--",
    ];
    return summaryListHtml(rows);
}

function todayBoardCardHtml(card) {
    return `
        <article class="today-board-card ${safeText(card.tone, "")}">
            <span class="muted-label">${safeText(card.label)}</span>
            <strong>${safeText(card.value)}</strong>
            <p>${safeText(card.note, "")}</p>
        </article>
    `;
}

function actionCenterCardHtml(title, row, emptyText) {
    if (!row) {
        return `
            <div class="action-center-card">
                <span class="muted-label">${safeText(title)}</span>
                <strong>暂无记录</strong>
                <p>${safeText(emptyText, "今天还没有对应动作。")}</p>
            </div>
        `;
    }
    return `
        <div class="action-center-card">
            <span class="muted-label">${safeText(title)}</span>
            <strong>${safeText(row.action_label || row.action_key)}</strong>
            <p>${safeText(row.created_time, "--")} · ${safeText(row.status_label || row.status, "--")}</p>
            <p>${safeText(row.message, "--")}</p>
        </div>
    `;
}

function actionTimelineHtml(rows) {
    if (!(rows || []).length) {
        return `<div class="empty-state">今日还没有动作执行记录。</div>`;
    }
    return (rows || []).map((row) => `
        <article class="action-timeline-item">
            <strong>${safeText(row.action_label)}</strong>
            <span>${safeText(row.created_time)} · ${safeText(row.status_label)}</span>
            <p>${safeText(row.message, "--")}</p>
        </article>
    `).join("");
}

function stageActionButtonHtml(action, secondary = false) {
    const klass = secondary ? "stage-ghost-btn" : "primary-btn";
    return `<button type="button" class="${klass}" data-action="${safeText(action.key, "")}">${safeText(action.label)}</button>`;
}

function renderTodayBoard(snapshot) {
    const board = snapshot.today_board || {};
    document.getElementById("todayBoardCards").innerHTML = (board.cards || []).map(todayBoardCardHtml).join("");

    const actions = board.quick_actions || [];
    document.getElementById("todayBoardActions").innerHTML = actions.map((item, index) =>
        stageActionButtonHtml(item, index > 0)
    ).join("");
    const monitor = snapshot.monitor_session || {};
    const terminalRuntime = snapshot.terminal_runtime || {};
    const actionCenter = snapshot.action_center || {};
    const outbox = actionCenter.push_outbox || {};
    const extraHighlights = [
        `盯盘会话：${safeText(monitor.status_label, "未开始")}`,
        `实时监控：${safeText(monitor.runtime_status_label, "未知")}`,
        `终端运行态：${safeText(terminalRuntime.status_label, "未知")}`,
    ];
    document.getElementById("todayBoardHighlights").innerHTML = summaryListHtml([...(board.highlights || []), ...extraHighlights]);
    document.getElementById("actionCenterSummary").innerHTML = summaryListHtml([
        `最近动作摘要：${safeText(actionCenter.latest_summary, "暂无执行记录")}`,
        ...(actionCenter.latest ? [`最近结果：${safeText(actionCenter.latest.message, "--")}`] : []),
        ...(outbox.available ? [`推送队列：待发 ${toNumber(outbox.pending)} 条 / 失败 ${toNumber(outbox.failed)} 条`] : []),
    ]);
    document.getElementById("actionCenterLatestSuccess").innerHTML = actionCenterCardHtml(
        "最近一次成功动作",
        actionCenter.latest_success,
        "今天还没有成功动作。"
    );
    document.getElementById("actionCenterLatestFailed").innerHTML = actionCenterCardHtml(
        "最近一次失败动作",
        actionCenter.latest_failed,
        "今天暂无失败动作。"
    );
    document.getElementById("actionTimeline").innerHTML = actionTimelineHtml(actionCenter.timeline || []);
}

function journeyQuoteLineHtml(item) {
    if (!item.quote_ok) {
        return `<p class="journey-quote-muted">实时：${safeText(item.quote_hint, "暂无行情")}</p>`;
    }
    const pct = item.quote_pct_change;
    const pctCls = signClass(pct);
    const src = item.quote_source ? ` · ${safeText(item.quote_source)}` : "";
    return `
        <div class="journey-quote">
            <span class="journey-quote-price">${formatNumber(item.quote_price, 2)}</span>
            <span class="journey-quote-pct ${pctCls}">${formatPercent(pct)}</span>
            <span class="journey-quote-oh">高 ${formatNumber(item.quote_high, 2)} / 低 ${formatNumber(item.quote_low, 2)}</span>
            <span class="journey-quote-vol">量 ${formatNumber(item.quote_volume, 0)} 手</span>
            <span class="journey-quote-time">${safeText(item.quote_time, "--")}${src}</span>
        </div>
    `;
}

function journeyItemHtml(item, type) {
    if (type === "pre") {
        return `
            <article class="journey-item">
                <div class="journey-item-head">
                    <div class="journey-item-title">
                        <strong>${safeText(item.name)}</strong>
                        ${item.symbol ? `<span class="journey-badge">${safeText(item.symbol)}</span>` : ""}
                    </div>
                    <span class="journey-badge">${safeText(item.level)}</span>
                </div>
                <p>${safeText(item.summary)}</p>
                <p>关注重点：${safeText(item.focus)}</p>
                <p>风险提示：${safeText(item.risk_tip)}</p>
            </article>
        `;
    }

    if (type === "watch") {
        return `
            <article class="journey-item">
                <div class="journey-item-head">
                    <div class="journey-item-title">
                        <strong>${safeText(item.name)}</strong>
                        <span class="journey-badge">${safeText(item.symbol)}</span>
                    </div>
                    <span class="journey-badge">${safeText(item.status)}</span>
                </div>
                <p>${safeText(item.note)}</p>
                <p class="journey-quote-muted">信号：${safeText(item.signal_status_label, "--")}；原因：${safeText(item.signal_reason, "--")}</p>
                ${journeyQuoteLineHtml(item)}
            </article>
        `;
    }

    return `
        <article class="journey-item">
            <div class="journey-item-head">
                <div class="journey-item-title">
                    <strong>${safeText(item.name)}</strong>
                    <span class="journey-badge">${safeText(item.symbol)}</span>
                </div>
                <span class="journey-badge">${safeText(item.signal_time, "--")}</span>
            </div>
            <p>${safeText(item.signal_type, "暂无信号")}</p>
            <p>${safeText(item.suggestion, "仅观察")}：${safeText(item.trigger_reason, "等待确认")}</p>
            <p class="journey-quote-muted">信号：${safeText(item.signal_status_label, "--")}；原因：${safeText(item.signal_reason, "--")}</p>
            ${journeyQuoteLineHtml(item)}
        </article>
    `;
}

function renderJourney(snapshot) {
    const journey = snapshot.journey || {};
    const preMarket = journey.pre_market || {};
    const intraday = journey.intraday || {};
    const postMarket = journey.post_market || {};
    const postSummary = postMarket.summary || {};
    const tracking = snapshot.secondary_launch_tracking || {};
    const trackingSummary = tracking.summary || {};
    const monitorSession = intraday.monitor_session || snapshot.monitor_session || {};
    const terminalRuntime = snapshot.terminal_runtime || {};

    document.getElementById("preMarketSummary").textContent = safeText(preMarket.summary);
    document.getElementById("preMarketActionButton").textContent = safeText(preMarket.action_label, "生成今日计划");
    document.getElementById("preMarketList").innerHTML = (preMarket.items || []).map((item) => journeyItemHtml(item, "pre")).join("");

    document.getElementById("intradaySummary").textContent = safeText(intraday.summary);
    document.getElementById("intradayActionButton").textContent = safeText(intraday.action_label, "开始盘中盯盘");
    document.getElementById("intradayRefreshButton").textContent = monitorSession.is_active ? "刷新盘中状态" : "开始后可刷新";
    document.getElementById("intradayWatchList").innerHTML = (intraday.watch_list || []).length
        ? (intraday.watch_list || []).map((item) => journeyItemHtml(item, "watch")).join("")
        : `<div class="empty-state">暂无重点观察股票</div>`;
    document.getElementById("intradaySignalList").innerHTML = (intraday.signals || []).length
        ? (intraday.signals || []).map((item) => journeyItemHtml(item, "signal")).join("")
        : `<div class="empty-state">当前没有新的可执行信号</div>`;
    const qStatus = intraday.quote_batch_status || "";
    const qNote =
        qStatus === "error"
            ? "实时行情接口异常，以下为计划与信号说明。"
            : qStatus === "empty"
              ? "暂无实时行情返回（可能非交易时段或网络受限）。"
              : "";
    const runtimeLine = `盯盘会话：${safeText(monitorSession.status_label, "未开始")}；实时监控：${safeText(monitorSession.runtime_status_label, "未知")}；终端运行态：${safeText(terminalRuntime.status_label, "未知")}；行情拉取：${safeText(
        qStatus || "—",
        "—"
    )}。`;
    document.getElementById("intradayRiskHint").textContent = `${runtimeLine}${qNote ? ` ${qNote}` : ""} ${safeText(intraday.risk_hint, "只处理已确认信号。")}`;

    document.getElementById("postMarketSummary").textContent = `今日推荐 ${formatNumber(postSummary.recommended_count || 0)} 只，触发 ${formatNumber(postSummary.triggered_count || 0)} 只。`;
    document.getElementById("postMarketActionButton").textContent = safeText(postMarket.action_label, "生成今日复盘");
    document.getElementById("postMarketHeadline").innerHTML = summaryListHtml([
        `今日候选：${formatNumber(postSummary.candidate_pool_count ?? postSummary.recommended_count ?? 0)}只`,
        `候选触发：${formatNumber(postSummary.candidate_hit_count ?? postSummary.triggered_count ?? 0)}只`,
        `候选未触发：${formatNumber(postSummary.candidate_miss_count ?? 0)}只`,
        `候选主因：${safeText(postSummary.candidate_main_reason || postSummary.main_blocker, "暂无")}`,
    ]);
    document.getElementById("postMarketDoneRight").innerHTML = summaryListHtml(postSummary.done_right || []);
    document.getElementById("postMarketMissed").innerHTML = summaryListHtml(postSummary.missed_today || []);
    document.getElementById("postMarketNextActions").innerHTML = summaryListHtml(postSummary.next_day_actions || []);
    const candidateRows = postSummary.candidate_signal_rows || [];
    const candidateLines = candidateRows.length
        ? candidateRows.map((row) => `候选 ${safeText(row.name)}(${safeText(row.symbol)})：${safeText(row.status)}；${safeText(row.reason)}`)
        : [];
    document.getElementById("postMarketBlockers").innerHTML = summaryListHtml([
        "候选池逐只结果（用于解释“为什么没触发”）：",
        ...candidateLines,
        "",
        `全量复盘信号：${formatNumber(trackingSummary.reviewed_signal_count || 0)}只`,
        `全量出现买点：${formatNumber(trackingSummary.buy_signal_count || 0)}只`,
        `全量未触发：${formatNumber(trackingSummary.not_pushed_count || 0)}只`,
        ...((trackingSummary.top_blockers || []).slice(0, 3).map((item) =>
            `${safeText(item.label || item.reason, "未知原因")}：${formatNumber(item.count || 0)}次`
        )),
    ].filter((line) => String(line).trim() !== ""));
}

function renderHero(snapshot) {
    const meta = snapshot.meta || {};
    const headline = snapshot.overview?.headline || {};
    const flags = meta.feature_flags || {};

    document.getElementById("generatedTime").textContent = safeText(meta.generated_label);
    document.getElementById("marketPhase").textContent = safeText(meta.market_session?.phase);
    document.getElementById("minuteProvider").textContent = safeText(meta.minute_provider);
    document.getElementById("heroStatusLabel").textContent = safeText(headline.health_label);
    document.getElementById("heroStatusDetail").textContent = safeText(
        headline.candidate_status || meta.market_session?.detail
    );

    const orb = document.getElementById("statusOrb");
    orb.className = `status-orb status-${snapshot.health?.tone || "slate"}`;

    const chips = [
        `策略 ${safeText(meta.strategy_profile)}`,
        `权重档 ${safeText(meta.enhanced_weight_profile)}`,
        flags.runtime_optimization ? "运行时优化 开" : "运行时优化 关",
        flags.market_gate ? "市场闸门 开" : "市场闸门 关",
        flags.feedback_guard ? "反馈防护 开" : "反馈防护 关",
        safeText(meta.market_session?.detail, ""),
    ];

    document.getElementById("heroChips").innerHTML = chips
        .filter(Boolean)
        .map((item) => `<span class="chip"><span class="chip-dot"></span>${item}</span>`)
        .join("");
}

function renderSnapshot(snapshot) {
    renderHero(snapshot);
    renderTodayBoard(snapshot);
    renderJourney(snapshot);
    renderCommandDeck(snapshot);
    renderSpotlights(snapshot);
    renderRiskList(snapshot);
    renderMetrics(snapshot.overview?.metrics || []);
    renderRecommendationTrend(snapshot.recommendations || {});
    renderFeedbackChart(snapshot.feedback || {});
    renderTradeCurve(snapshot.virtual_trades || {});
    renderHealthChart(snapshot.health || {});
    const systemMetricsDom = document.getElementById("systemMetricsSummary");
    if (systemMetricsDom) {
        systemMetricsDom.innerHTML = systemMetricsSummaryHtml(snapshot.health?.system_metrics || {});
    }
    renderPieChart("signalMixChart", snapshot.signals?.type_distribution || [], "暂无信号");
    renderPieChart("industryMixChart", snapshot.candidate_pool?.industry_distribution || [], "暂无候选");
    renderTables(snapshot);
}

function taskItemHtml(task) {
    if (!task) {
        return `<div class="empty-state">暂无后台任务。</div>`;
    }
    return `
        <article class="task-item">
            <strong>${safeText(task.action_label || task.action_key, "未命名任务")}</strong>
            <span>状态：${safeText(task.status, "未知")} · 开始：${safeText(task.started_at, "--")}</span>
            <p>${safeText(task.message, "暂无说明")}</p>
        </article>
    `;
}

function renderTaskList(tasks) {
    const dom = document.getElementById("taskList");
    if (!dom) return;
    const rows = tasks || [];
    dom.innerHTML = rows.length ? rows.map(taskItemHtml).join("") : `<div class="empty-state">暂无后台任务。</div>`;
}

function getWecomStrategyPayload() {
    const select = document.getElementById("wecomStrategySelect");
    return {
        strategy: select ? String(select.value || "secondary_launch") : "secondary_launch",
    };
}

async function loadTasks() {
    const response = await fetch("/api/dashboard/tasks");
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    renderTaskList(payload.tasks || []);
}

function showActionFeedback(title, text) {
    const card = document.getElementById("actionFeedbackCard");
    document.getElementById("actionFeedbackTitle").textContent = safeText(title, "操作已完成");
    document.getElementById("actionFeedbackText").textContent = safeText(text, "");
    card.hidden = false;
}

function ensureChart(id) {
    const dom = document.getElementById(id);
    if (!charts[id]) {
        charts[id] = echarts.init(dom);
    }
    return charts[id];
}

function baseChartOption() {
    return {
        textStyle: { fontFamily: "Noto Sans SC, Microsoft YaHei, sans-serif", color: "#182927" },
        grid: { left: 42, right: 18, top: 24, bottom: 34, containLabel: true },
        tooltip: {
            trigger: "axis",
            backgroundColor: "rgba(24,41,39,.94)",
            borderWidth: 0,
            textStyle: { color: "#fff" },
        },
    };
}

function buildPrimaryCommand(snapshot) {
    const market = snapshot.meta?.market_session || {};
    const health = snapshot.health || {};
    const candidatePool = snapshot.candidate_pool || {};
    const signals = snapshot.signals || {};

    if (health.status === "stale") {
        return {
            tone: "tone-slate",
            kicker: "先恢复实时链路",
            title: "先别依赖盘中执行信号",
            value: "监控停更",
            body: "健康快照已停更，当前更适合看候选池和复盘，不适合把这块看板当实时执行依据。",
            pills: [
                `健康 ${safeText(health.status_label)}`,
                safeText(market.phase),
                safeText(snapshot.overview?.headline?.recommendation_status),
            ],
            points: [
                "先确认监控服务和分钟数据链路恢复更新。",
                "在恢复前，只把这里当盘前/盘后复盘面板使用。",
                safeText(signals.latest_signal_label, "暂无最近信号"),
            ],
        };
    }

    if (!toNumber(candidatePool.count)) {
        return {
            tone: healthTone(health.status),
            kicker: "先补候选池",
            title: "今天先别急着找买点",
            value: "无候选",
            body: "当前没有可用候选池。对你来说，下一步不是看信号，而是先跑盘前选股。",
            pills: [
                `市场 ${safeText(market.phase)}`,
                `健康 ${safeText(health.status_label)}`,
            ],
            points: [
                "先执行一次盘前选股，生成观察池。",
                "没有候选池时，盘中提醒的参考价值会明显下降。",
            ],
        };
    }

    if (market.phase === "休市" || market.phase === "盘后") {
        return {
            tone: healthTone(health.status),
            kicker: "现在是准备时间",
            title: "先看候选池，不做盘中判断",
            value: `${formatNumber(candidatePool.count)}只`,
            body: "当前处于休市/盘后阶段。你现在最需要做的是缩小观察范围，而不是预判每一只票的走势。",
            pills: [
                `主策略 ${safeText(snapshot.meta?.strategy_profile)}`,
                `候选均分 ${formatNumber(candidatePool.avg_score, 1)}`,
                safeText(candidatePool.freshness_label),
            ],
            points: [
                "把注意力集中在前 3 只，而不是把 TOP10 都当成要做的票。",
                "第二天开盘前只需要记住：盘前计划不是下单指令，盘中信号才是执行候选。",
            ],
        };
    }

    if (market.phase === "盘前") {
        return {
            tone: healthTone(health.status),
            kicker: "开盘前怎么做",
            title: "先圈定 2 到 4 只重点票",
            value: `${formatNumber(candidatePool.count)}只`,
            body: "现在不需要决定买谁，只需要先把注意力缩到最值得盯的少数票上，等盘中结构确认。",
            pills: [
                `主策略 ${safeText(snapshot.meta?.strategy_profile)}`,
                `候选均分 ${formatNumber(candidatePool.avg_score, 1)}`,
                safeText(candidatePool.freshness_label),
            ],
            points: [
                "优先盯前 3 名候选，不要把 TOP10 全做。",
                "盘中只根据买点信号执行，不根据盘前分数直接追单。",
            ],
        };
    }

    if (market.phase === "午间休市") {
        return {
            tone: healthTone(health.status),
            kicker: "中场复核",
            title: "先检查上午信号，不急着追加",
            value: safeText(health.status_label),
            body: "午间更适合复核上午已经出现的买卖提示，而不是情绪化地追加新交易。",
            pills: [
                `候选 ${formatNumber(candidatePool.count)}只`,
                `近两周信号 ${formatNumber(snapshot.signals?.recent_count || 0)}条`,
            ],
            points: [
                "先看真实持仓和虚拟持仓有没有需要处理的事件。",
                "下午开盘前优先复核风险，而不是直接扩大仓位。",
            ],
        };
    }

    return {
        tone: healthTone(health.status),
        kicker: "盘中执行纪律",
        title: "只做触发信号，不做主观追单",
        value: `${formatNumber(candidatePool.count)}只`,
        body: "现在是盘中时段。对你最重要的不是重新选股，而是只在买点模板真正触发时执行。",
        pills: [
            `健康 ${safeText(health.status_label)}`,
            `候选均分 ${formatNumber(candidatePool.avg_score, 1)}`,
            safeText(signals.latest_signal_label),
        ],
        points: [
            "盘前计划只是观察池，盘中买点信号才是执行候选。",
            "平弱开盘且没有修复确认的票，宁可不做。",
        ],
    };
}

function buildEdgeCard(snapshot) {
    const best = snapshot.feedback?.best_summary;
    const stats = snapshot.virtual_trades?.stats || {};

    if (!best) {
        return {
            tone: "tone-slate",
            kicker: "系统边际",
            title: "暂时没有足够闭环结论",
            value: "样本不足",
            body: "当前还不能明确判断系统最近是偏强还是偏弱，需要再积累闭环样本。",
            pills: [
                `虚拟闭环 ${formatNumber(stats.total_closed || 0)}笔`,
                `虚拟胜率 ${formatNumber(stats.win_rate_pct || 0, 1)}%`,
            ],
            points: [
                "样本不足时，不要因为几笔漂亮交易就放大仓位。",
            ],
        };
    }

    let tone = "tone-slate";
    let title = "系统边际中性";
    let advice = "当前看起来并不差，但也还不到可以放松执行纪律的时候。";

    if (toNumber(best.mean_net_return_pct) >= 1 && toNumber(best.sample_count) >= 50) {
        tone = "tone-green";
        title = "系统边际偏强";
        advice = "说明这段时间闭环效果有一定优势，可以继续按纪律执行，但仍然不要满仓化。";
    } else if (toNumber(best.mean_net_return_pct) < 0) {
        tone = "tone-amber";
        title = "系统边际偏弱";
        advice = "说明系统更像是在抓波动，而不是稳定落袋。执行上应该偏保守，别因为候选分数高就放大仓位。";
    }

    return {
        tone,
        kicker: "系统边际",
        title,
        value: `T+${safeText(best.horizon)}`,
        body: `目前最优闭环窗口是 ${safeText(best.label)} / T+${safeText(best.horizon)}，均值净收益 ${formatPercent(best.mean_net_return_pct)}，平均峰值 ${formatPercent(best.mean_mfe_pct)}。`,
        pills: [
            `样本 ${formatNumber(best.sample_count)}`,
            `虚拟胜率 ${formatNumber(stats.win_rate_pct || 0, 1)}%`,
            `虚拟均值 ${formatPercent(stats.avg_pnl_pct || 0, 2)}`,
        ],
        points: [advice],
    };
}

function buildRiskCard(snapshot) {
    const health = snapshot.health || {};
    const holdings = snapshot.holdings || {};
    const openVirtual = snapshot.virtual_trades?.open_count || 0;
    const recentIncidents = snapshot.health?.recent_incidents || [];

    let tone = healthTone(health.status);
    let title = "当前风险可控";
    let body = "没有看到特别突出的硬风险，重点还是按纪律执行。";

    if (health.status === "stale") {
        tone = "tone-red";
        title = "实时监控风险高";
        body = "系统健康快照停更时，最大的风险不是选错票，而是你把旧状态当成实时状态。";
    } else if (health.status === "degraded" || recentIncidents.length > 0) {
        tone = "tone-amber";
        title = "运行层有告警";
        body = "系统不是完全坏了，但当前需要把注意力分一部分给运行稳定性，而不是只盯收益。";
    } else if (toNumber(holdings.total_unrealized_pct) < -2) {
        tone = "tone-amber";
        title = "真实持仓承压";
        body = "真实持仓整体浮亏已经明显转弱，接下来更应该优先处理风险而不是继续扩仓。";
    }

    return {
        tone,
        kicker: "风险暴露",
        title,
        value: `${formatNumber(holdings.count || 0)}持仓`,
        body,
        pills: [
            `真实浮盈 ${formatPercent(holdings.total_unrealized_pct || 0, 2)}`,
            `虚拟持仓 ${formatNumber(openVirtual)}笔`,
            `告警 ${formatNumber(health.incident_count || recentIncidents.length || 0)}条`,
        ],
        points: [
            "真实持仓和虚拟样本要分开看，别把系统跟踪样本当成你的真实仓位。",
        ],
    };
}

function buildFocusCard(snapshot) {
    const candidates = snapshot.candidate_pool?.top_candidates || [];
    const topCodes = candidates.slice(0, 3).map((item) => safeText(item.symbol)).filter(Boolean);
    const market = snapshot.meta?.market_session || {};

    return {
        tone: "tone-slate",
        kicker: "盯盘范围",
        title: "今天只需要盯少数票",
        value: topCodes.length ? topCodes.join(" / ") : "暂无",
        body: market.phase === "盘前" || market.phase === "休市" || market.phase === "盘后"
            ? "看板已经帮你把候选池压缩成可执行观察范围了。真正需要重点看的，通常就是前 3 只。"
            : "盘中不要重新在全市场找感觉，继续围绕已有观察池和实际触发的信号执行就够了。",
        pills: [
            `TOP1 ${safeText(candidates[0]?.name, "--")}`,
            `TOP2 ${safeText(candidates[1]?.name, "--")}`,
            `TOP3 ${safeText(candidates[2]?.name, "--")}`,
        ].filter((item) => !item.endsWith("--")),
        points: [
            "如果你必须放弃一些票，优先放弃排位靠后的备选，不要把注意力摊太散。",
        ],
    };
}

function briefCardHtml(card, primary = false) {
    return `
        <div class="brief-inner">
            <div class="brief-head">
                <span class="brief-kicker">${safeText(card.kicker)}</span>
                <h3 class="brief-title">${safeText(card.title)}</h3>
                <div class="brief-value">${safeText(card.value)}</div>
            </div>
            <div class="brief-body">${safeText(card.body)}</div>
            <div class="brief-meta">${(card.pills || []).map(miniPillHtml).join("")}</div>
            <div class="brief-points">${(card.points || []).map((item) => `<div class="brief-point">${item}</div>`).join("")}</div>
        </div>
    `;
}

function renderCommandDeck(snapshot) {
    const primaryCard = buildPrimaryCommand(snapshot);
    document.getElementById("commandCard").className = `brief-card brief-card-primary ${primaryCard.tone}`;
    document.getElementById("commandCard").innerHTML = briefCardHtml(primaryCard, true);

    const edgeCard = buildEdgeCard(snapshot);
    document.getElementById("edgeCard").className = `brief-card ${edgeCard.tone}`;
    document.getElementById("edgeCard").innerHTML = briefCardHtml(edgeCard);

    const riskCard = buildRiskCard(snapshot);
    document.getElementById("riskCard").className = `brief-card ${riskCard.tone}`;
    document.getElementById("riskCard").innerHTML = briefCardHtml(riskCard);

    const focusCard = buildFocusCard(snapshot);
    document.getElementById("focusCard").className = `brief-card ${focusCard.tone}`;
    document.getElementById("focusCard").innerHTML = briefCardHtml(focusCard);
}

function renderSpotlights(snapshot) {
    const candidates = snapshot.candidate_pool?.top_candidates || [];
    const list = document.getElementById("spotlightList");

    if (!candidates.length) {
        list.innerHTML = `<div class="empty-state">暂无候选池数据，先执行盘前选股。</div>`;
        return;
    }

    list.innerHTML = candidates.slice(0, 3).map((row, index) => `
        <article class="spotlight-card">
            <div class="spotlight-rank">${index + 1}</div>
            <div class="spotlight-main">
                <div class="spotlight-title">
                    <strong>${safeText(row.name)}</strong>
                    <span class="spotlight-code">${safeText(row.symbol)}</span>
                </div>
                <div class="spotlight-meta">
                    ${pillHtml(`评分 ${formatNumber(row.score, 1)}`, toneClass(row.score - 80))}
                    ${pillHtml(safeText(candidatePriority(row).label), candidatePriority(row).tone)}
                    ${pillHtml(safeText(row.level, "观察"), levelTone(row.level))}
                    ${pillHtml(safeText(row.industry, "未分类"), "tone-slate")}
                    ${pillHtml(safeText(row.pool_type, "default"), "tone-slate")}
                </div>
                <div class="spotlight-note">
                    ${candidatePriority(row).note}。${index === 0 ? "这是当前第一优先候选，盘中只等买点确认，不要因为分数高就提前追单。" : ""}
                    ${index === 1 ? "这是第二顺位候选，适合作为主盯票的替补，不需要和第一名同时重仓。" : ""}
                    ${index === 2 ? "这是第三顺位候选，更多用于备选补位，不建议和前两名一起摊薄注意力。" : ""}
                </div>
            </div>
        </article>
    `).join("");
}

function renderRiskList(snapshot) {
    const risks = [];
    const health = snapshot.health || {};
    const best = snapshot.feedback?.best_summary;
    const holdings = snapshot.holdings || {};
    const incidents = health.recent_incidents || [];

    if (health.status === "stale") {
        risks.push({
            tone: "tone-red",
            title: "实时健康快照已停更",
            body: "当前更适合看候选池和复盘，不适合拿实时状态做盘中执行判断。",
        });
    } else if (health.status === "degraded") {
        risks.push({
            tone: "tone-amber",
            title: "系统运行层有告警",
            body: safeText(health.subtitle, "请先检查监控和推送链路。"),
        });
    }

    if (best && toNumber(best.mean_net_return_pct) < 0) {
        risks.push({
            tone: "tone-amber",
            title: "闭环净收益仍偏弱",
            body: `最佳窗口净收益 ${formatPercent(best.mean_net_return_pct)}，说明当前更该保守执行，而不是放大仓位。`,
        });
    }

    if (toNumber(holdings.total_unrealized_pct) < -2) {
        risks.push({
            tone: "tone-red",
            title: "真实持仓整体浮亏偏大",
            body: `真实持仓当前总浮盈 ${formatPercent(holdings.total_unrealized_pct)}，优先处理风险，不建议继续情绪化加仓。`,
        });
    }

    incidents.slice(0, 2).forEach((row) => {
        risks.push({
            tone: severityTone(row.severity),
            title: safeText(row.title, "运行告警"),
            body: `${safeText(row.component, "unknown")} · ${safeText(row.incident_time, "--")}`,
        });
    });

    if (!risks.length) {
        risks.push({
            tone: "tone-green",
            title: "当前没有明显硬风险",
            body: "系统状态、闭环表现和持仓侧暂时没有出现必须优先处理的红灯项。",
        });
    }

    document.getElementById("riskList").innerHTML = risks.map((item) => `
        <article class="risk-item ${item.tone}">
            <strong>${item.title}</strong>
            <p>${item.body}</p>
        </article>
    `).join("");
}

function renderRecommendationTrend(section) {
    const chart = ensureChart("recommendationTrendChart");
    const trend = section.trend || [];
    chart.setOption({
        ...baseChartOption(),
        legend: { data: ["推荐数量", "平均评分"] },
        xAxis: {
            type: "category",
            data: trend.map((item) => item.date),
            axisLine: { lineStyle: { color: palette.grid } },
        },
        yAxis: [
            { type: "value", name: "数量", splitLine: { lineStyle: { color: palette.grid } } },
            { type: "value", name: "评分", min: 0, max: 100, splitLine: { show: false } },
        ],
        series: [
            {
                name: "推荐数量",
                type: "bar",
                data: trend.map((item) => item.count),
                itemStyle: { color: palette.teal, borderRadius: [8, 8, 0, 0] },
            },
            {
                name: "平均评分",
                type: "line",
                yAxisIndex: 1,
                smooth: true,
                symbolSize: 8,
                data: trend.map((item) => item.avg_score),
                lineStyle: { width: 3, color: palette.gold },
                itemStyle: { color: palette.gold },
            },
        ],
    });
}

function renderFeedbackChart(section) {
    const chart = ensureChart("feedbackChart");
    const payload = section.chart || { horizons: [], series: [] };
    chart.setOption({
        ...baseChartOption(),
        legend: { top: 0 },
        xAxis: {
            type: "category",
            data: (payload.horizons || []).map((item) => `T+${item}`),
            axisLine: { lineStyle: { color: palette.grid } },
        },
        yAxis: { type: "value", name: "净收益(%)", splitLine: { lineStyle: { color: palette.grid } } },
        series: (payload.series || []).map((item, index) => ({
            name: item.name,
            type: "bar",
            data: item.values,
            barMaxWidth: 24,
            itemStyle: {
                color: [palette.navy, palette.teal, palette.rose, palette.plum][index % 4],
                borderRadius: [8, 8, 0, 0],
            },
        })),
    });
}

function renderTradeCurve(section) {
    const chart = ensureChart("tradeCurveChart");
    const curve = section.equity_curve || [];
    const daily = section.daily_pnl || [];
    chart.setOption({
        ...baseChartOption(),
        legend: { data: ["累计收益", "日度收益"] },
        xAxis: [
            {
                type: "category",
                gridIndex: 0,
                data: curve.map((item) => item.time || ""),
                axisLine: { lineStyle: { color: palette.grid } },
            },
            {
                type: "category",
                gridIndex: 1,
                data: daily.map((item) => item.date || ""),
                axisLine: { lineStyle: { color: palette.grid } },
            },
        ],
        yAxis: [
            { type: "value", gridIndex: 0, name: "累计(%)", splitLine: { lineStyle: { color: palette.grid } } },
            { type: "value", gridIndex: 1, name: "日度(%)", splitLine: { show: false } },
        ],
        grid: [
            { left: 42, right: 18, top: 28, height: "52%" },
            { left: 42, right: 18, top: "70%", height: "16%" },
        ],
        tooltip: { trigger: "axis" },
        series: [
            {
                name: "累计收益",
                type: "line",
                smooth: true,
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: curve.map((item) => item.value),
                lineStyle: { width: 3, color: palette.emerald },
                itemStyle: { color: palette.emerald },
            },
            {
                name: "日度收益",
                type: "bar",
                xAxisIndex: 1,
                yAxisIndex: 1,
                data: daily.map((item) => item.pnl_pct),
                itemStyle: {
                    color: (params) => params.value >= 0 ? palette.teal : palette.rose,
                    borderRadius: [8, 8, 0, 0],
                },
            },
        ],
    });
}

function renderHealthChart(section) {
    const chart = ensureChart("healthTimelineChart");
    const trend = section.timeline || [];
    chart.setOption({
        ...baseChartOption(),
        legend: { data: ["成功数", "告警数"] },
        xAxis: {
            type: "category",
            data: trend.map((item) => item.time),
            axisLine: { lineStyle: { color: palette.grid } },
        },
        yAxis: { type: "value", splitLine: { lineStyle: { color: palette.grid } } },
        series: [
            {
                name: "成功数",
                type: "line",
                smooth: true,
                data: trend.map((item) => item.success_total),
                lineStyle: { width: 3, color: palette.navy },
                itemStyle: { color: palette.navy },
            },
            {
                name: "告警数",
                type: "bar",
                data: trend.map((item) => item.incident_total),
                itemStyle: { color: palette.amber, borderRadius: [8, 8, 0, 0] },
            },
        ],
    });
}

function renderPieChart(id, section, fallbackLabel) {
    const chart = ensureChart(id);
    const data = section || [];
    chart.setOption({
        tooltip: { trigger: "item" },
        series: [{
            type: "pie",
            radius: ["42%", "70%"],
            center: ["50%", "54%"],
            itemStyle: { borderColor: "#fff9ef", borderWidth: 4 },
            label: { formatter: "{b}\n{d}%" },
            data: data.length ? data : [{ name: fallbackLabel, value: 1, itemStyle: { color: "#cbd5e1" } }],
        }],
    });
}

function tableHtml(columns, rows, emptyLabel, getRowClass = null) {
    if (!rows || !rows.length) {
        return `<tbody><tr><td colspan="${columns.length}"><div class="empty-state">${emptyLabel}</div></td></tr></tbody>`;
    }

    const head = `<thead><tr>${columns.map((column) => `<th>${column.label}</th>`).join("")}</tr></thead>`;
    const body = rows.map((row) => {
        const tds = columns.map((column) => `<td>${column.render ? column.render(row) : safeText(row[column.key])}</td>`).join("");
        const rowClass = getRowClass ? getRowClass(row) : "";
        return `<tr class="${safeText(rowClass, "")}">${tds}</tr>`;
    }).join("");
    return `${head}<tbody>${body}</tbody>`;
}

function renderTables(snapshot) {
    document.getElementById("candidateTable").innerHTML = tableHtml(
        [
            { label: "优先级", render: (row) => pillHtml(candidatePriority(row).label, candidatePriority(row).tone) },
            { label: "代码", key: "symbol" },
            { label: "名称", render: (row) => `${safeText(row.name)}<br><small>${candidatePriority(row).note}</small>` },
            { label: "评分", render: (row) => `<span class="${signClass(toNumber(row.score) - 80)}">${formatNumber(row.score, 1)}</span>` },
            { label: "级别", render: (row) => pillHtml(safeText(row.level), levelTone(row.level)) },
            { label: "行业", key: "industry" },
            { label: "池型", render: (row) => pillHtml(safeText(row.pool_type, "default"), "tone-slate") },
        ],
        snapshot.candidate_pool?.top_candidates || [],
        "暂无候选池缓存",
        (row) => candidatePriority(row).rowClass
    );

    document.getElementById("holdingTable").innerHTML = tableHtml(
        [
            { label: "状态", render: (row) => pillHtml(holdingStatus(row).label, holdingStatus(row).tone) },
            { label: "标的", render: (row) => `${safeText(row.ts_code)}<br><small>${safeText(row.name, "")}</small>` },
            { label: "成本 / 现价", render: (row) => `${formatNumber(row.hold_price, 2)} / ${row.latest_close !== null ? formatNumber(row.latest_close, 2) : "--"}` },
            { label: "数量", render: (row) => `${formatNumber(row.hold_num)}股` },
            { label: "浮盈", render: (row) => `<span class="${signClass(row.unrealized_pct)}">${formatPercent(row.unrealized_pct)}</span>` },
            { label: "市值", render: (row) => formatNumber(row.market_value, 2) },
        ],
        snapshot.holdings?.items || [],
        "暂无真实持仓",
        (row) => holdingStatus(row).rowClass
    );

    document.getElementById("openTradeTable").innerHTML = tableHtml(
        [
            { label: "跟踪级别", render: (row) => pillHtml(openTradeStatus(row).label, openTradeStatus(row).tone) },
            { label: "标的", render: (row) => `${safeText(row.symbol)}<br><small>${safeText(row.name, "")}</small>` },
            { label: "买入时间", key: "buy_time" },
            { label: "价格", render: (row) => openTradePriceHtml(row) },
            { label: "收益表现", render: (row) => openTradePerformanceHtml(row) },
            { label: "信号", render: (row) => `${safeText(row.buy_signal)}<br><small>分数 ${formatNumber(row.buy_score, 1)}</small>` },
            { label: "路由", render: (row) => pillHtml(safeText(row.buy_route, "未记录"), "tone-slate") },
        ],
        snapshot.virtual_trades?.open_trades || [],
        "暂无未平仓虚拟交易",
        (row) => openTradeStatus(row).rowClass
    );

    document.getElementById("signalTable").innerHTML = tableHtml(
        [
            { label: "处理级别", render: (row) => pillHtml(signalStatus(row).label, signalStatus(row).tone) },
            { label: "标的", render: (row) => `${safeText(row.ts_code)}<br><small>${safeText(row.name, "")}</small>` },
            { label: "信号", render: (row) => pillHtml(safeText(row.signal_type), "tone-slate") },
            { label: "时间", key: "signal_time" },
            { label: "原因", render: (row) => actionNoteHtml(safeText(row.suggestion, row.signal_type), safeText(row.trigger_reason, "--"), signalStatus(row).tone) },
        ],
        snapshot.signals?.latest_items || [],
        "暂无历史信号",
        (row) => signalStatus(row).rowClass
    );

    document.getElementById("secondaryLaunchReviewTable").innerHTML = tableHtml(
        [
            {
                label: "状态",
                render: (row) => row.has_buy_signal
                    ? pillHtml("已触发", "tone-green")
                    : pillHtml("被拦截", ["near_high_supply", "afternoon_threshold", "market_gate_weak"].includes(String(row.blocker_tag || "")) ? "tone-red" : "tone-amber"),
            },
            { label: "标的", render: (row) => `${safeText(row.ts_code)}<br><small>${safeText(row.name, "")}</small>` },
            { label: "触发/拦截类型", render: (row) => pillHtml(safeText(row.signal_type || row.blocker_label || row.blocker_tag || "未分类"), "tone-slate") },
            { label: "时间", render: (row) => safeText(row.trigger_time, "--") },
            {
                label: "结论",
                render: (row) => actionNoteHtml(
                    row.has_buy_signal ? "已触发买点" : safeText(row.not_pushed_reason, "未触发"),
                    row.has_buy_signal ? safeText(row.push_reason, "--") : safeText(row.blocker_detail || row.not_pushed_reason, "--"),
                    row.has_buy_signal ? "tone-green" : "tone-amber"
                ),
            },
            { label: "置信度", render: (row) => formatNumber(row.confidence || 0, 2) },
        ],
        snapshot.secondary_launch_tracking?.review_rows || [],
        "暂无二次启动拦截复盘数据"
    );

    document.getElementById("feedbackTable").innerHTML = tableHtml(
        [
            { label: "来源", key: "label" },
            { label: "窗口", render: (row) => `T+${row.horizon}` },
            { label: "样本", render: (row) => formatNumber(row.sample_count) },
            { label: "胜率", render: (row) => formatPercent(row.win_rate_pct) },
            { label: "净收益", render: (row) => `<span class="${signClass(row.mean_net_return_pct)}">${formatPercent(row.mean_net_return_pct)}</span>` },
        ],
        snapshot.feedback?.summary_rows || [],
        "暂无反馈摘要"
    );

    document.getElementById("incidentTable").innerHTML = tableHtml(
        [
            { label: "时间", key: "incident_time" },
            { label: "级别", render: (row) => pillHtml(safeText(row.severity, "warning"), severityTone(row.severity)) },
            { label: "组件", key: "component" },
            { label: "标题", key: "title" },
        ],
        snapshot.health?.recent_incidents || [],
        "暂无运行告警"
    );
}

async function loadSnapshot() {
    const response = await fetch("/api/dashboard/snapshot");
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }

    const snapshot = await response.json();
    renderSnapshot(snapshot);
}

async function executeDashboardAction(action, payload = {}, confirmed = false) {
    if (!actionLoading || actionLoading === false) {
        actionLoading = true;
    }
    try {
        const response = await fetch("/api/dashboard/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action, payload, confirmed }),
        });
        const result = await response.json();
        if (!response.ok || result.success === false) {
            throw new Error(result.message || `动作执行失败: ${response.status}`);
        }
        if (result.snapshot) {
            renderSnapshot(result.snapshot);
        } else {
            await loadSnapshot();
        }
        showActionFeedback("操作已完成", result.message || "已更新最新状态。");
        const stageTarget = result.payload?.stage_target;
        if (stageTarget) {
            activateStage(stageTarget);
        }
        loadTasks().catch(console.error);
    } finally {
        actionLoading = false;
    }
}

function bindStageNav() {
    document.querySelectorAll("[data-stage-target]").forEach((button) => {
        button.addEventListener("click", () => {
            activateStage(button.dataset.stageTarget);
        });
    });
}

function bindActionButtons() {
    document.getElementById("todayBoardActions").addEventListener("click", (event) => {
        const button = event.target.closest("[data-action]");
        if (!button) return;
        executeDashboardAction(button.dataset.action).catch((error) => {
            console.error(error);
            showActionFeedback("操作失败", error.message || "请稍后重试。");
        });
    });
    ["preMarketActionButton", "intradayActionButton", "intradayRefreshButton", "postMarketActionButton"].forEach((id) => {
        const button = document.getElementById(id);
        if (!button) return;
        button.addEventListener("click", () => {
            executeDashboardAction(button.dataset.action).catch((error) => {
                console.error(error);
                showActionFeedback("操作失败", error.message || "请稍后重试。");
            });
        });
    });

    document.querySelectorAll(".ops-action-btn").forEach((button) => {
        button.addEventListener("click", () => {
            const confirmMessage = button.dataset.confirmMessage;
            const confirmed = confirmMessage ? window.confirm(confirmMessage) : false;
            if (confirmMessage && !confirmed) return;
            const payload = ["push_selection_wecom", "push_review_wecom"].includes(button.dataset.action)
                ? getWecomStrategyPayload()
                : {};
            executeDashboardAction(button.dataset.action, payload, confirmed).catch((error) => {
                console.error(error);
                showActionFeedback("操作失败", error.message || "请稍后重试。");
            });
        });
    });

    const saveHoldingButton = document.getElementById("saveHoldingButton");
    if (saveHoldingButton) {
        saveHoldingButton.addEventListener("click", () => {
            const form = document.getElementById("holdingForm");
            const formData = new FormData(form);
            const payload = Object.fromEntries(formData.entries());
            executeDashboardAction("update_holding", payload).catch((error) => {
                console.error(error);
                showActionFeedback("操作失败", error.message || "请稍后重试。");
            });
        });
    }

    const removeHoldingButton = document.getElementById("removeHoldingButton");
    if (removeHoldingButton) {
        removeHoldingButton.addEventListener("click", () => {
            const form = document.getElementById("holdingForm");
            const formData = new FormData(form);
            const payload = Object.fromEntries(formData.entries());
            if (!window.confirm("确认删除该持仓吗？")) return;
            executeDashboardAction("remove_holding", payload, true).catch((error) => {
                console.error(error);
                showActionFeedback("操作失败", error.message || "请稍后重试。");
            });
        });
    }
}

function resetAutoRefresh() {
    if (refreshTimer) {
        clearInterval(refreshTimer);
        refreshTimer = null;
    }
    const seconds = Number(document.getElementById("refreshSelect").value || 0);
    if (seconds > 0) {
        refreshTimer = setInterval(() => {
            loadSnapshot().catch(console.error);
        }, seconds * 1000);
    }
}

function resetTaskRefresh() {
    if (taskTimer) {
        clearInterval(taskTimer);
        taskTimer = null;
    }
    taskTimer = setInterval(() => {
        loadTasks().catch(console.error);
    }, 10000);
}

function bindEvents() {
    bindStageNav();
    bindActionButtons();
    document.getElementById("refreshButton").addEventListener("click", () => {
        loadSnapshot().catch(console.error);
        loadTasks().catch(console.error);
    });
    document.getElementById("refreshSelect").addEventListener("change", resetAutoRefresh);
    window.addEventListener("resize", () => {
        Object.values(charts).forEach((chart) => chart.resize());
    });
}

document.addEventListener("DOMContentLoaded", async () => {
    bindEvents();
    resetAutoRefresh();
    resetTaskRefresh();
    try {
        await loadSnapshot();
        await loadTasks();
    } catch (error) {
        console.error(error);
        document.getElementById("heroStatusLabel").textContent = "加载失败";
        document.getElementById("heroStatusDetail").textContent = "请检查数据库或缓存文件是否可以读取。";
        document.getElementById("commandCard").className = "brief-card brief-card-primary tone-red";
        document.getElementById("commandCard").innerHTML = briefCardHtml({
            kicker: "加载异常",
            title: "看板暂时不可用",
            value: "请检查",
            body: "当前快照无法加载。先检查数据库路径、缓存文件和后端服务状态。",
            pills: ["Dashboard API 失败"],
            points: ["如果是首次启动，先确认 dashboard.py 已正常运行。"],
        }, true);
    }
});
