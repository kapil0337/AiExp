/* ═══════════════════════════════════════════════════════════
   Bloom Budget 🌸 — frontend
   No build step, no dependencies. Just a module.
   ═══════════════════════════════════════════════════════════ */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const API = "/api";

const CURRENCIES = {
  INR: { symbol: "₹", locale: "en-IN" },
  USD: { symbol: "$", locale: "en-US" },
  EUR: { symbol: "€", locale: "de-DE" },
  GBP: { symbol: "£", locale: "en-GB" },
  AED: { symbol: "AED ", locale: "en-AE" },
  JPY: { symbol: "¥", locale: "ja-JP" },
};

const METHOD_META = {
  cash: { label: "Cash", emoji: "💵", varName: "--s-cash" },
  gpay: { label: "GPay", emoji: "📱", varName: "--s-gpay" },
  card: { label: "Card", emoji: "💳", varName: "--s-card" },
};
const METHODS = ["cash", "gpay", "card"];

const EMOJI_PALETTE = [
  "🌸", "🍜", "☕", "🛍️", "💅", "🚕", "🏠", "🧾", "🎀", "💊", "🎁", "📱",
  "🍫", "🍕", "🧋", "🍦", "👗", "👟", "💄", "🎬", "📚", "🐱", "✈️", "🌷",
  "🍰", "🥗", "💐", "🎧", "🧴", "🪴", "🎂", "✨",
];

const state = {
  user: null,
  summary: null,
  dashboard: null,
  splits: [],
  categories: [],
  currency: "INR",
  emoji: "🌸",
  category: "other",
  view: "home",
  filters: { q: "", method: "", category: "", month: "" },
  showSettled: false,
};

/* ── formatting ──────────────────────────────────────────── */

function currencyInfo() {
  return CURRENCIES[state.currency] || CURRENCIES.INR;
}

function fmt(value, { decimals = false } = {}) {
  const { symbol, locale } = currencyInfo();
  const n = Number(value || 0);
  const body = n.toLocaleString(locale, {
    minimumFractionDigits: decimals ? 2 : 0,
    maximumFractionDigits: decimals ? 2 : 0,
  });
  return `${symbol}${body}`;
}

function fmtCompact(value) {
  const n = Math.abs(Number(value || 0));
  const { symbol } = currencyInfo();
  const sign = Number(value) < 0 ? "-" : "";
  if (n >= 1e7) return `${sign}${symbol}${(n / 1e7).toFixed(1)}Cr`;
  if (n >= 1e5) return `${sign}${symbol}${(n / 1e5).toFixed(1)}L`;
  if (n >= 1e3) return `${sign}${symbol}${(n / 1e3).toFixed(1)}k`;
  return `${sign}${symbol}${Math.round(n)}`;
}

