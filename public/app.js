"use strict";

const state = {
    session: null,
    qrTimer: null,
    qrActive: false,
    qrRetries: 0,
    qrInterval: 2,
    runnerTimer: null,
    delayTimer: null,
    disconnected: false,
    keyMask: "",
    historySig: "",
    pendingTempt: null,
    pendingBurn: null,
    temptSeq: 0,
    burnSeq: 0,
};

const TOTAL_TURNS = 78;
const CONNECTION_LOST = "Connection lost. Reconnecting...";
const STATUS_NO_CAREER = "No Grand Live career. Start one in-game.";
const STATUS_FINISHED = "Career finished. Start a new one in-game.";
const CAREER_STATUS_MESSAGES = [STATUS_NO_CAREER, STATUS_FINISHED];
const STEAM_TOKEN_KEY = "sweepy_steam_token";
const BRAIN_KEY_KEY = "sweepy_brain_key";
const DEVICE_STATE_KEY = "sweepy_device_state";

function readSteamToken() {
    try {
        return localStorage.getItem(STEAM_TOKEN_KEY) || "";
    } catch {
        return "";
    }
}

function saveSteamToken(token) {
    try {
        if (token) {
            localStorage.setItem(STEAM_TOKEN_KEY, token);
        } else {
            localStorage.removeItem(STEAM_TOKEN_KEY);
        }
    } catch {
    }
}

function readBrainKey() {
    try {
        return localStorage.getItem(BRAIN_KEY_KEY) || "";
    } catch {
        return "";
    }
}

function saveBrainKey(key) {
    try {
        if (key) {
            localStorage.setItem(BRAIN_KEY_KEY, key);
        } else {
            localStorage.removeItem(BRAIN_KEY_KEY);
        }
    } catch {
    }
}

function readDeviceState() {
    try {
        const raw = localStorage.getItem(DEVICE_STATE_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch {
        return null;
    }
}

function saveDeviceState(device) {
    try {
        if (device && typeof device === "object") {
            localStorage.setItem(DEVICE_STATE_KEY, JSON.stringify(device));
        } else {
            localStorage.removeItem(DEVICE_STATE_KEY);
        }
    } catch {
    }
}

function adoptDeviceState(payload) {
    if (payload && payload.device_state) {
        saveDeviceState(payload.device_state);
    }
}

async function pushBrainKey(session) {
    const key = readBrainKey();
    if (!key || !session || !session.brain || session.brain.has_api_key) {
        return session;
    }
    try {
        await api("/api/config/brain", "POST", { api_key: key });
        return await refreshSession();
    } catch (error) {
        setFeedback("key-feedback", error.message, "err");
        return session;
    }
}

const MOOD_CLASSES = ["mood-awful", "mood-bad", "mood-normal", "mood-good", "mood-great"];
const MOOD_LABELS = ["AWFUL", "BAD", "NORMAL", "GOOD", "GREAT"];

function $(id) {
    return document.getElementById(id);
}

function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) {
        node.className = className;
    }
    if (text !== undefined && text !== null) {
        node.textContent = String(text);
    }
    return node;
}

async function api(path, method = "GET", body = null, timeoutMs = 40000) {
    const options = { method, headers: { Accept: "application/json" }, credentials: "same-origin" };
    if (body !== null) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    options.signal = controller.signal;
    let response;
    try {
        response = await fetch(path, options);
    } catch (error) {
        if (error.name === "AbortError") {
            throw new Error(`${path} timed out`);
        }
        throw error;
    } finally {
        clearTimeout(timeout);
    }
    const raw = await response.text();
    let payload = null;
    if (raw) {
        try {
            payload = JSON.parse(raw);
        } catch (error) {
            throw new Error(`Malformed JSON from ${path}: ${error.message}`);
        }
    }
    if (!response.ok) {
        const detail = payload && (payload.detail || payload.error);
        throw new Error(detail || `${path} returned HTTP ${response.status}`);
    }
    if (payload === null) {
        throw new Error(`Empty response from ${path}`);
    }
    return payload;
}

const QR_HINT_IDLE = "Login with Steam mobile app";

