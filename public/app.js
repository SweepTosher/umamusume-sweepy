"use strict";

const state = {
    session: null,
    qrTimer: null,
    qrActive: false,
    qrPollInFlight: false,
    qrRetries: 0,
    qrInterval: 2,
    authTab: null,
    authConnecting: false,
    credTimer: null,
    credPollActive: false,
    credPollInFlight: false,
    credRetries: 0,
    credInterval: 3,
    runnerTimer: null,
    runnerPollInFlight: false,
    delayTimer: null,
    disconnected: false,
    keyMask: "",
    historySig: "",
    pendingTempt: null,
    pendingBurn: null,
    pendingCmMode: null,
    temptSeq: 0,
    burnSeq: 0,
    cmSeq: 0,
    cmCatalog: null,
    cmConfig: null,
    veterans: [],
    mateQuery: "",
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
        const err = new Error(detail || `${path} returned HTTP ${response.status}`);
        err.status = response.status;
        throw err;
    }
    if (payload === null) {
        throw new Error(`Empty response from ${path}`);
    }
    return payload;
}

const QR_HINT_IDLE = "Scan with Steam Mobile app";

function isAndroidBrowser() {
    return /Android/i.test(navigator.userAgent || "");
}

function defaultAuthTab(session) {
    if (!session || !session.password_auth) {
        return "qr";
    }
    return isAndroidBrowser() ? "credentials" : "qr";
}

function setStatusDots(node, label, options) {
    if (!node) {
        return;
    }
    const opts = options || {};
    const visible = opts.visible !== undefined ? Boolean(opts.visible) : true;
    const clean = label ? String(label) : "";
    node.hidden = !visible;
    node.classList.toggle("is-connecting", Boolean(opts.connecting));
    node.textContent = clean;
    if (clean && opts.animated) {
        for (let i = 0; i < 3; i += 1) {
            node.append(make("span", "dot", "."));
        }
    }
}

function setQrHint(text, options) {
    setStatusDots($("qr-hint"), text, options);
}

function setGuardStatus(text, options) {
    setStatusDots($("guard-status"), text, options);
}