function prettyDate(iso) {
  const d = new Date(`${iso}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((today - d) / 86400000);
  if (diff === 0) return "today";
  if (diff === 1) return "yesterday";
  if (diff > 1 && diff < 7) return `${diff}d ago`;
  return d.toLocaleDateString(currencyInfo().locale, { day: "numeric", month: "short" });
}

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function esc(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );
}

function seriesColor(method) {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(METHOD_META[method].varName).trim() || "#e8579a";
}

/* ── api ─────────────────────────────────────────────────── */

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(`${API}${path}`, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const text = await res.text();
  // A 500 from Starlette is the plain string "Internal Server Error", not
  // JSON. Parsing it blind threw "Unexpected token 'I'" and hid the real
  // status, so treat unparseable bodies as a message rather than a crash.
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: res.ok ? null : `${text.slice(0, 120) || "Server error"} (${res.status})` };
  }
  if (!res.ok) {
    if (res.status === 401 && path !== "/auth/me") {
      state.user = null;
      showLoginScreen();
    }
    const detail = data?.detail;
    const msg = Array.isArray(detail)
      ? detail.map((d) => d.msg?.replace(/^Value error, /, "")).join(", ")
      : detail || `Something went sideways (${res.status})`;
    throw new Error(msg);
  }
  return data;
}

/* ── delight: toast, confetti, floaties, count-up ────────── */

function toast(message, kind = "ok") {
  const el = document.createElement("div");
  el.className = "toast";
  el.dataset.kind = kind;
  el.textContent = message;
  $("#toasts").append(el);
  setTimeout(() => {
    el.classList.add("is-out");
    setTimeout(() => el.remove(), 320);
  }, 2800);
}

function confetti(count = 22) {
  if (document.body.classList.contains("no-motion")) return;
  const layer = $("#confetti");
  const pieces = ["🌸", "💖", "✨", "🎀", "💕", "🌟", "🫧"];
  for (let i = 0; i < count; i++) {
    const c = document.createElement("span");
    c.className = "confetto";
    c.textContent = pieces[(Math.random() * pieces.length) | 0];
    c.style.left = `${10 + Math.random() * 80}%`;
    c.style.top = `${15 + Math.random() * 25}%`;
    c.style.setProperty("--dx", `${(Math.random() - 0.5) * 260}px`);
    c.style.setProperty("--rot", `${(Math.random() - 0.5) * 900}deg`);
    c.style.setProperty("--dur", `${1.1 + Math.random() * 0.9}s`);
    layer.append(c);
    setTimeout(() => c.remove(), 2200);
  }
}

function startFloaties() {
  const host = $("#floaties");
  const glyphs = ["🌸", "✨", "💗", "🫧", "🌷"];
  setInterval(() => {
    if (document.hidden || document.body.classList.contains("no-motion")) return;
    if (host.childElementCount > 14) return;
    const f = document.createElement("span");
    f.className = "floaty";
    f.textContent = glyphs[(Math.random() * glyphs.length) | 0];
    f.style.left = `${Math.random() * 100}%`;
    f.style.fontSize = `${0.6 + Math.random() * 0.9}rem`;
    const dur = 12 + Math.random() * 12;
    f.style.animationDuration = `${dur}s`;
    host.append(f);
    setTimeout(() => f.remove(), dur * 1000);
  }, 1600);
}

function countUp(el, to, formatter) {
  const from = Number(el.dataset.value || 0);
  el.dataset.value = String(to);
  if (document.body.classList.contains("no-motion") || from === to) {
    el.textContent = formatter(to);
    return;
  }
  const start = performance.now();
  const dur = 700;
  const tick = (now) => {
    const t = Math.min(1, (now - start) / dur);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = formatter(from + (to - from) * eased);
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/* ── theme ───────────────────────────────────────────────── */

function applyTheme(mode) {
  document.documentElement.dataset.theme = mode;
  localStorage.setItem("bloom.theme", mode);
  const dark =
    mode === "dark" ||
    (mode === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
  $("#themeBtn").textContent = dark ? "☀️" : "🌙";
  $("meta[name=theme-color]")?.setAttribute("content", dark ? "#16101a" : "#ff8fbd");
  const radio = $(`input[name=theme][value="${mode}"]`);
  if (radio) radio.checked = true;
  // series colours changed -> repaint charts
  if (state.dashboard) renderStats();
}

function initTheme() {
  applyTheme(localStorage.getItem("bloom.theme") || "auto");
  $("#themeBtn").addEventListener("click", () => {
    const order = ["light", "dark", "auto"];
    const next = order[(order.indexOf(document.documentElement.dataset.theme) + 1) % 3];
    applyTheme(next);
    toast(`${next === "auto" ? "✨ Auto" : next === "dark" ? "🌙 Dark" : "☀️ Light"} mode`);
  });
  $$("input[name=theme]").forEach((r) =>
    r.addEventListener("change", () => applyTheme(r.value))
  );

  const motionOff = localStorage.getItem("bloom.motion") === "off";
  document.body.classList.toggle("no-motion", motionOff);
  $("#motionToggle").checked = !motionOff;
  $("#motionToggle").addEventListener("change", (e) => {
    const on = e.target.checked;
    document.body.classList.toggle("no-motion", !on);
    localStorage.setItem("bloom.motion", on ? "on" : "off");
  });
}

/* ── auth ────────────────────────────────────────────────── */

let gsiInitialized = false;

function showLoginScreen() {
  $("#appShell").classList.add("is-hidden");
  $("#nicknameGate").classList.add("is-hidden");
  $("#userBadge").classList.add("is-hidden");
  $("#authGate").classList.remove("is-hidden");
}

function showNicknameGate() {
  $("#appShell").classList.add("is-hidden");
  $("#authGate").classList.add("is-hidden");
  $("#nicknameGate").classList.remove("is-hidden");
  $("#nicknameInput").focus();
}

function showApp() {
  $("#authGate").classList.add("is-hidden");
  $("#nicknameGate").classList.add("is-hidden");
  $("#appShell").classList.remove("is-hidden");
}

/** After we know who's signed in: first-timers (no nickname yet) get the
 *  onboarding gate before they ever see the app; everyone else goes straight in. */
async function enterApp() {
  if (!state.user.nickname) {
    showNicknameGate();
  } else {
    showApp();
    await runApp();
  }
}

async function saveNickname(nickname) {
  const user = await api("/auth/nickname", { method: "PUT", body: { nickname } });
  state.user = user;
  renderUserBadge();
  return user;
}

function renderUserBadge() {
  const badge = $("#userBadge");
  if (!state.user) {
    badge.classList.add("is-hidden");
    return;
  }
  // An empty src (or a Google avatar that 404s) renders as a broken-image
  // icon with the alt text spilling across the header — hide it instead.
  const img = $("#userAvatar");
  const pic = state.user.picture || "";
  img.alt = state.user.name || state.user.email || "";
  img.onerror = () => img.classList.add("is-hidden");
  if (pic) {
    img.classList.remove("is-hidden");
    img.src = pic;
  } else {
    img.classList.add("is-hidden");
    img.removeAttribute("src");
  }
  badge.classList.remove("is-hidden");
}

function waitForGoogleGIS() {
  return new Promise((resolve) => {
    const check = () => {
      if (window.google?.accounts?.id) resolve();
      else setTimeout(check, 50);
    };
    check();
  });
}

async function initGoogleSignIn(clientId) {
  if (gsiInitialized || !clientId) return;
  await waitForGoogleGIS();
  google.accounts.id.initialize({ client_id: clientId, callback: handleGoogleCredential });
  google.accounts.id.renderButton($("#gsiButton"), {
    type: "standard",
    theme: "outline",
    size: "large",
    shape: "pill",
  });
  gsiInitialized = true;
}

async function handleGoogleCredential(response) {
  showFormError("#authError", "");
  try {
    const user = await api("/auth/google", {
      method: "POST",
      body: { credential: response.credential, remember: $("#keepSignedIn").checked },
    });
    state.user = user;
    renderUserBadge();
    await enterApp();
  } catch (err) {
    showFormError("#authError", err.message);
  }
}

async function logout() {
  try {
    await api("/auth/logout", { method: "POST" });
  } catch {
    // cookie is cleared server-side regardless of network hiccups client-side
  }
  window.google?.accounts?.id?.disableAutoSelect();
  state.user = null;
  renderUserBadge();
  showLoginScreen();
}

/* ── router ──────────────────────────────────────────────── */

function go(view) {
  state.view = view;
  $$(".nav-item").forEach((b) => b.classList.toggle("is-active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("is-active", v.id === `view-${view}`));
  location.hash = view;
  $(`#view-${view}`)?.focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: document.body.classList.contains("no-motion") ? "auto" : "smooth" });
  if (view === "stats") renderStats();
  if (view === "log") loadExpenses();
}

/* ═══════════════════════════════════════════════════════════
   CHARTS
   Marks: thin, 4px rounded data-ends, 2px surface gaps,
   hairline grid, selective direct labels, tooltip + table view.
   ═══════════════════════════════════════════════════════════ */

const SVG_NS = "http://www.w3.org/2000/svg";
const tipEl = () => $("#chartTip");

function showTip(html, evt) {
  const tip = tipEl();
  tip.innerHTML = html;
  tip.classList.remove("is-hidden");
  const pad = 12;
  const rect = tip.getBoundingClientRect();
  let x = evt.clientX + pad;
  let y = evt.clientY - rect.height - pad;
  if (x + rect.width > innerWidth - 8) x = evt.clientX - rect.width - pad;
  if (y < 8) y = evt.clientY + pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${y}px`;
}
function hideTip() { tipEl().classList.add("is-hidden"); }

/** Measure the card so the viewBox is 1 unit = 1 CSS pixel.
 *  A fixed viewBox would scale label text down with the screen — 12px type
 *  renders at ~6px on a phone. Measuring keeps every label at its true size.
 *  Falls back to 700 when the view is display:none (clientWidth reads 0);
 *  switching to the tab re-renders with the real width. */
function chartWidth(host) {
  const w = host.clientWidth || host.parentElement?.clientWidth || 0;
  return Math.max(260, Math.round(w) || 700);
}

function el(tag, attrs = {}, text) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text != null) node.textContent = text;
  return node;
}

/** Rounded-top bar path anchored to the baseline. */
function topRoundedPath(x, y, w, h, r) {
  const rr = Math.max(0, Math.min(r, w / 2, h));
  return `M${x},${y + h} L${x},${y + rr} Q${x},${y} ${x + rr},${y} ` +
         `L${x + w - rr},${y} Q${x + w},${y} ${x + w},${y + rr} L${x + w},${y + h} Z`;
}

/** Horizontal pill segment with selectively rounded ends. */
function pillPath(x, y, w, h, roundLeft, roundRight) {
  const r = Math.min(h / 2, w / 2, 6);
  const rl = roundLeft ? r : 0;
  const rr = roundRight ? r : 0;
  return `M${x + rl},${y} L${x + w - rr},${y} Q${x + w},${y} ${x + w},${y + rr} ` +
         `L${x + w},${y + h - rr} Q${x + w},${y + h} ${x + w - rr},${y + h} ` +
         `L${x + rl},${y + h} Q${x},${y + h} ${x},${y + h - rl} ` +
         `L${x},${y + rl} Q${x},${y} ${x + rl},${y} Z`;
}

/* ── part-to-whole: horizontal stacked bar ───────────────── */

function renderMethodChart(by) {
  const host = $("#methodChart");
  host.innerHTML = "";
  const total = METHODS.reduce((s, m) => s + Number(by[m] || 0), 0);

  if (total <= 0) {
    host.innerHTML = `<p class="empty"><span class="big">🫧</span>No spending yet — the pot is untouched!</p>`;
    $("#methodLegend").innerHTML = "";
    $("#methodTable").innerHTML = "";
    return;
  }

  const W = chartWidth(host), H = 74, BAR_H = 34, GAP = 2;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": "Share of spending by payment method" });
  const inkMuted = getComputedStyle(document.documentElement)
    .getPropertyValue("--ink-2").trim();

  const present = METHODS.filter((m) => Number(by[m] || 0) > 0);
  let x = 0;
  present.forEach((m, i) => {
    const value = Number(by[m]);
    const raw = (value / total) * W;
    const w = Math.max(4, raw - (i < present.length - 1 ? GAP : 0));
    const path = el("path", {
      d: pillPath(x, 6, w, BAR_H, i === 0, i === present.length - 1),
      fill: seriesColor(m),
      tabindex: "0",
      role: "listitem",
      "aria-label": `${METHOD_META[m].label}: ${fmt(value)}, ${Math.round((value / total) * 100)} percent`,
    });
    const pct = Math.round((value / total) * 100);
    const tip = `<div class="tip-title">${METHOD_META[m].emoji} ${METHOD_META[m].label}</div>
      <div class="tip-row"><span>${fmt(value, { decimals: true })}</span><span>${pct}%</span></div>`;
    path.addEventListener("pointerenter", (e) => showTip(tip, e));
    path.addEventListener("pointermove", (e) => showTip(tip, e));
    path.addEventListener("pointerleave", hideTip);
    path.addEventListener("focus", (e) => {
      const r = e.target.getBoundingClientRect();
      showTip(tip, { clientX: r.left + r.width / 2, clientY: r.top });
    });
    path.addEventListener("blur", hideTip);
    svg.append(path);

    // Direct label sits *below* the segment in a text token — never white-on-fill,
    // and only when the segment is wide enough for it not to collide.
    if (w > 64) {
      svg.append(el("text", {
        x: x + w / 2, y: 6 + BAR_H + 20,
        "text-anchor": "middle",
        fill: inkMuted,
        "font-size": "12", "font-weight": "700",
        "font-family": "Quicksand, system-ui, sans-serif",
        "pointer-events": "none",
      }, `${METHOD_META[m].emoji} ${pct}%`));
    }
    x += raw;
  });

  host.append(svg);

  // legend — always present for >= 2 series, carries the values
  $("#methodLegend").innerHTML = METHODS.map((m) => {
    const v = Number(by[m] || 0);
    return `<span class="legend-item">
      <span class="legend-swatch" style="background:${seriesColor(m)}"></span>
      ${METHOD_META[m].emoji} ${METHOD_META[m].label}
      <span class="legend-value">${fmt(v)}</span>
    </span>`;
  }).join("");

  $("#methodTable").innerHTML = `<table>
    <thead><tr><th>Method</th><th>Spent</th><th>Share</th></tr></thead>
    <tbody>${METHODS.map((m) => {
      const v = Number(by[m] || 0);
      return `<tr><td>${METHOD_META[m].emoji} ${METHOD_META[m].label}</td>
        <td>${fmt(v, { decimals: true })}</td>
        <td>${total ? Math.round((v / total) * 100) : 0}%</td></tr>`;
    }).join("")}
    <tr><td><strong>Total</strong></td><td><strong>${fmt(total, { decimals: true })}</strong></td><td>100%</td></tr>
    </tbody></table>`;
}

/* ── trend: daily columns (one hue) ──────────────────────── */

function renderDailyChart(daily) {
  const host = $("#dailyChart");
  host.innerHTML = "";
  const max = Math.max(...daily.map((d) => d.total), 0);

  if (max <= 0) {
    host.innerHTML = `<p class="empty"><span class="big">🌙</span>Nothing logged in this window. Peaceful.</p>`;
    $("#dailyTable").innerHTML = "";
    return;
  }

  const W = chartWidth(host), PLOT_H = 170, AXIS_H = 26, TOP = 22;
  const H = TOP + PLOT_H + AXIS_H;
  const LEFT = 4, RIGHT = 4;
  const innerW = W - LEFT - RIGHT;
  const slot = innerW / daily.length;
  const GAP = 2;
  const barW = Math.max(6, slot - GAP * 2);

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": `Daily spending over the last ${daily.length} days` });

  const css = getComputedStyle(document.documentElement);
  const grid = css.getPropertyValue("--line").trim();
  const muted = css.getPropertyValue("--ink-muted").trim();
  const ink = css.getPropertyValue("--ink-2").trim();
  const hue = seriesColor("cash");

  // hairline gridlines, solid, one shade off the surface
  const steps = 3;
  for (let i = 0; i <= steps; i++) {
    const y = TOP + PLOT_H - (PLOT_H * i) / steps;
    svg.append(el("line", {
      x1: LEFT, x2: W - RIGHT, y1: y, y2: y,
      stroke: grid, "stroke-width": 1,
    }));
    if (i > 0) {
      svg.append(el("text", {
        x: LEFT, y: y - 5, fill: muted, "font-size": "10", "font-weight": "600",
        "font-family": "Quicksand, system-ui, sans-serif",
      }, fmtCompact((max * i) / steps)));
    }
  }

  const maxIdx = daily.reduce((best, d, i) => (d.total > daily[best].total ? i : best), 0);

  daily.forEach((d, i) => {
    const x = LEFT + i * slot + GAP;
    const h = d.total > 0 ? Math.max(3, (d.total / max) * PLOT_H) : 0;
    const y = TOP + PLOT_H - h;

    if (h > 0) {
      svg.append(el("path", {
        d: topRoundedPath(x, y, barW, h, 4),
        fill: hue,
        opacity: i === maxIdx ? "1" : "0.82",
      }));
    }

    // generous hit area covering the whole column
    const hit = el("rect", {
      x: LEFT + i * slot, y: TOP, width: slot, height: PLOT_H,
      fill: "transparent", tabindex: "0",
      "aria-label": `${d.date}: ${fmt(d.total)}`,
    });
    const tipHtml = `<div class="tip-title">${prettyDate(d.date)}</div>
      <div class="tip-row"><span>Total</span><strong>${fmt(d.total, { decimals: true })}</strong></div>
      ${METHODS.filter((m) => d[m] > 0).map((m) =>
        `<div class="tip-row"><span>${METHOD_META[m].emoji} ${METHOD_META[m].label}</span><span>${fmt(d[m])}</span></div>`
      ).join("")}`;
    hit.addEventListener("pointerenter", (e) => showTip(tipHtml, e));
    hit.addEventListener("pointermove", (e) => showTip(tipHtml, e));
    hit.addEventListener("pointerleave", hideTip);
    hit.addEventListener("focus", (e) => {
      const r = e.target.getBoundingClientRect();
      showTip(tipHtml, { clientX: r.left + r.width / 2, clientY: r.top + 20 });
    });
    hit.addEventListener("blur", hideTip);
    svg.append(hit);

    // direct-label only the peak
    if (i === maxIdx && d.total > 0) {
      svg.append(el("text", {
        x: x + barW / 2, y: y - 7, "text-anchor": "middle",
        fill: ink, "font-size": "11", "font-weight": "700",
        "font-family": "Quicksand, system-ui, sans-serif",
        "pointer-events": "none",
      }, fmtCompact(d.total)));
    }

    // x labels: thin them out so they never collide
    const every = daily.length > 20 ? 5 : daily.length > 10 ? 3 : 2;
    if (i % every === 0 || i === daily.length - 1) {
      const dd = new Date(`${d.date}T00:00:00`);
      svg.append(el("text", {
        x: x + barW / 2, y: TOP + PLOT_H + 16, "text-anchor": "middle",
        fill: muted, "font-size": "10", "font-weight": "600",
        "font-family": "Quicksand, system-ui, sans-serif",
      }, `${dd.getDate()}/${dd.getMonth() + 1}`));
    }
  });

  host.append(svg);

  const spentDays = daily.filter((d) => d.total > 0);
  $("#dailyTable").innerHTML = `<table>
    <thead><tr><th>Day</th><th>💵</th><th>📱</th><th>💳</th><th>Total</th></tr></thead>
    <tbody>${spentDays.map((d) => `<tr>
      <td>${prettyDate(d.date)}</td>
      <td>${d.cash ? fmt(d.cash) : "—"}</td>
      <td>${d.gpay ? fmt(d.gpay) : "—"}</td>
      <td>${d.card ? fmt(d.card) : "—"}</td>
      <td><strong>${fmt(d.total, { decimals: true })}</strong></td>
    </tr>`).join("")}</tbody></table>`;
}

/* ── magnitude: category bars (one hue) ──────────────────── */

function renderCategoryChart(categories) {
  const host = $("#categoryChart");
  host.innerHTML = "";
  if (!categories.length) {
    host.innerHTML = `<p class="empty"><span class="big">🎀</span>Categories show up once she logs something.</p>`;
    $("#catTable").innerHTML = "";
    return;
  }

  const rows = categories.slice(0, 8);
  const max = Math.max(...rows.map((r) => r.total));
  const ROW_H = 34, BAR_H = 16;
  const W = chartWidth(host);
  // Give the label and value columns a share of the real width so the track
  // never collapses on a narrow phone.
  const LABEL_W = Math.round(Math.min(132, Math.max(88, W * 0.32)));
  const VALUE_W = Math.round(Math.min(78, Math.max(52, W * 0.17)));
  const trackW = W - LABEL_W - VALUE_W;
  const H = rows.length * ROW_H;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": "Spending by category" });
  const hue = seriesColor("cash");
  const track = getComputedStyle(document.documentElement).getPropertyValue("--surface-3").trim();
  const ink = getComputedStyle(document.documentElement).getPropertyValue("--ink-2").trim();
  const muted = getComputedStyle(document.documentElement).getPropertyValue("--ink-muted").trim();

  rows.forEach((r, i) => {
    const y = i * ROW_H + (ROW_H - BAR_H) / 2;
    svg.append(el("text", {
      x: 0, y: y + BAR_H / 2 + 4, fill: ink,
      "font-size": "12", "font-weight": "700",
      "font-family": "Quicksand, system-ui, sans-serif",
    }, `${r.emoji} ${r.category}`));

    svg.append(el("rect", {
      x: LABEL_W, y, width: trackW, height: BAR_H, rx: BAR_H / 2, fill: track,
    }));

    const w = Math.max(BAR_H, (r.total / max) * trackW);
    const bar = el("rect", {
      x: LABEL_W, y, width: w, height: BAR_H, rx: BAR_H / 2,
      fill: hue, opacity: i === 0 ? "1" : "0.78",
      tabindex: "0",
      "aria-label": `${r.category}: ${fmt(r.total)} across ${r.count} expenses`,
    });
    const tip = `<div class="tip-title">${r.emoji} ${r.category}</div>
      <div class="tip-row"><span>${r.count} expense${r.count === 1 ? "" : "s"}</span><strong>${fmt(r.total, { decimals: true })}</strong></div>`;
    bar.addEventListener("pointerenter", (e) => showTip(tip, e));
    bar.addEventListener("pointermove", (e) => showTip(tip, e));
    bar.addEventListener("pointerleave", hideTip);
    bar.addEventListener("focus", (e) => {
      const rect = e.target.getBoundingClientRect();
      showTip(tip, { clientX: rect.right, clientY: rect.top });
    });
    bar.addEventListener("blur", hideTip);
    svg.append(bar);

    svg.append(el("text", {
      x: W, y: y + BAR_H / 2 + 4, "text-anchor": "end", fill: muted,
      "font-size": "12", "font-weight": "700",
      "font-family": "Quicksand, system-ui, sans-serif",
    }, fmtCompact(r.total)));
  });

  host.append(svg);

  $("#catTable").innerHTML = `<table>
    <thead><tr><th>Category</th><th>Count</th><th>Spent</th></tr></thead>
    <tbody>${categories.map((r) => `<tr>
      <td>${r.emoji} ${r.category}</td><td>${r.count}</td>
      <td>${fmt(r.total, { decimals: true })}</td></tr>`).join("")}</tbody></table>`;
}

/* ═══════════════════════════════════════════════════════════
   RENDERERS
   ═══════════════════════════════════════════════════════════ */

const STATUS_COPY = {
  comfy: "living comfortably 🌿",
  watchful: "keeping an eye 👀",
  tight: "getting tight 😬",
  overboard: "OVERBOARD 🚨",
};

function renderHome() {
  const s = state.summary;
  if (!s) return;

  const hero = $("#heroRemaining");
  hero.classList.toggle("is-negative", s.remaining < 0);
  countUp(hero, s.remaining, (v) => fmt(v));

  $("#statusPill").textContent = STATUS_COPY[s.status] || s.status;
  $("#statusPill").dataset.status = s.status;

  if (s.total_budget <= 0) {
    $("#heroSub").textContent = "Set your budget in Settings to get started ✨";
  } else if (s.remaining < 0) {
    $("#heroSub").textContent = `You're ${fmt(Math.abs(s.remaining))} past the budget. Oopsie 🙈`;
  } else {
    $("#heroSub").textContent = `${fmt(s.total_spent)} spent of ${fmt(s.total_budget)} · ${s.expense_count} expense${s.expense_count === 1 ? "" : "s"}`;
  }

  const pct = Math.min(100, Math.max(0, s.percent_used));
  const fill = $("#meterFill");
  fill.style.width = `${pct}%`;
  fill.dataset.status = s.status;
  $("#meter").setAttribute("aria-label", `${Math.round(s.percent_used)}% of budget used`);
  $("#meterSpent").textContent = `spent ${fmt(s.total_spent)}`;
  $("#meterTotal").textContent = `of ${fmt(s.total_budget)} · ${Math.round(s.percent_used)}%`;

  $("#chipPerDay").textContent = s.avg_per_day > 0
    ? `☕ ${fmt(s.avg_per_day)} / day`
    : "☕ no spending yet";
  $("#chipOwed").textContent = s.owed_to_her > 0
    ? `🤝 ${fmt(s.owed_to_her)} owed to you`
    : "🤝 nobody owes you";

  $("#brandSub").textContent = s.budget_name || "your money, but cuter";
}