function setQrHint(text) {
    const node = $("qr-hint");
    if (node) {
        node.textContent = text;
    }
}

function showAuthError(message) {
    const node = $("auth-error-msg");
    if (!node) {
        return;
    }
    node.textContent = message || "";
    node.classList.toggle("is-visible", Boolean(message));
}

function setStatus(message, tone) {
    const node = $("exec-status-line");
    if (!node) {
        return;
    }
    node.textContent = message || "";
    node.classList.toggle("error", tone === "error");
    node.classList.toggle("ok", tone === "ok");
}

function setFeedback(id, message, tone) {
    const node = $(id);
    if (!node) {
        return;
    }
    node.textContent = message || "";
    node.classList.remove("ok", "err");
    if (tone) {
        node.classList.add(tone);
    }
}

function markDisconnected() {
    if (state.disconnected) {
        return;
    }
    state.disconnected = true;
    setStatus(CONNECTION_LOST, "error");
}

function markConnected() {
    if (!state.disconnected) {
        return;
    }
    state.disconnected = false;
    const node = $("exec-status-line");
    if (node && node.textContent === CONNECTION_LOST) {
        setStatus("", "");
    }
}

function hideLoading() {
    const node = $("loading-screen");
    if (node) {
        node.classList.add("hidden");
    }
}

function setToggle(id, on) {
    const node = $(id);
    if (!node) {
        return;
    }
    node.dataset.on = String(on);
    node.setAttribute("aria-checked", String(on));
    node.classList.toggle("btn-brass", on);
    node.classList.toggle("btn-quiet", !on);
    const stateNode = node.querySelector(".toggle-state");
    if (stateNode) {
        stateNode.textContent = on ? "On" : "Off";
    }
}

function pill(label, value, tone) {
    const node = make("div", `account-pill ${tone || ""}`.trim());
    node.append(make("span", "label", label));
    node.append(make("strong", null, value));
    return node;
}

function activeGrandLiveCareer(session) {
    const career = ((session && session.account) || {}).career;
    return Boolean(career && career.active && Number(career.scenario_id) === 3);
}

function showKeyMask() {
    const input = $("key-input");
    if (!input || !state.keyMask) {
        return;
    }
    input.value = state.keyMask;
    input.type = "text";
    input.dataset.masked = "1";
}

function clearKeyMask() {
    const input = $("key-input");
    if (!input || input.dataset.masked !== "1") {
        return;
    }
    input.value = "";
    input.type = "password";
    delete input.dataset.masked;
}