function nextPollDelaySec(interval, interacted) {
    const parsed = Number(interval);
    const base = parsed > 0 ? parsed : 2;
    return interacted ? 1 : Math.min(2, Math.max(1.5, base));
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

const APT_GRADES = ["—", "G", "F", "E", "D", "C", "B", "A", "S"];
const STYLE_SHORT = ["Auto", "Front", "Pace", "Late", "End", "Runaway"];
const TURN_SHORT = { 1: "Right", 2: "Left", 4: "Straight" };
const INOUT_SHORT = { 1: "Inner", 2: "Outer" };

function defaultCmConfig() {
    return {
        cm_mode: false,
        cm_preset: "sagittarius",
        cm_course: "sagittarius",
        track: "Nakayama",
        distance: 2500,
        ground: 1,
        ground_condition: 1,
        weather: 1,
        season: 4,
        course_id: 10506,
        inout: 1,
        cm_role: 0,
        cm_target: "carry",
        cm_style: 0,
        mate_ids: [null, null],
        mate_roles: ["auto", "auto"],
        mate_snapshots: [null, null],
    };
}

function getCmConfig(session) {
    const base = defaultCmConfig();
    const raw = (state.cmConfig || (session && session.cm_config)) || {};
    const merged = { ...base, ...raw };
    if (state.pendingCmMode !== null) {
        merged.cm_mode = state.pendingCmMode;
    }
    return merged;
}

function isCmSupportBlocked(session) {
    const activeSession = session || state.session;
    if (!activeSession || !activeSession.cm_enabled) {
        return false;
    }
    const cfg = getCmConfig(activeSession);
    if (!cfg.cm_mode) {
        return false;
    }
    const role = Number(cfg.cm_role);
    const needTwo = role === 2 || role === 3 || (role === 1 && String(cfg.cm_target || "carry") === "debuffer");
    if (!needTwo) {
        return false;
    }
    const ids = (cfg.mate_ids || []).filter((v) => v !== null && v !== undefined && Number(v) > 0).map(Number);
    return new Set(ids).size < 2;
}

function paintCmModeToggle(on) {
    setToggle("cm-mode-btn", Boolean(on));
}

function labelForOption(list, id, fallback) {
    const found = (list || []).find((x) => Number(x.id) === Number(id));
    return found ? found.label : fallback;
}

function renderPillGroup(containerId, items, activeId, onPick) {
    const host = $(containerId);
    if (!host) {
        return;
    }
    host.innerHTML = "";
    for (const item of items) {
        const active = String(item.id) === String(activeId);
        const btn = make("button", `btn cm-pill ${active ? "btn-brass" : "btn-quiet"}`, item.label);
        btn.type = "button";
        btn.disabled = Boolean(item.disabled);
        btn.setAttribute("aria-pressed", String(active));
        if (!btn.disabled) {
            btn.addEventListener("click", () => onPick(item.id));
        }
        host.append(btn);
    }
}

function coursesForTrackAndGround(courses, track, ground) {
    return (courses || []).filter((c) => c.track === track && Number(c.ground) === Number(ground));
}

function findMatchingPreset(presets, cfg) {
    return (presets || []).find(
        (p) =>
            p.track === cfg.track &&
            Number(p.ground) === Number(cfg.ground) &&
            Number(p.distance) === Number(cfg.distance) &&
            Number(p.ground_condition) === Number(cfg.ground_condition) &&
            Number(p.weather) === Number(cfg.weather) &&
            Number(p.season) === Number(cfg.season) &&
            (!p.course_id || !cfg.course_id || Number(p.course_id) === Number(cfg.course_id))
    );
}

function formatVeteranOption(v) {
    const st = STYLE_SHORT[Number(v.running_style || 2)] || "?";
    const s = v.stats || [0, 0, 0, 0, 0];
    return `${v.name} · ${v.rank_score} pts · ${st} (${s.join("/")})`;
}

function formatVeteranSummary(v) {
    if (!v) {
        return "None selected";
    }
    const st = STYLE_SHORT[Number(v.running_style || 2)] || "?";
    const s = v.stats || [0, 0, 0, 0, 0];
    const gr = v.proper_ground || [1, 1];
    const ds = v.proper_distance || [1, 1, 1, 1];
    const gTxt = `Turf:${APT_GRADES[gr[0]] || "?"} Dirt:${APT_GRADES[gr[1]] || "?"}`;
    const dTxt = `S:${APT_GRADES[ds[0]] || "?"} M:${APT_GRADES[ds[1]] || "?"} Md:${APT_GRADES[ds[2]] || "?"} L:${APT_GRADES[ds[3]] || "?"}`;
    return `Rank ${v.rank_score} · ${st} · Spd ${s[0]} Sta ${s[1]} Pow ${s[2]} Gut ${s[3]} Wit ${s[4]} · ${gTxt} · ${dTxt} · ${v.skill_count} skills`;
}

async function saveCmConfig(patch) {
    const prev = getCmConfig(state.session);
    const next = { ...prev, ...patch };
    const catalog = state.cmCatalog || {};
    const matched = findMatchingPreset(catalog.presets || [], next);
    if (!("cm_preset" in patch)) {
        next.cm_preset = matched ? matched.slug : "custom";
    }
    next.cm_course = {
        track: next.track,
        distance: Number(next.distance),
        ground: Number(next.ground),
        ground_condition: Number(next.ground_condition),
        weather: Number(next.weather),
        season: Number(next.season),
        course_id: next.course_id ? Number(next.course_id) : null,
        inout: Number(next.inout || 1),
    };
    state.cmConfig = next;
    if (state.session) {
        state.session.cm_config = next;
    }
    renderCmPanel(state.session);
    renderRunner((state.session || {}).runner);
    const seq = ++state.cmSeq;
    try {
        const res = await api("/api/settings/cm", "POST", next);
        if (seq !== state.cmSeq) {
            return;
        }
        state.pendingCmMode = null;
        if (res && res.cm_config) {
            state.cmConfig = res.cm_config;
            if (state.session) {
                state.session.cm_config = res.cm_config;
            }
            renderCmPanel(state.session);
            renderRunner((state.session || {}).runner);
        }
    } catch (error) {
        if (seq === state.cmSeq) {
            state.pendingCmMode = null;
            setStatus(`CM config failed: ${error.message}`, "error");
        }
    }
}

function toggleCmMode() {
    const cfg = getCmConfig(state.session);
    const next = !Boolean(cfg.cm_mode);
    state.pendingCmMode = next;
    saveCmConfig({ cm_mode: next });
}

function renderCmPanel(session) {
    const cmEnabled = Boolean(session && session.cm_enabled);
    const cmBtn = $("cm-mode-btn");
    if (cmBtn) {
        cmBtn.style.display = cmEnabled ? "" : "none";
    }
    const panel = $("cm-panel");
    if (!cmEnabled) {
        paintCmModeToggle(false);
        if (panel) {
            panel.style.display = "none";
        }
        return;
    }
    const cfg = getCmConfig(session);
    paintCmModeToggle(cfg.cm_mode);
    if (!panel) {
        return;
    }
    panel.style.display = cfg.cm_mode ? "" : "none";
    if (!cfg.cm_mode) {
        return;
    }

    const catalog = state.cmCatalog || ((session || {}).cm_catalog) || {};
    const presets = catalog.presets || [];
    const courses = catalog.courses || [];
    const tracks = catalog.tracks || [cfg.track];

    const summaryPill = $("cm-summary-pill");
    if (summaryPill) {
        const surfTxt = Number(cfg.ground) === 2 ? "Dirt" : "Turf";
        const gcTxt = labelForOption(catalog.ground_conditions, cfg.ground_condition, "Firm");
        const wTxt = labelForOption(catalog.weathers, cfg.weather, "Sunny");
        const sTxt = labelForOption(catalog.seasons, cfg.season, "Winter");
        const mTxt = Number(cfg.cm_role) === 1 && String(cfg.cm_target || "carry") === "debuffer"
            ? "Ace (Debuffer)"
            : labelForOption(catalog.modes, cfg.cm_role, "Solo");
        summaryPill.textContent = `${cfg.track} ${cfg.distance}m ${surfTxt} · ${gcTxt} · ${wTxt} · ${sTxt} · ${mTxt}`;
    }

    const brain = (session && session.brain) || {};
    const brainBadge = $("cm-brain-badge");
    const brainWarn = $("cm-brain-warning");
    const hCm = brain.health && typeof brain.health.cm_mode === "boolean" ? brain.health.cm_mode : null;
    const hHasCm = brain.health && typeof brain.health.has_cm_model === "boolean" ? brain.health.has_cm_model : hCm;
    if (brainBadge) {
        if (!brain.online) {
            brainBadge.textContent = "OFFLINE";
            brainBadge.className = "runner-state is-idle";
        } else if (hCm === true) {
            brainBadge.textContent = "CM MODEL";
            brainBadge.className = "runner-state is-finished";
        } else if (hHasCm === true) {
            brainBadge.textContent = "CM + SCORE READY";
            brainBadge.className = "runner-state is-finished";
        } else {
            brainBadge.textContent = "SCOREMAXXER";
            brainBadge.className = "runner-state is-error";
        }
    }
    if (brainWarn) {
        if (brain.online && hCm === false && hHasCm !== true) {
            brainWarn.style.display = "block";
            brainWarn.textContent = "Connected brain server reports cm_mode=false (Scoremaxxer checkpoint). Restart mayano-api with MAYANO_CM_MODE=1 or MAYANO_CM_MODEL_PATH to serve the CM champion.";
        } else {
            brainWarn.style.display = "none";
            brainWarn.textContent = "";
        }
    }

    const presetSel = $("cm-preset-select");
    if (presetSel) {
        presetSel.innerHTML = "";
        for (const p of presets) {
            const opt = document.createElement("option");
            opt.value = p.slug;
            opt.textContent = p.name;
            presetSel.append(opt);
        }
        const customOpt = document.createElement("option");
        customOpt.value = "custom";
        customOpt.textContent = "Custom (uma.moe)";
        presetSel.append(customOpt);
        const matched = findMatchingPreset(presets, cfg);
        presetSel.value = matched ? matched.slug : "custom";
    }

    const trackSel = $("cm-track-select");
    if (trackSel) {
        trackSel.innerHTML = "";
        for (const tr of tracks) {
            const opt = document.createElement("option");
            opt.value = tr;
            opt.textContent = tr;
            trackSel.append(opt);
        }
        trackSel.value = tracks.includes(cfg.track) ? cfg.track : tracks[0] || cfg.track;
    }

    const turfCourses = coursesForTrackAndGround(courses, cfg.track, 1);
    const dirtCourses = coursesForTrackAndGround(courses, cfg.track, 2);
    renderPillGroup(
        "cm-surface-group",
        [
            { id: 1, label: "Turf", disabled: turfCourses.length === 0 },
            { id: 2, label: "Dirt", disabled: dirtCourses.length === 0 },
        ],
        cfg.ground,
        (newGround) => {
            const avail = coursesForTrackAndGround(courses, cfg.track, newGround);
            if (!avail.length) {
                return;
            }
            const best = avail.reduce((a, b) => (Math.abs(a.distance - cfg.distance) <= Math.abs(b.distance - cfg.distance) ? a : b));
            saveCmConfig({ ground: newGround, course_id: best.course_id, distance: best.distance, inout: best.inout });
        }
    );

    const courseSel = $("cm-course-select");
    if (courseSel) {
        courseSel.innerHTML = "";
        let avail = coursesForTrackAndGround(courses, cfg.track, cfg.ground);
        if (!avail.length) {
            avail = courses.filter((c) => c.track === cfg.track);
        }
        for (const c of avail) {
            const opt = document.createElement("option");
            opt.value = String(c.course_id);
            const tLbl = TURN_SHORT[Number(c.turn)] || "";
            const ioLbl = INOUT_SHORT[Number(c.inout)] || "";
            const metaParts = [tLbl, ioLbl].filter(Boolean).join(" · ");
            opt.textContent = `${c.distance}m${metaParts ? ` · ${metaParts}` : ""} (#${c.course_id})`;
            courseSel.append(opt);
        }
        const curMatch = avail.find((c) => Number(c.course_id) === Number(cfg.course_id)) || avail[0];
        if (curMatch) {
            courseSel.value = String(curMatch.course_id);
        }
    }

    renderPillGroup("cm-gcond-group", catalog.ground_conditions || [], cfg.ground_condition, (id) => saveCmConfig({ ground_condition: id }));
    renderPillGroup("cm-weather-group", catalog.weathers || [], cfg.weather, (id) => saveCmConfig({ weather: id }));
    renderPillGroup("cm-season-group", catalog.seasons || [], cfg.season, (id) => saveCmConfig({ season: id }));
    renderPillGroup("cm-style-group", catalog.styles || [], cfg.cm_style, (id) => saveCmConfig({ cm_style: id }));

    const roleNum = Number(cfg.cm_role || 0);
    const topMode = roleNum >= 2 ? 2 : roleNum;
    const topModes = [
        { id: 0, label: "Solo" },
        { id: 1, label: "Ace" },
        { id: 2, label: "Support" },
    ];
    renderPillGroup("cm-role-group", topModes, topMode, (id) => {
        if (Number(id) === 0) {
            saveCmConfig({ cm_role: 0, cm_target: "carry" });
        } else if (Number(id) === 1) {
            saveCmConfig({ cm_role: 1 });
        } else {
            saveCmConfig({ cm_role: roleNum === 3 ? 3 : 2 });
        }
    });

    const aceWrap = $("cm-ace-target-wrap");
    if (aceWrap) {
        aceWrap.style.display = topMode === 1 ? "" : "none";
        if (topMode === 1) {
            renderPillGroup(
                "cm-ace-target-group",
                catalog.ace_targets || [{ id: "carry", label: "Carry" }, { id: "debuffer", label: "Debuffer" }],
                String(cfg.cm_target || "carry"),
                (id) => saveCmConfig({ cm_role: 1, cm_target: String(id) }),
            );
        }
    }

    const supWrap = $("cm-support-subrole-wrap");
    if (supWrap) {
        supWrap.style.display = topMode === 2 ? "" : "none";
        if (topMode === 2) {
            renderPillGroup(
                "cm-support-subrole-group",
                catalog.support_subroles || [{ id: 2, label: "Debuffer" }, { id: 3, label: "Blocker" }],
                roleNum === 3 ? 3 : 2,
                (id) => saveCmConfig({ cm_role: Number(id) }),
            );
        }
    }

    const isAceDebuffer = roleNum === 1 && String(cfg.cm_target || "carry") === "debuffer";
    const needTwoMates = roleNum === 2 || roleNum === 3 || isAceDebuffer;

    const hint = $("cm-role-hint");
    const roleHints = {
        0: "Solo: evaluates this Uma's own individual winrate (0 teammates).",
        1: isAceDebuffer
            ? "Ace (Debuffer target): select your 2 veteran ace teammates below so the model trains around them."
            : "Ace: optional 0–2 veteran teammates (blank = auto-supplied mates).",
        2: "Support (Debuffer): evaluates full 3-Uma team winrate around your 2 selected veterans. Requires 2 distinct veterans.",
        3: "Support (Blocker): Front-runner blocker serving your 2 selected veterans. Requires 2 distinct veterans.",
    };
    if (hint) {
        hint.textContent = roleHints[roleNum] || "";
    }

    const matesArea = $("cm-mates-area");
    if (matesArea) {
        matesArea.style.display = roleNum === 0 ? "none" : "";
    }

    const vets = state.veterans || [];
    const byTid = new Map(vets.map((v) => [Number(v.trained_chara_id), v]));
    const q = (state.mateQuery || "").trim().toLowerCase();
    const filtered = q
        ? vets.filter((v) => `${v.name} ${v.rank_score} ${STYLE_SHORT[v.running_style] || ""} ${(v.stats || []).join(" ")}`.toLowerCase().includes(q))
        : vets;
    const countNode = $("cm-vet-count");
    if (countNode) {
        countNode.textContent = `${vets.length} veteran${vets.length === 1 ? "" : "s"}`;
    }

    const mateIds = Array.isArray(cfg.mate_ids) ? cfg.mate_ids : [null, null];
    const mateRoles = Array.isArray(cfg.mate_roles) ? cfg.mate_roles : ["auto", "auto"];

    for (const slot of [0, 1]) {
        const sel = $(`cm-mate-${slot}`);
        const roleSel = $(`cm-mate-role-${slot}`);
        const info = $(`cm-mate-info-${slot}`);
        const curTid = mateIds[slot] != null ? Number(mateIds[slot]) : null;
        const otherTid = mateIds[1 - slot] != null ? Number(mateIds[1 - slot]) : null;
        if (sel) {
            sel.innerHTML = "";
            const blank = document.createElement("option");
            blank.value = "";
            blank.textContent = needTwoMates ? "— Select veteran teammate —" : "Auto-supplied / None";
            sel.append(blank);
            const listForSlot = [...filtered];
            if (curTid && byTid.has(curTid) && !listForSlot.some((v) => Number(v.trained_chara_id) === curTid)) {
                listForSlot.unshift(byTid.get(curTid));
            }
            for (const v of listForSlot) {
                const tid = Number(v.trained_chara_id);
                const opt = document.createElement("option");
                opt.value = String(tid);
                opt.textContent = formatVeteranOption(v);
                opt.disabled = Boolean(otherTid && tid === otherTid);
                sel.append(opt);
            }
            sel.value = curTid ? String(curTid) : "";
        }
        if (roleSel) {
            roleSel.value = mateRoles[slot] || "auto";
        }
        if (info) {
            if (curTid && byTid.has(curTid)) {
                info.textContent = formatVeteranSummary(byTid.get(curTid));
            } else if (curTid) {
                info.textContent = `Saved veteran #${curTid}`;
            } else {
                info.textContent = needTwoMates ? "Required: select a veteran teammate" : "Auto-supplied by model / None";
            }
        }
    }

    const warn = $("cm-warning");
    if (warn) {
        if (isCmSupportBlocked(session)) {
            warn.style.display = "block";
            warn.textContent = isAceDebuffer
                ? "Targeting a debuffer build: select your 2 veteran ace teammates below."
                : "Support mode requires selecting 2 distinct veteran teammates before starting.";
        } else {
            warn.style.display = "none";
            warn.textContent = "";
        }
    }
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
        if (window.SweepyAndroid && typeof window.SweepyAndroid.saveJson === "function") {
            window.SweepyAndroid.saveJson(payload.filename || "umadump.json", JSON.stringify(payload.json, null, 2));
        } else if (/Android/i.test(navigator.userAgent)) {
            const anchor = document.createElement("a");
            anchor.href = "/api/career/final-turn-export?download=1";
            anchor.download = payload.filename || "umadump.json";
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
        } else {
            downloadJsonFile(payload.json, payload.filename);
        }
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
        runBtn.disabled = runner.running === true || !state.session || !state.session.logged_in || !activeGrandLiveCareer(state.session) || isCmSupportBlocked(state.session);
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
    const lessonLabels = new Map([
        ["Song", "Song learned"],
        ["Lesson", "Lesson completed"],
    ]);
    for (const entry of history) {
        const row = document.createElement("tr");
        row.append(make("td", "col-turn", entry.turn ?? ""));
        row.append(make("td", "col-kind", entry.kind ?? ""));
        const action = lessonLabels.get(entry.kind) ?? entry.action ?? "";
        row.append(make("td", "col-action", action));
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
        setQrHint(QR_HINT_IDLE);
        state.qrActive = true;
        state.qrRetries = 0;
        state.qrInterval = nextPollDelaySec(response.interval, false);
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

function setAuthConnecting(active, label) {
    state.authConnecting = Boolean(active);
    const ids = [
        "auth-tab-credentials",
        "auth-tab-qr",
        "qr-refresh-btn",
        "guard-reset-btn",
        "cred-login-btn",
        "guard-verify-btn",
    ];
    for (const id of ids) {
        const el = $(id);
        if (el) {
            el.disabled = state.authConnecting;
        }
    }
    if (state.authConnecting) {
        showAuthError("");
        const text = label || "Connecting to Umamusume";
        const qrPanel = $("qr-panel");
        const guardPanel = $("guard-panel");
        if (qrPanel && !qrPanel.hidden) {
            setQrHint(text, { animated: true, connecting: true });
        } else if (guardPanel && !guardPanel.hidden) {
            const promptNode = $("guard-prompt");
            const codeField = $("guard-code-field");
            const verifyBtn = $("guard-verify-btn");
            if (promptNode) {
                promptNode.textContent = "Steam approved.";
            }
            if (codeField) {
                codeField.hidden = true;
            }
            if (verifyBtn) {
                verifyBtn.hidden = true;
            }
            setGuardStatus(text, { animated: true, connecting: true, visible: true });
        } else {
            const loginBtn = $("cred-login-btn");
            if (loginBtn) {
                loginBtn.textContent = "CONNECTING…";
            }
        }
    } else {
        const qrPanel = $("qr-panel");
        if (qrPanel && !qrPanel.hidden) {
            setQrHint(QR_HINT_IDLE);
        }
        setGuardStatus("", { visible: false });
        const loginBtn = $("cred-login-btn");
        if (loginBtn) {
            loginBtn.textContent = "SIGN IN";
        }
        const verifyBtn = $("guard-verify-btn");
        if (verifyBtn) {
            verifyBtn.textContent = "VERIFY";
        }
    }
}

async function finalizeApprovedLogin(response) {
    state.qrActive = false;
    state.credPollActive = false;
    clearTimeout(state.qrTimer);
    clearTimeout(state.credTimer);
    setAuthConnecting(true, "Connecting to Umamusume");
    try {
        let finalRes = response;
        if (response.status === "steam_approved") {
            finalRes = await api("/api/auth/finalize", "POST", {}, 60000);
        }
        await completeSteamApproval(finalRes);
    } catch (error) {
        const credPanel = $("credentials-panel");
        if (credPanel && !credPanel.hidden) {
            resetCredentialsUi();
        } else {
            setAuthConnecting(false);
        }
        showAuthError(error.message);
    }
}

async function completeSteamApproval(response) {
    state.qrActive = false;
    state.credPollActive = false;
    clearTimeout(state.qrTimer);
    clearTimeout(state.credTimer);
    const passInput = $("steam-pass-input");
    if (passInput) {
        passInput.value = "";
    }
    const guardInput = $("steam-guard-input");
    if (guardInput) {
        guardInput.value = "";
    }
    saveSteamToken(response.refresh_token || "");
    adoptDeviceState(response);
    try {
        await refreshSession();
    } finally {
        setAuthConnecting(false);
    }
}

function setAuthTab(tab, triggerQr) {
    if (state.authConnecting) {
        return;
    }
    const hasPwd = Boolean(state.session && state.session.password_auth);
    const chosen = hasPwd && tab === "credentials" ? "credentials" : "qr";
    state.authTab = chosen;
    const tabs = $("auth-mode-tabs");
    const credPanel = $("credentials-panel");
    const qrPanel = $("qr-panel");
    const credBtn = $("auth-tab-credentials");
    const qrBtn = $("auth-tab-qr");
    if (tabs) {
        tabs.hidden = !hasPwd;
    }
    if (credPanel) {
        credPanel.hidden = chosen !== "credentials";
    }
    if (qrPanel) {
        qrPanel.hidden = chosen !== "qr";
    }
    if (credBtn && qrBtn) {
        const credOn = chosen === "credentials";
        credBtn.classList.toggle("btn-brass", credOn);
        credBtn.classList.toggle("btn-quiet", !credOn);
        credBtn.setAttribute("aria-pressed", String(credOn));
        qrBtn.classList.toggle("btn-brass", !credOn);
        qrBtn.classList.toggle("btn-quiet", credOn);
        qrBtn.setAttribute("aria-pressed", String(!credOn));
    }
    showAuthError("");
    if (chosen === "credentials") {
        state.qrActive = false;
        clearTimeout(state.qrTimer);
    } else if (triggerQr && !state.qrActive) {
        startQr();
    }
}

function resetCredentialsUi() {
    state.credPollActive = false;
    state.authConnecting = false;
    clearTimeout(state.credTimer);
    setAuthConnecting(false);
    const credForm = $("credentials-form");
    const guardPanel = $("guard-panel");
    const guardInput = $("steam-guard-input");
    const guardBtn = $("guard-verify-btn");
    const loginBtn = $("cred-login-btn");
    if (credForm) {
        credForm.hidden = false;
    }
    if (guardPanel) {
        guardPanel.hidden = true;
    }
    if (guardInput) {
        guardInput.value = "";
    }
    setGuardStatus("", { visible: false });
    if (guardBtn) {
        guardBtn.disabled = false;
        guardBtn.textContent = "VERIFY";
    }
    if (loginBtn) {
        loginBtn.disabled = false;
        loginBtn.textContent = "SIGN IN";
    }
    showAuthError("");
}

function renderGuardChallenge(res) {
    const types = Array.isArray(res.guard_types) ? res.guard_types : [];
    const hint = res.hint ? String(res.hint) : "";
    const credForm = $("credentials-form");
    const guardPanel = $("guard-panel");
    const codeField = $("guard-code-field");
    const verifyBtn = $("guard-verify-btn");
    const promptNode = $("guard-prompt");
    if (credForm) {
        credForm.hidden = true;
    }
    if (guardPanel) {
        guardPanel.hidden = false;
    }

    const allowsPush = types.includes("device_confirm") || types.includes("email_confirm");
    const needsCode = !allowsPush && (types.includes("email_code") || types.includes("device_code") || types.length === 0);
    if (codeField) {
        codeField.hidden = !needsCode;
    }
    if (verifyBtn) {
        verifyBtn.hidden = !needsCode;
    }

    let text = "Approve this sign-in using the Steam Mobile app.";
    if (types.includes("device_confirm")) {
        text = "Approve this sign-in using the Steam Mobile app.";
    } else if (types.includes("email_confirm")) {
        text = "Click the confirmation link sent to your Steam email.";
    } else if (types.includes("email_code")) {
        text = hint
            ? `Enter the Steam Guard code sent to ${hint}.`
            : "Enter the Steam Guard code sent to your email.";
    } else if (needsCode) {
        text = "Enter your 5-character Steam Guard code.";
    }
    if (promptNode) {
        promptNode.textContent = text;
    }

    if (allowsPush) {
        setGuardStatus("Waiting for approval", { animated: true, visible: true });
        state.credPollActive = true;
        state.credRetries = 0;
        state.credInterval = nextPollDelaySec(res.interval, false);
        scheduleCredPoll(state.credInterval);
    } else {
        setGuardStatus("", { visible: false });
        state.credPollActive = false;
        clearTimeout(state.credTimer);
    }
    if (needsCode) {
        const input = $("steam-guard-input");
        if (input) {
            input.focus();
        }
    }
}

function scheduleCredPoll(seconds) {
    clearTimeout(state.credTimer);
    state.credTimer = setTimeout(pollCredentials, Math.max(1, seconds) * 1000);
}

async function pollCredentials() {
    if (!state.credPollActive || state.credPollInFlight) {
        return;
    }
    state.credPollInFlight = true;
    try {
        const res = await api("/api/auth/credentials/poll", "POST", { defer_login: true }, 30000);
        if (res.status === "steam_approved" || res.status === "approved" || res.logged_in === true) {
            await finalizeApprovedLogin(res);
            return;
        }
        if (String(res.status || "").toLowerCase() === "expired") {
            resetCredentialsUi();
            showAuthError("Sign-in session expired — enter your credentials again.");
            return;
        }
        if (res.had_remote_interaction === true) {
            setGuardStatus("Confirming sign-in", { animated: true, visible: true });
        }
        state.credInterval = nextPollDelaySec(res.interval, res.had_remote_interaction === true);
        state.credRetries = 0;
        scheduleCredPoll(state.credInterval);
    } catch (error) {
        state.credRetries += 1;
        showAuthError(error.message);
        if (error.status === 400 || state.credRetries > 3) {
            state.credPollActive = false;
            return;
        }
        scheduleCredPoll(Math.max(3, state.credInterval * state.credRetries));
    } finally {
        state.credPollInFlight = false;
    }
}

async function submitCredentialsLogin(event) {
    if (event) {
        event.preventDefault();
    }
    const userInput = $("steam-user-input");
    const passInput = $("steam-pass-input");
    const btn = $("cred-login-btn");
    const username = userInput ? userInput.value.trim() : "";
    const password = passInput ? passInput.value : "";
    if (!username || !password) {
        showAuthError("Enter both your Steam username and password.");
        return;
    }
    showAuthError("");
    if (btn) {
        btn.disabled = true;
        btn.textContent = "SIGNING IN…";
    }
    try {
        const res = await api("/api/auth/credentials/start", "POST", { username, password, defer_login: true }, 45000);
        if (res.status === "steam_approved" || res.status === "approved" || res.logged_in === true) {
            await finalizeApprovedLogin(res);
            return;
        }
        if (passInput) {
            passInput.value = "";
        }
        renderGuardChallenge(res);
    } catch (error) {
        showAuthError(error.message);
    } finally {
        if (btn && !state.authConnecting) {
            btn.disabled = false;
            btn.textContent = "SIGN IN";
        }
    }
}

async function submitGuardCode(event) {
    if (event) {
        event.preventDefault();
    }
    const input = $("steam-guard-input");
    const btn = $("guard-verify-btn");
    const code = input ? input.value.trim() : "";
    if (!code) {
        showAuthError("Enter your Steam Guard code.");
        return;
    }
    showAuthError("");
    if (btn) {
        btn.disabled = true;
        btn.textContent = "VERIFYING…";
    }
    try {
        const res = await api("/api/auth/credentials/code", "POST", { code, defer_login: true }, 45000);
        if (res.status === "steam_approved" || res.status === "approved" || res.logged_in === true) {
            await finalizeApprovedLogin(res);
            return;
        }
        setGuardStatus("Verifying with Steam", { animated: true, connecting: true, visible: true });
        state.credPollActive = true;
        state.credRetries = 0;
        scheduleCredPoll(1);
    } catch (error) {
        showAuthError(error.message);
    } finally {
        if (btn && !state.authConnecting) {
            btn.disabled = false;
            btn.textContent = "VERIFY";
        }
    }
}

async function pollQr() {
    if (!state.qrActive || state.qrPollInFlight) {
        return;
    }
    state.qrPollInFlight = true;
    try {
        const response = await api("/api/auth/qr/poll", "POST", { defer_login: true }, 120000);
        if (response.status === "steam_approved" || response.status === "approved" || response.logged_in === true) {
            await finalizeApprovedLogin(response);
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
            setQrHint(`Code refreshed · ${QR_HINT_IDLE}`);
        } else if (response.had_remote_interaction === true) {
            setQrHint("Waiting for Steam approval", { animated: true });
        } else {
            setQrHint(QR_HINT_IDLE);
        }
        state.qrInterval = nextPollDelaySec(response.interval, response.had_remote_interaction === true);
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
    } finally {
        state.qrPollInFlight = false;
    }
}

async function logout() {
    state.qrActive = false;
    state.qrPollInFlight = false;
    state.credPollActive = false;
    state.credPollInFlight = false;
    clearTimeout(state.qrTimer);
    clearTimeout(state.credTimer);
    const passInput = $("steam-pass-input");
    if (passInput) {
        passInput.value = "";
    }
    resetCredentialsUi();
    saveSteamToken("");
    saveBrainKey("");
    saveDeviceState(null);
    try {
        state.authTab = "";
        await api("/api/logout", "POST", {});
        const session = await refreshSession();
        if (!session.logged_in) {
            const nextTab = defaultAuthTab(session);
            setAuthTab(nextTab, nextTab === "qr");
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
        const payload = {
            burn_clocks: Boolean(state.session.burn_clocks),
        };
        if (state.session.cm_enabled) {
            payload.cm_config = getCmConfig(state.session);
        }
        const response = await api("/api/career/run", "POST", payload);
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
    state.cmCatalog = session.cm_catalog || state.cmCatalog;
    state.veterans = Array.isArray(session.veterans) ? session.veterans : [];
    if (session.cm_config && state.pendingCmMode === null) {
        state.cmConfig = session.cm_config;
    }
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
        renderCmPanel(session);
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
        const defaultTab = state.authTab || defaultAuthTab(session);
        setAuthTab(defaultTab, false);
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
        if (state.runnerPollInFlight) {
            return;
        }
        const runner = state.session && state.session.runner;
        if (!state.session || !state.session.logged_in || !runner || runner.running !== true) {
            return;
        }
        state.runnerPollInFlight = true;
        try {
            const response = await api("/api/career/runner");
            markConnected();
            renderRunner(response.runner);
            if (response.runner && response.runner.running !== true) {
                await refreshSession(true);
                return;
            }
            if (state.session) {
                state.session.runner = response.runner;
                state.session.account = response.account || state.session.account;
                renderAccountStrip(state.session);
                renderCareer(state.session);
            }
        } catch {
            markDisconnected();
        } finally {
            state.runnerPollInFlight = false;
        }
    }, 1200);
}

function bindStatic() {
    $("logout-btn").addEventListener("click", logout);
    $("qr-refresh-btn").addEventListener("click", startQr);
    $("auth-tab-credentials").addEventListener("click", () => setAuthTab("credentials", false));
    $("auth-tab-qr").addEventListener("click", () => setAuthTab("qr", true));
    $("credentials-form").addEventListener("submit", submitCredentialsLogin);
    $("guard-panel").addEventListener("submit", submitGuardCode);
    $("guard-reset-btn").addEventListener("click", resetCredentialsUi);
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
    $("cm-mode-btn").addEventListener("click", toggleCmMode);

    $("cm-preset-select").addEventListener("change", (event) => {
        const slug = event.target.value;
        const presets = ((state.cmCatalog || {}).presets) || [];
        const found = presets.find((p) => p.slug === slug);
        if (found) {
            saveCmConfig({
                cm_preset: found.slug,
                track: found.track,
                distance: found.distance,
                ground: found.ground,
                ground_condition: found.ground_condition,
                weather: found.weather,
                season: found.season,
                course_id: found.course_id,
                inout: found.inout || 1,
            });
        } else {
            saveCmConfig({ cm_preset: "custom" });
        }
    });

    $("cm-track-select").addEventListener("change", (event) => {
        const track = event.target.value;
        const courses = ((state.cmCatalog || {}).courses) || [];
        const cfg = getCmConfig(state.session);
        let avail = coursesForTrackAndGround(courses, track, cfg.ground);
        let nextGround = cfg.ground;
        if (!avail.length) {
            avail = courses.filter((c) => c.track === track);
            nextGround = avail.length ? Number(avail[0].ground) : 1;
        }
        const best = avail.length
            ? avail.reduce((a, b) => (Math.abs(a.distance - cfg.distance) <= Math.abs(b.distance - cfg.distance) ? a : b))
            : null;
        if (best) {
            saveCmConfig({ track, ground: nextGround, course_id: best.course_id, distance: best.distance, inout: best.inout });
        }
    });

    $("cm-course-select").addEventListener("change", (event) => {
        const cid = Number(event.target.value);
        const courses = ((state.cmCatalog || {}).courses) || [];
        const found = courses.find((c) => Number(c.course_id) === cid);
        if (found) {
            saveCmConfig({ course_id: found.course_id, distance: found.distance, ground: found.ground, inout: found.inout });
        }
    });

    $("cm-mate-search").addEventListener("input", (event) => {
        state.mateQuery = event.target.value || "";
        renderCmPanel(state.session);
    });

    for (const slot of [0, 1]) {
        $(`cm-mate-${slot}`).addEventListener("change", (event) => {
            const cfg = getCmConfig(state.session);
            const nextIds = [...(cfg.mate_ids || [null, null])];
            nextIds[slot] = event.target.value ? Number(event.target.value) : null;
            saveCmConfig({ mate_ids: nextIds });
        });
        $(`cm-mate-role-${slot}`).addEventListener("change", (event) => {
            const cfg = getCmConfig(state.session);
            const nextRoles = [...(cfg.mate_roles || ["auto", "auto"])];
            nextRoles[slot] = event.target.value || "auto";
            saveCmConfig({ mate_roles: nextRoles });
        });
        $(`cm-mate-clear-${slot}`).addEventListener("click", () => {
            const cfg = getCmConfig(state.session);
            const nextIds = [...(cfg.mate_ids || [null, null])];
            nextIds[slot] = null;
            saveCmConfig({ mate_ids: nextIds });
        });
    }
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
            const nextTab = defaultAuthTab(session);
            setAuthTab(nextTab, nextTab === "qr");
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
    if (document.hidden || state.authConnecting) {
        return;
    }
    if (state.credPollActive && !state.credPollInFlight) {
        clearTimeout(state.credTimer);
        pollCredentials();
        return;
    }
    if (state.qrActive && !state.qrPollInFlight) {
        clearTimeout(state.qrTimer);
        pollQr();
        return;
    }
    if (state.session && state.session.logged_in) {
        refreshSession().catch(() => markDisconnected());
    }
});