function expenseRow(e) {
  return `<li class="expense-item" data-id="${e.id}">
    <span class="expense-emoji">${esc(e.emoji)}</span>
    <div class="expense-main">
      <p class="expense-name">${esc(e.name)}</p>
      <p class="expense-meta">
        <span>${prettyDate(e.spent_on)}</span>
        <span class="dot-sep">${esc(e.category)}</span>
      </p>
    </div>
    <div class="expense-right">
      <span class="expense-amount">${fmt(e.total, { decimals: true })}</span>
      <span class="row-actions">
        <button class="mini-btn" data-del="${e.id}" title="Delete" aria-label="Delete ${esc(e.name)}">🗑️</button>
      </span>
    </div>
  </li>`;
}

function renderRecent() {
  const list = $("#recentList");
  const items = state.dashboard?.recent || [];
  list.innerHTML = items.length
    ? items.map(expenseRow).join("")
    : `<li class="empty"><span class="big">🌷</span>No expenses yet. Add your first one above!</li>`;
  items.forEach((_, i) => {
    const node = list.children[i];
    if (node) node.style.animationDelay = `${i * 40}ms`;
  });
}

function renderStats() {
  const d = state.dashboard;
  if (!d) return;
  const s = d.summary;

  $("#kpiRow").innerHTML = [
    { label: "Budget", value: fmt(s.total_budget), foot: s.budget_name },
    { label: "Spent", value: fmt(s.total_spent), foot: `${Math.round(s.percent_used)}% used` },
    { label: "Left", value: fmt(s.remaining), foot: s.remaining < 0 ? "over budget 🚨" : "still yours 💖" },
    { label: "Owed to you", value: fmt(s.owed_to_her), foot: s.owed_to_her > 0 ? "chase them 👀" : "all clear ✨" },
  ].map((k) => `<div class="kpi">
      <p class="kpi-label">${k.label}</p>
      <p class="kpi-value">${k.value}</p>
      <p class="kpi-foot">${esc(k.foot || "")}</p>
    </div>`).join("");

  $("#dailySub").textContent = `Last ${d.daily.length} days · biggest single buy ${fmt(s.biggest_expense)}`;
  renderMethodChart(s.by_method);
  renderDailyChart(d.daily);
  renderCategoryChart(d.categories);
}