function renderKeyStatus(session) {
    const brain = (session && session.brain) || {};
    const online = Boolean(brain.online);
    const hasKey = Boolean(brain.has_api_key);
    const link = $("key-link");
    if (link && brain.api_url) {
        const host = String(brain.api_url).replace(/^https?:\/\//, "");
        link.href = brain.api_url;
        link.title = `Open ${host} to ${hasKey ? "manage" : "generate"} your API key`;
    }
    const badge = $("key-status-badge");
    if (badge) {
        badge.textContent = !hasKey ? "NO KEY" : online ? "ONLINE" : "OFFLINE";
        badge.className = `runner-state ${hasKey && online ? "is-running" : "is-idle"}`;
    }
    const feedback = $("key-feedback");
    const staleUnreachable = Boolean(feedback && feedback.textContent.trim() === "Unreachable.");
    if (hasKey && !online) {
        setFeedback("key-feedback", "Unreachable.", "err");
    } else if (!hasKey || staleUnreachable) {
        setFeedback("key-feedback", "", "");
    }
    state.keyMask = hasKey ? String(brain.api_key_masked || "") : "";
    const input = $("key-input");
    if (input && (input.dataset.masked === "1" || !input.value)) {
        clearKeyMask();
        showKeyMask();
    }
}

function renderCareer(session) {
    const career = (session.account || {}).career || {};
    const nameNode = $("career-name");
    if (nameNode) {
        nameNode.textContent = career.active ? String(career.name || "GRAND LIVE CAREER").toUpperCase() : "NO ACTIVE CAREER";
        nameNode.classList.toggle("is-placeholder", career.active !== true);
    }
}

function renderAccountStrip(session) {
    const strip = $("account-strip");
    if (!strip) {
        return;
    }
    strip.innerHTML = "";
    if (!session.logged_in) {
        strip.style.display = "none";
        return;
    }
    strip.style.display = "flex";
    const account = session.account || {};
    const tp = account.tp || {};
    strip.append(pill("TP", `${tp.current ?? 0} / ${tp.max ?? 0}`, "pill-tp"));
    strip.append(pill("CLOCKS", `${account.clocks ?? 0}`, "pill-clk"));
}

function downloadJsonFile(payload, filename) {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename || "umadump.json";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function exportFinalTurn() {
    const btn = $("final-turn-export-btn");
    if (!btn) {
        return;
    }
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "EXPORTING…";
    try {
        const payload = await api("/api/career/final-turn-export");
        downloadJsonFile(payload.json, payload.filename);
        btn.textContent = "SAVED";
        setTimeout(() => {
            btn.textContent = label;
            btn.disabled = false;
        }, 1500);
    } catch (error) {
        setStatus(`Export failed: ${error.message}`, "error");
        btn.textContent = label;
        btn.disabled = false;
    }
}

function bindFinalTurnExport() {
    const btn = $("final-turn-export-btn");
    if (!btn || btn.dataset.bound === "1") {
        return;
    }
    btn.dataset.bound = "1";
    btn.addEventListener("click", exportFinalTurn);
}

function renderRunner(runner) {
    const exportBtn = $("final-turn-export-btn");
    if (!runner) {
        if (exportBtn) {
            exportBtn.style.display = "none";
        }
        return;
    }
    bindFinalTurnExport();
    if (exportBtn) {
        exportBtn.style.display = runner.final_turn_export_ready === true ? "" : "none";
    }
    const badge = $("hud-runner-badge");
    if (badge) {
        const status = String(runner.status || "idle").toUpperCase();
        badge.textContent = status;
        badge.classList.toggle("is-running", runner.running === true);
        badge.classList.toggle("is-finished", runner.finished === true);
        badge.classList.toggle("is-error", status === "ERROR");
    }
    const clocks = $("hud-clocks-used");
    if (clocks) {
        clocks.textContent = String(runner.clocks_used ?? 0);
    }
    const hasData = Number(runner.turn ?? 0) > 0;
    const shown = (value) => (hasData ? String(value) : "—");
    const turn = $("hud-turn-val");
    if (turn) {
        turn.textContent = hasData ? `${runner.turn ?? 0} / ${TOTAL_TURNS}` : `— / ${TOTAL_TURNS}`;
    }
    const stats = runner.stats || {};
    const hpText = $("hud-hp-text");
    if (hpText) {
        hpText.textContent = hasData ? `${stats.hp ?? 0} / ${stats.max_hp ?? 100}` : "— / —";
    }
    const hpFill = $("hud-hp-fill");
    if (hpFill) {
        const max = Number(stats.max_hp ?? 100) || 100;
        const pct = Math.max(0, Math.min(100, (Number(stats.hp ?? 0) / max) * 100));
        hpFill.style.width = hasData ? `${pct}%` : "0%";
    }
    const moodBadge = $("hud-mood-badge");
    if (moodBadge) {
        for (const cls of MOOD_CLASSES) {
            moodBadge.classList.remove(cls);
        }
        if (hasData) {
            const mood = Math.max(1, Math.min(5, Number(stats.mood ?? 3)));
            moodBadge.textContent = MOOD_LABELS[mood - 1];
            moodBadge.classList.add(MOOD_CLASSES[mood - 1]);
        } else {
            moodBadge.textContent = "—";
        }
    }
    const lastAction = $("hud-last-action");
    if (lastAction) {
        lastAction.textContent = runner.last_action || "WAITING";
    }
    const mapping = { spd: "speed", sta: "stamina", pwr: "power", gut: "guts", wit: "wit", sp: "sp", fans: "fans" };
    for (const [key, field] of Object.entries(mapping)) {
        const node = $(`stat-val-${key}`);
        if (node) {
            node.textContent = shown(stats[field] ?? 0);
        }
    }
    const tokens = runner.tokens || {};
    for (const key of ["da", "pa", "vo", "vi", "me"]) {
        const node = $(`tok-val-${key}`);
        if (node) {
            node.textContent = shown(tokens[key] ?? 0);
        }
    }
    renderGrandLive(runner);
    renderHistory(runner.history || []);
    renderResult(runner.result);
    renderError(runner.error);
    const runBtn = $("run-career-btn");
    const stopBtn = $("stop-career-btn");
    if (runBtn) {
        runBtn.disabled = runner.running === true || !state.session || !state.session.logged_in || !activeGrandLiveCareer(state.session);
    }
    if (stopBtn) {
        stopBtn.disabled = runner.running !== true;
    }
}

function renderGrandLive(runner) {
    const turn = Math.max(0, Math.min(TOTAL_TURNS, Number(runner.turn ?? 0)));
    const tokens = runner.tokens || {};
    const keys = ["da", "pa", "vo", "vi", "me"];
    const values = keys.map((key) => Number(tokens[key] ?? 0));
    const scale = Math.max(1, ...values);
    for (const [i, key] of keys.entries()) {
        const fill = $(`tok-fill-${key}`);
        if (!fill) {
            continue;
        }
        fill.style.width = `${Math.min(100, (values[i] / scale) * 100)}%`;
    }
    const turnText = $("gl-turn");
    if (turnText) {
        turnText.textContent = `${turn} / ${TOTAL_TURNS}`;
    }
    const turnFill = $("gl-turn-fill");
    if (turnFill) {
        turnFill.style.width = `${(turn / TOTAL_TURNS) * 100}%`;
    }
}

function renderHistory(history) {
    const body = $("turn-log-tbody");
    if (!body) {
        return;
    }
    const signature = history.map((entry) => `${entry.turn}|${entry.kind}|${entry.action}`).join("\n");
    if (signature === state.historySig) {
        return;
    }
    state.historySig = signature;
    const wrap = $("turn-log-wrap");
    const pinned = !wrap || wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight < 40;
    body.innerHTML = "";
    if (!history.length) {
        const row = make("tr", "log-empty-row");
        const cell = make("td", null, "NO TURNS YET");
        cell.colSpan = 3;
        row.append(cell);
        body.append(row);
        return;
    }
    for (const entry of history) {
        const row = document.createElement("tr");
        row.append(make("td", "col-turn", entry.turn ?? ""));
        row.append(make("td", "col-kind", entry.kind ?? ""));
        row.append(make("td", "col-action", entry.action ?? ""));
        body.append(row);
    }
    if (wrap && pinned) {
        wrap.scrollTop = wrap.scrollHeight;
    }
}

function renderResult(result) {
    const banner = $("hud-result-banner");
    if (!banner) {
        return;
    }
    if (!result) {
        banner.style.display = "none";
        banner.textContent = "";
        return;
    }
    banner.style.display = "flex";
    if (result.reason === "career_complete") {
        banner.textContent = `FINISHED · CAREER COMPLETE · TURN ${result.turn ?? "?"}`;
    } else if (result.rank != null || result.rank_score != null) {
        banner.textContent = `FINISHED · SCORE ${result.rank_score ?? "?"} · RANK ${result.rank ?? "?"}`;
    } else {
        banner.textContent = `FINISHED · ${String(result.reason || "DONE").toUpperCase()}`;
    }
}

function renderError(message) {
    const banner = $("hud-error-banner");
    if (!banner) {
        return;
    }
    if (!message) {
        banner.style.display = "none";
        banner.textContent = "";
        return;
    }
    banner.style.display = "block";
    banner.textContent = message;
}

async function startQr() {
    clearTimeout(state.qrTimer);
    setQrHint(QR_HINT_IDLE);
    const box = $("qr-svg-box");
    if (box) {
        box.innerHTML = "";
        box.append(make("div", "qr-placeholder", "Requesting code..."));
    }
    showAuthError("");
    try {
        const response = await api("/api/auth/qr/start", "POST", {});
        if (box) {
            box.innerHTML = "";
            box.insertAdjacentHTML("afterbegin", response.qr_svg);
        }
        state.qrActive = true;
        state.qrRetries = 0;
        state.qrInterval = Number(response.interval) || 2;
        scheduleQrPoll(state.qrInterval);
    } catch (error) {
        state.qrActive = false;
        state.qrRetries += 1;
        setQrHint(QR_HINT_IDLE);
        showAuthError(error.message);
        if (state.qrRetries <= 3) {
            clearTimeout(state.qrTimer);
            state.qrTimer = setTimeout(startQr, 1500 * state.qrRetries);
        }
    }
}

function scheduleQrPoll(seconds) {
    clearTimeout(state.qrTimer);
    state.qrTimer = setTimeout(pollQr, Math.max(1, seconds) * 1000);
}

async function pollQr() {
    if (!state.qrActive) {
        return;
    }
    try {
        const response = await api("/api/auth/qr/poll", "POST", {}, 120000);
        if (response.status === "approved" || response.logged_in === true) {
            state.qrActive = false;
            setQrHint("Signing in");
            saveSteamToken(response.refresh_token || "");
            adoptDeviceState(response);
            await refreshSession();
            return;
        }
        const qrState = String(response.status || "pending").toLowerCase();
        if (qrState === "expired" || qrState === "refused") {
            state.qrActive = false;
            clearTimeout(state.qrTimer);
            state.qrTimer = setTimeout(startQr, 1200);
            return;
        }
        if (response.qr_svg) {
            const box = $("qr-svg-box");
            if (box) {
                box.innerHTML = "";
                box.insertAdjacentHTML("afterbegin", response.qr_svg);
            }
            setQrHint("Code refreshed, scan the new one");
        } else {
            setQrHint("Waiting for Steam approval");
        }
        if (Number(response.interval) > 0) {
            state.qrInterval = Number(response.interval);
        }
        state.qrRetries = 0;
        scheduleQrPoll(state.qrInterval);
    } catch (error) {
        state.qrRetries += 1;
        if (state.qrRetries > 3) {
            state.qrActive = false;
            showAuthError(error.message);
            return;
        }
        showAuthError(error.message);
        scheduleQrPoll(state.qrInterval * state.qrRetries);
    }
}

async function logout() {
    state.qrActive = false;
    clearTimeout(state.qrTimer);
    saveSteamToken("");
    saveBrainKey("");
    saveDeviceState(null);
    try {
        await api("/api/logout", "POST", {});
        const session = await refreshSession();
        if (!session.logged_in) {
            await startQr();
        }
    } catch (error) {
        showAuthError(error.message);
    }
}

async function saveKey() {
    const key = $("key-input").value.trim();
    if (!key || key === state.keyMask) {
        return;
    }
    setFeedback("key-feedback", "Saving...", "");
    try {
        await api("/api/config/brain", "POST", { api_key: key });
        saveBrainKey(key);
        delete $("key-input").dataset.masked;
        $("key-input").value = "";
        $("key-input").type = "password";
        setFeedback("key-feedback", "", "");
        await refreshSession();
    } catch (error) {
        setFeedback("key-feedback", error.message, "err");
    }
}

async function startCareer() {
    if (!state.session) {
        return;
    }
    if (!activeGrandLiveCareer(state.session)) {
        return;
    }
    try {
        const response = await api("/api/career/run", "POST", {
            burn_clocks: Boolean(state.session.burn_clocks),
        });
        if (state.session) {
            state.session.runner = response.runner;
        }
        renderRunner(response.runner);
        startRunnerPolling();
    } catch (error) {
        setStatus(`Run failed: ${error.message}`, "error");
        refreshSession().catch(() => markDisconnected());
    }
}

async function stopCareer() {
    try {
        const response = await api("/api/career/runner/stop", "POST", {});
        if (state.session) {
            state.session.runner = response.runner;
        }
        renderRunner(response.runner);
    } catch (error) {
        setStatus(`Stop failed: ${error.message}`, "error");
    }
}

function paintDelay(delay) {
    const config = delay || {};
    const min = $("turn-delay-min");
    const max = $("turn-delay-max");
    if (!min || !max) {
        return;
    }
    min.value = Number(config.restore_min ?? config.min ?? 1.6).toFixed(1);
    max.value = Number(config.restore_max ?? config.max ?? 3.7).toFixed(1);
    min.disabled = Boolean(config.disabled);
    max.disabled = Boolean(config.disabled);
}

async function setTurnDelay() {
    const current = (state.session && state.session.turn_delay) || {};
    if (current.disabled) {
        return;
    }
    const min = Number($("turn-delay-min").value);
    const max = Number($("turn-delay-max").value);
    try {
        const saved = await api("/api/settings/turn-delay", "POST", { min, max, disabled: false });
        if (state.session) {
            state.session.turn_delay = saved.turn_delay || saved;
        }
        paintDelay(state.session && state.session.turn_delay);
    } catch (error) {
        setStatus(`Delay update failed: ${error.message}`, "error");
    }
}

function paintTemptFate(on) {
    $("tempt-fate-btn").dataset.enabled = String(on);
    setToggle("tempt-fate-btn", on);
}

function paintBurnClocks(on) {
    setToggle("burn-clocks-btn", on);
}

async function toggleTemptFate() {
    const button = $("tempt-fate-btn");
    const next = button.dataset.enabled !== "true";
    const delay = (state.session && state.session.turn_delay) || {};
    const body = next
        ? { min: 0, max: 0, disabled: true }
        : {
            min: Number(delay.restore_min ?? 1.6),
            max: Number(delay.restore_max ?? 3.7),
            disabled: false,
        };
    const seq = ++state.temptSeq;
    state.pendingTempt = next;
    paintTemptFate(next);
    try {
        const saved = await api("/api/settings/turn-delay", "POST", body);
        if (seq !== state.temptSeq) {
            return;
        }
        state.pendingTempt = null;
        const delayCfg = saved.turn_delay || saved;
        if (state.session) {
            state.session.turn_delay = delayCfg;
        }
        paintTemptFate(Boolean(delayCfg.disabled));
        paintDelay(delayCfg);
    } catch (error) {
        if (seq === state.temptSeq) {
            state.pendingTempt = null;
            paintTemptFate(!next);
            setStatus(`Tempt fate: ${error.message}`, "error");
        }
    }
}

async function toggleBurnClocks() {
    if (!state.session) {
        return;
    }
    const next = !state.session.burn_clocks;
    const seq = ++state.burnSeq;
    state.session.burn_clocks = next;
    state.pendingBurn = next;
    paintBurnClocks(next);
    try {
        const response = await api("/api/career/runner/burn_clocks", "POST", { burn_clocks: next });
        if (seq === state.burnSeq) {
            state.pendingBurn = null;
            state.session.burn_clocks = Boolean(response.burn_clocks);
            paintBurnClocks(Boolean(response.burn_clocks));
        }
    } catch (error) {
        if (seq === state.burnSeq) {
            state.pendingBurn = null;
            state.session.burn_clocks = !next;
            paintBurnClocks(!next);
            setStatus(`Burn clocks failed: ${error.message}`, "error");
        }
    }
}


function applySession(session) {
    state.session = session;
    if (state.pendingTempt !== null && session.turn_delay) {
        session.turn_delay.disabled = state.pendingTempt;
    }
    if (state.pendingBurn !== null) {
        session.burn_clocks = state.pendingBurn;
    }
    const keySeed = (session.brain || {}).api_key_seed || "";
    if (keySeed && !readBrainKey()) {
        saveBrainKey(keySeed);
    }
    adoptDeviceState(session);
    const logged = Boolean(session.logged_in);
    document.body.classList.toggle("pre-login", !logged);
    const loginView = $("login-view");
    const dashView = $("dashboard-view");
    if (loginView) {
        loginView.style.display = logged ? "none" : "flex";
    }
    if (dashView) {
        dashView.classList.toggle("active", logged);
    }
    renderKeyStatus(session);
    if (logged) {
        const delay = session.turn_delay || {};
        if (state.pendingTempt === null) {
            paintDelay(delay);
            paintTemptFate(Boolean(delay.disabled));
        }
        if (state.pendingBurn === null) {
            paintBurnClocks(Boolean(session.burn_clocks));
        }
        renderAccountStrip(session);
        renderCareer(session);
        renderRunner(session.runner);
        const career = (session.account || {}).career;
        if (!activeGrandLiveCareer(session)) {
            if (career && career.active) {
                setStatus(`Career scenario ${career.scenario_id}, not Grand Live.`, "error");
            } else if ((session.runner || {}).finished === true) {
                setStatus(STATUS_FINISHED, "ok");
            } else {
                setStatus(STATUS_NO_CAREER, "");
            }
        } else {
            const statusNode = $("exec-status-line");
            const statusText = statusNode ? statusNode.textContent || "" : "";
            if (CAREER_STATUS_MESSAGES.includes(statusText) || statusText.startsWith("Career scenario ")) {
                setStatus("", "");
            }
        }
    } else {
        renderAccountStrip(session);
    }
}

async function refreshSession(fresh) {
    let session;
    try {
        session = await api(fresh ? "/api/session?fresh=1" : "/api/session");
    } catch (error) {
        markDisconnected();
        throw error;
    }
    applySession(session);
    markConnected();
    return session;
}

function startRunnerPolling() {
    if (state.runnerTimer) {
        return;
    }
    state.runnerTimer = setInterval(async () => {
        const runner = state.session && state.session.runner;
        if (!state.session || !state.session.logged_in || !runner || runner.running !== true) {
            return;
        }
        try {
            const response = await api("/api/career/runner");
            markConnected();
            renderRunner(response.runner);
            if (response.runner && response.runner.running !== true) {
                await refreshSession(true);
            }
            if (state.session) {
                state.session.runner = response.runner;
                state.session.account = response.account || state.session.account;
                renderAccountStrip(state.session);
                renderCareer(state.session);
            }
        } catch {
            markDisconnected();
        }
    }, 1200);
}

function bindStatic() {
    $("logout-btn").addEventListener("click", logout);
    $("qr-refresh-btn").addEventListener("click", startQr);
    $("key-save-btn").addEventListener("click", saveKey);
    $("key-input").addEventListener("focus", clearKeyMask);
    $("key-input").addEventListener("blur", () => {
        if (!$("key-input").value) {
            showKeyMask();
        }
    });
    $("key-input").addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            saveKey();
        }
    });
    $("run-career-btn").addEventListener("click", startCareer);
    $("stop-career-btn").addEventListener("click", stopCareer);
    $("turn-delay-min").addEventListener("change", () => {
        clearTimeout(state.delayTimer);
        state.delayTimer = setTimeout(setTurnDelay, 400);
    });
    $("turn-delay-max").addEventListener("change", () => {
        clearTimeout(state.delayTimer);
        state.delayTimer = setTimeout(setTurnDelay, 400);
    });
    $("tempt-fate-btn").addEventListener("click", toggleTemptFate);
    $("burn-clocks-btn").addEventListener("click", toggleBurnClocks);
}

async function init() {
    bindStatic();
    try {
        let session = await refreshSession(true);
        if (!session.logged_in) {
            try {
                const restored = await api("/api/auth/restore", "POST", {
                    refresh_token: readSteamToken(),
                    api_key: readBrainKey(),
                    device: readDeviceState(),
                });
                adoptDeviceState(restored);
                session = await refreshSession();
            } catch (error) {
                showAuthError(error.message);
            }
        }
        session = await pushBrainKey(session);
        if (!session.logged_in) {
            startQr();
        }
        startRunnerPolling();
    } catch (error) {
        markDisconnected();
        showAuthError(`Session load failed: ${error.message}`);
    } finally {
        hideLoading();
    }
}

document.addEventListener("DOMContentLoaded", init);

document.addEventListener("visibilitychange", () => {
    if (!document.hidden && state.session && state.session.logged_in) {
        refreshSession().catch(() => markDisconnected());
    }
});