function renderSplits() {
  const s = state.summary;
  if (s) {
    $("#owedToHer").textContent = fmt(s.owed_to_her);
    $("#sheOwes").textContent = fmt(s.she_owes);
  }

  const list = $("#splitList");
  const items = state.splits.filter((x) => state.showSettled || !x.is_settled);

  if (!items.length) {
    list.innerHTML = `<li class="empty"><span class="big">🤝</span>${
      state.showSettled ? "Nothing here yet." : "No open IOUs. Everyone's square! ✨"
    }</li>`;
    return;
  }

  list.innerHTML = items.map((x, i) => {
    const owed = x.direction === "they_owe";
    return `<li class="split-item ${x.is_settled ? "is-settled" : ""}" style="animation-delay:${i * 40}ms">
      <span class="expense-emoji">${esc(x.emoji)}</span>
      <div class="expense-main">
        <p class="split-who">${esc(x.person)} ${owed ? "owes you" : "— you owe"}</p>
        <p class="split-note">${esc(x.note || x.expense_name || "no note")}${x.is_settled ? " · settled ✅" : ""}</p>
      </div>
      <div class="expense-right">
        <span class="split-amount ${owed ? "owed" : "owing"}">${fmt(x.amount, { decimals: true })}</span>
        <span class="row-actions">
          <button class="settle-btn" data-settle="${x.id}" data-settled="${x.is_settled}">
            ${x.is_settled ? "↩️ undo" : "✅ settle"}
          </button>
          <button class="mini-btn" data-split-del="${x.id}" title="Delete" aria-label="Delete IOU from ${esc(x.person)}">🗑️</button>
        </span>
      </div>
    </li>`;
  }).join("");
}

function renderSettings() {
  const s = state.summary;
  if (!s) return;
  $("#bgName").value = s.budget_name;
  $("#bgTotal").value = s.total_budget || "";
  $("#bgCurrency").value = s.currency;
  $("#settingsAccountEmail").textContent = state.user
    ? `Signed in as ${state.user.email}`
    : "";
  $("#settingsNickname").value = state.user?.nickname || "";
}

function syncCurrencySymbols() {
  const { symbol } = currencyInfo();
  $$("[data-currency]").forEach((n) => { n.textContent = symbol; });
}

/* ═══════════════════════════════════════════════════════════
   DATA LOADING
   ═══════════════════════════════════════════════════════════ */

async function loadAll() {
  try {
    const [dash, splits] = await Promise.all([
      api("/dashboard?days=14"),
      api("/splits"),
    ]);
    state.dashboard = dash;
    state.summary = dash.summary;
    state.splits = splits;
    state.currency = dash.summary.currency;

    syncCurrencySymbols();
    renderHome();
    renderRecent();
    renderSplits();
    renderSettings();
    if (state.view === "stats") renderStats();
  } catch (err) {
    toast(`😵 ${err.message}`, "error");
  }
}

async function loadExpenses() {
  const list = $("#expenseList");
  const { q, method, category, month } = state.filters;
  const params = new URLSearchParams({ limit: "300" });
  if (q) params.set("q", q);
  if (method) params.set("method", method);
  if (category) params.set("category", category);
  if (month) params.set("month", month);

  list.innerHTML = `<li class="skeleton"></li><li class="skeleton"></li><li class="skeleton"></li>`;
  try {
    const items = await api(`/expenses?${params}`);
    const sum = items.reduce((t, e) => t + e.total, 0);
    $("#listSummary").textContent = items.length
      ? `${items.length} expense${items.length === 1 ? "" : "s"} · ${fmt(sum, { decimals: true })}`
      : "";
    list.innerHTML = items.length
      ? items.map(expenseRow).join("")
      : `<li class="empty"><span class="big">🔍</span>Nothing matches that. Try clearing the filters.</li>`;
    [...list.children].forEach((n, i) => { n.style.animationDelay = `${Math.min(i, 12) * 35}ms`; });
  } catch (err) {
    list.innerHTML = "";
    toast(`😵 ${err.message}`, "error");
  }
}

async function askBloomie() {
  const text = $("#bloomieText");
  text.innerHTML = `<span class="dots"><i></i><i></i><i></i></span>`;
  try {
    const v = await api("/vibe-check", { method: "POST" });
    $("#bloomieFace").textContent = v.emoji;
    $("#bloomieTag").textContent = v.source === "nvidia" ? "NVIDIA live" : "offline mode";
    $("#bloomieTag").classList.toggle("is-live", v.source === "nvidia");
    typeOut(text, v.message);
  } catch {
    text.textContent = "Bloomie is having a moment. Try again in a sec 💤";
  }
}

function typeOut(node, message) {
  if (document.body.classList.contains("no-motion")) {
    node.textContent = message;
    return;
  }
  node.textContent = "";
  let i = 0;
  const step = () => {
    node.textContent = message.slice(0, ++i);
    if (i < message.length) setTimeout(step, 16);
  };
  step();
}

/* ═══════════════════════════════════════════════════════════
   FORMS & EVENTS
   ═══════════════════════════════════════════════════════════ */

function buildCategoryChips(categories) {
  state.categories = categories;
  $("#categoryRow").innerHTML = categories.map((c, i) => `
    <label class="cat-chip">
      <input type="radio" name="category" value="${c.key}" ${i === categories.length - 1 ? "checked" : ""} />
      <span>${c.emoji} ${esc(c.label)}</span>
    </label>`).join("");

  $("#filterCategory").innerHTML =
    `<option value="">All categories</option>` +
    categories.map((c) => `<option value="${c.key}">${c.emoji} ${esc(c.label)}</option>`).join("");

  $$('input[name="category"]').forEach((r) =>
    r.addEventListener("change", () => {
      state.category = r.value;
      const match = categories.find((c) => c.key === r.value);
      if (match && !$("#exEmoji").dataset.manual) {
        state.emoji = match.emoji;
        $("#exEmoji").textContent = match.emoji;
      }
    })
  );
}

function selectedMethods() {
  return $$('input[name="method"]:checked').map((c) => c.value);
}

function syncMethodInputs() {
  const chosen = selectedMethods();
  const single = $("#singleAmountField");
  const multi = $("#multiAmountField");

  if (chosen.length > 1) {
    single.classList.add("is-hidden");
    multi.classList.remove("is-hidden");
    const grid = $("#multiGrid");
    const existing = Object.fromEntries(
      $$("[data-mamount]", grid).map((i) => [i.dataset.mamount, i.value])
    );
    grid.innerHTML = chosen.map((m) => `
      <div class="multi-row">
        <span class="tagline">${METHOD_META[m].emoji} ${METHOD_META[m].label}</span>
        <div class="money-input">
          <span class="cur" data-currency>${currencyInfo().symbol}</span>
          <input type="number" inputmode="decimal" min="0" step="0.01" placeholder="0.00"
                 data-mamount="${m}" value="${existing[m] ?? ""}"
                 aria-label="Amount paid by ${METHOD_META[m].label}" />
        </div>
      </div>`).join("");
    $$("[data-mamount]", grid).forEach((i) => i.addEventListener("input", updateMultiTotal));
    updateMultiTotal();
  } else {
    single.classList.remove("is-hidden");
    multi.classList.add("is-hidden");
  }
}

function updateMultiTotal() {
  const total = $$("[data-mamount]").reduce((t, i) => t + (parseFloat(i.value) || 0), 0);
  $("#multiTotal").textContent = fmt(total, { decimals: true });
}

function readAmounts() {
  const chosen = selectedMethods();
  const amounts = { cash_amount: 0, gpay_amount: 0, card_amount: 0 };
  if (chosen.length === 0) return { amounts, error: "Tick at least one payment method 💵📱💳" };
  if (chosen.length === 1) {
    const v = parseFloat($("#exAmount").value);
    if (!v || v <= 0) return { amounts, error: "How much was it? 🥺" };
    amounts[`${chosen[0]}_amount`] = v;
  } else {
    let any = false;
    for (const input of $$("[data-mamount]")) {
      const v = parseFloat(input.value) || 0;
      if (v > 0) any = true;
      amounts[`${input.dataset.mamount}_amount`] = v;
    }
    if (!any) return { amounts, error: "Put an amount on at least one method 💸" };
  }
  return { amounts, error: null };
}

function showFormError(id, message) {
  const node = $(id);
  node.textContent = message;
  node.classList.toggle("is-hidden", !message);
}

function resetExpenseForm() {
  $("#exName").value = "";
  $("#exAmount").value = "";
  $("#exNote").value = "";
  $("#exSplitWho").value = "";
  $("#exSplitAmt").value = "";
  $("#exSplitToggle").checked = false;
  $("#splitInline").classList.add("is-hidden");
  $$('input[name="method"]').forEach((c) => { c.checked = false; });
  // hand the emoji back to whatever the selected category suggests
  $("#exEmoji").dataset.manual = "";
  const cat = $('input[name="category"]:checked')?.value;
  const match = state.categories.find((c) => c.key === cat);
  state.emoji = match?.emoji || "🌸";
  $("#exEmoji").textContent = state.emoji;
  syncMethodInputs();
  showFormError("#expenseError", "");
}

function openEmojiPicker(anchor) {
  $(".emoji-pop")?.remove();
  const pop = document.createElement("div");
  pop.className = "emoji-pop card";
  pop.style.cssText =
    "position:fixed;z-index:120;display:grid;grid-template-columns:repeat(8,1fr);gap:.2rem;" +
    "padding:.6rem;max-width:290px;";
  pop.innerHTML = EMOJI_PALETTE.map(
    (e) => `<button type="button" class="mini-btn" style="font-size:1.2rem;opacity:1" data-emoji="${e}">${e}</button>`
  ).join("");
  document.body.append(pop);
  const r = anchor.getBoundingClientRect();
  pop.style.left = `${Math.min(r.left, innerWidth - 300)}px`;
  pop.style.top = `${Math.min(r.bottom + 8, innerHeight - pop.offsetHeight - 8)}px`;

  const close = () => {
    pop.remove();
    document.removeEventListener("pointerdown", onOutside);
    document.removeEventListener("keydown", onKey);
  };
  const onOutside = (ev) => {
    if (!pop.contains(ev.target) && ev.target !== anchor) close();
  };
  const onKey = (ev) => {
    if (ev.key === "Escape") { close(); anchor.focus(); }
  };

  pop.addEventListener("click", (e) => {
    const pick = e.target.closest("[data-emoji]");
    if (!pick) return;
    state.emoji = pick.dataset.emoji;
    anchor.textContent = state.emoji;
    anchor.dataset.manual = "1";
    close();
  });

  document.addEventListener("pointerdown", onOutside);
  document.addEventListener("keydown", onKey);
}

function wireEvents() {
  // nav
  $$(".nav-item").forEach((b) => b.addEventListener("click", () => go(b.dataset.view)));
  $$("[data-goto]").forEach((b) => b.addEventListener("click", () => go(b.dataset.goto)));
  $("#fab").addEventListener("click", () => {
    go("home");
    setTimeout(() => $("#exName").focus(), 320);
  });

  // expense form
  $$('input[name="method"]').forEach((c) => c.addEventListener("change", syncMethodInputs));
  $("#exEmoji").addEventListener("click", (e) => openEmojiPicker(e.currentTarget));
  $("#exSplitToggle").addEventListener("change", (e) =>
    $("#splitInline").classList.toggle("is-hidden", !e.target.checked)
  );

  $("#expenseForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#expenseSubmit");
    const name = $("#exName").value.trim();
    if (!name) return showFormError("#expenseError", "Give it a name, bestie ✨");

    const { amounts, error } = readAmounts();
    if (error) return showFormError("#expenseError", error);
    showFormError("#expenseError", "");

    const body = {
      name,
      emoji: state.emoji,
      category: $('input[name="category"]:checked')?.value || "other",
      note: $("#exNote").value.trim(),
      spent_on: $("#exDate").value || todayISO(),
      ...amounts,
    };
    if ($("#exSplitToggle").checked) {
      const who = $("#exSplitWho").value.trim();
      const amt = parseFloat($("#exSplitAmt").value) || 0;
      if (who && amt > 0) { body.split_with = who; body.split_amount = amt; }
    }

    btn.disabled = true;
    try {
      await api("/expenses", { method: "POST", body });
      confetti();
      toast(`${state.emoji} ${name} logged!`);
      resetExpenseForm();
      await loadAll();
      askBloomie();
    } catch (err) {
      showFormError("#expenseError", err.message);
    } finally {
      btn.disabled = false;
    }
  });

  // delete expense (delegated, both lists)
  document.addEventListener("click", async (e) => {
    const del = e.target.closest("[data-del]");
    if (!del) return;
    const row = del.closest(".expense-item");
    row.style.opacity = ".4";
    try {
      await api(`/expenses/${del.dataset.del}`, { method: "DELETE" });
      toast("Poof! Gone 🫧");
      await loadAll();
      if (state.view === "log") loadExpenses();
    } catch (err) {
      row.style.opacity = "1";
      toast(`😵 ${err.message}`, "error");
    }
  });

  // filters
  let debounce;
  $("#filterQ").addEventListener("input", (e) => {
    clearTimeout(debounce);
    state.filters.q = e.target.value;
    debounce = setTimeout(loadExpenses, 260);
  });
  $("#filterMethod").addEventListener("change", (e) => {
    state.filters.method = e.target.value; loadExpenses();
  });
  $("#filterCategory").addEventListener("change", (e) => {
    state.filters.category = e.target.value; loadExpenses();
  });
  $("#filterMonth").addEventListener("change", (e) => {
    state.filters.month = e.target.value; loadExpenses();
  });

  // splits
  $("#splitForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const person = $("#spPerson").value.trim();
    const amount = parseFloat($("#spAmount").value);
    if (!person) return showFormError("#splitError", "Who is it though? 👀");
    if (!amount || amount <= 0) return showFormError("#splitError", "Amount, please 💸");
    showFormError("#splitError", "");
    try {
      await api("/splits", {
        method: "POST",
        body: {
          person, amount,
          direction: $('input[name="direction"]:checked').value,
          note: $("#spNote").value.trim(),
        },
      });
      $("#spPerson").value = ""; $("#spAmount").value = ""; $("#spNote").value = "";
      toast("IOU saved 💌");
      confetti(12);
      await loadAll();
    } catch (err) {
      showFormError("#splitError", err.message);
    }
  });

  $("#showSettled").addEventListener("change", (e) => {
    state.showSettled = e.target.checked;
    renderSplits();
  });

  $("#splitList").addEventListener("click", async (e) => {
    const settle = e.target.closest("[data-settle]");
    const del = e.target.closest("[data-split-del]");
    try {
      if (settle) {
        const nowSettled = settle.dataset.settled !== "true";
        await api(`/splits/${settle.dataset.settle}`, {
          method: "PATCH", body: { is_settled: nowSettled },
        });
        if (nowSettled) { confetti(14); toast("Paid up! Money's back 💰"); }
        await loadAll();
      } else if (del) {
        await api(`/splits/${del.dataset.splitDel}`, { method: "DELETE" });
        toast("IOU deleted 🫧");
        await loadAll();
      }
    } catch (err) {
      toast(`😵 ${err.message}`, "error");
    }
  });

  // budget
  $("#budgetForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const total = parseFloat($("#bgTotal").value);
    if (isNaN(total) || total < 0) return showFormError("#budgetError", "Pop a number in there 💰");
    showFormError("#budgetError", "");
    try {
      const summary = await api("/budget", {
        method: "PUT",
        body: {
          name: $("#bgName").value.trim() || "My Budget",
          total_amount: total,
          currency: $("#bgCurrency").value,
        },
      });
      state.currency = summary.currency;
      syncCurrencySymbols();
      confetti(18);
      toast("Budget saved 🌷");
      await loadAll();
      askBloomie();
    } catch (err) {
      showFormError("#budgetError", err.message);
    }
  });

  $("#resetBtn").addEventListener("click", async () => {
    if (!confirm("Delete every expense and IOU? This can't be undone 🥺")) return;
    try {
      await api("/budget/reset?keep_budget=true", { method: "POST" });
      toast("Clean slate ✨");
      await loadAll();
      if (state.view === "log") loadExpenses();
    } catch (err) {
      toast(`😵 ${err.message}`, "error");
    }
  });

  // table-view toggles
  $$(".table-toggle").forEach((btn) =>
    btn.addEventListener("click", () => {
      const target = $(`#${btn.dataset.table}`);
      const hidden = target.classList.toggle("is-hidden");
      btn.textContent = hidden ? "table view" : "hide table";
    })
  );

  $("#bloomieRefresh").addEventListener("click", askBloomie);

  $("#logoutBtn").addEventListener("click", logout);
  $("#settingsLogoutBtn").addEventListener("click", logout);

  // first-login onboarding: pick a nickname before entering the app
  $("#nicknameForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const nickname = $("#nicknameInput").value.trim();
    if (!nickname) return showFormError("#nicknameError", "Give Bloomie something to call you 🥺");
    showFormError("#nicknameError", "");
    try {
      await saveNickname(nickname);
      showApp();
      await runApp();
    } catch (err) {
      showFormError("#nicknameError", err.message);
    }
  });

  // settings: edit the nickname later
  $("#settingsNicknameForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const nickname = $("#settingsNickname").value.trim();
    if (!nickname) return showFormError("#settingsNicknameError", "Give Bloomie something to call you 🥺");
    showFormError("#settingsNicknameError", "");
    try {
      await saveNickname(nickname);
      toast("Nickname saved 💫");
    } catch (err) {
      showFormError("#settingsNicknameError", err.message);
    }
  });

  // repaint charts on resize (viewBox handles scale; labels need re-thinning)
  let rs;
  addEventListener("resize", () => {
    clearTimeout(rs);
    rs = setTimeout(() => { if (state.view === "stats") renderStats(); }, 250);
  });

  addEventListener("hashchange", () => {
    const v = location.hash.slice(1);
    if (v && v !== state.view) go(v);
  });

  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (document.documentElement.dataset.theme === "auto") applyTheme("auto");
  });
}

/* ── boot ────────────────────────────────────────────────── */

/** Everything that needs a logged-in session — runs once at boot if already
 *  authenticated, or right after a successful Google sign-in. */
async function runApp() {
  syncMethodInputs();
  await loadAll();
  askBloomie();

  const startView = location.hash.slice(1);
  if (startView && $(`#view-${startView}`)) go(startView);
}

async function boot() {
  initTheme();
  wireEvents();
  startFloaties();
  $("#exDate").value = todayISO();

  let meta;
  try {
    meta = await api("/meta");
    buildCategoryChips(meta.categories);
    if (meta.app_name) {
      $(".brand h1").textContent = meta.app_name;
      document.title = `${meta.app_name} 🌸`;
    }
    $("#aiStatus").textContent = meta.ai_enabled
      ? "Bloomie is powered by NVIDIA NIM 🤖"
      : "Bloomie is in offline mode (add NVIDIA_API_KEY for live sass)";
  } catch {
    buildCategoryChips([{ key: "other", emoji: "✨", label: "Other" }]);
  }

  const auth = await api("/auth/me");
  if (auth.authenticated) {
    state.user = auth.user;
    renderUserBadge();
    await enterApp();
  } else {
    showLoginScreen();
    if (meta?.google_client_id) initGoogleSignIn(meta.google_client_id);
  }
}

boot();
