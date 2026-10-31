"use strict";

const state = {
  band: true,
  meta: null,
  cfg: null,
  frame: null,
  running: true,
  lastSeq: 0,
};

const $ = (id) => document.getElementById(id);
const fmt = (v, d = 3) => (v === null || v === undefined || Number.isNaN(v) ? "–" : v.toFixed(d));
const fmtHz = (f) => {
  if (f === null || f === undefined || !isFinite(f)) return "–";
  if (f >= 1e6) return (f / 1e6).toFixed(3) + " MHz";
  if (f >= 1e3) return (f / 1e3).toFixed(3) + " kHz";
  return f.toFixed(2) + " Hz";
};
const fmtTime = (s) => {
  if (s >= 1) return s.toFixed(3) + " s";
  if (s >= 1e-3) return (s * 1e3).toFixed(3) + " ms";
  if (s >= 1e-6) return (s * 1e6).toFixed(3) + " µs";
  return (s * 1e9).toFixed(1) + " ns";
};

// ------------------------------------------------------------------ 初期化
async function init() {
  const meta = await (await fetch("/api/meta")).json();
  state.meta = meta;
  $("demoBadge").hidden = !meta.demo;

  for (const r of meta.rates) {
    const o = document.createElement("option");
    o.value = o.textContent = r;
    $("rate").appendChild(o);
  }
  for (const r of meta.ch1_ranges) {
    const o = document.createElement("option");
    o.value = o.textContent = r;
    $("ch1rangeSel").appendChild(o);
  }
  for (const r of meta.ch2_ranges) {
    const o = document.createElement("option");
    o.value = o.textContent = r;
    $("ch2rangeSel").appendChild(o);
  }

  state.cfg = { ...meta.defaults };
  try { state.band = localStorage.getItem("dds140.band") !== "0"; } catch (_) {}
  $("band").checked = state.band;
  applyCfgToInputs();
  updateCapacityHint();
  bindInputs();
  resize();
  window.addEventListener("resize", resize);
  loop();
}

function applyCfgToInputs() {
  const c = state.cfg;
  $("rate").value = c.rate;
  $("ch1rangeSel").value = c.ch1;
  $("ch2rangeSel").value = c.ch2;
  $("trigOn").checked = c.trigger !== false;
  $("trigLevel").value = c.trigger_level ?? 50;
  $("trigVal").textContent = (c.trigger_level ?? 50) + "%";
  $("ac1").checked = !!c.ac1;
  $("ac2").checked = !!c.ac2;
  $("skip").value = c.skip;
  $("samples").value = String(c.samples);
  $("runBtn").textContent = c.run ? "Hold" : "Run";
  $("runBtn").classList.toggle("run", c.run);
  $("ch1range").textContent = c.ch1;
  $("ch2range").textContent = c.ch2;
}

async function pushCfg(patch) {
  Object.assign(state.cfg, patch);
  applyCfgToInputs();
  updateCapacityHint();
  await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state.cfg),
  });
}

function bindInputs() {
  $("rate").onchange = (e) => pushCfg({ rate: e.target.value });
  $("ch1rangeSel").onchange = (e) => pushCfg({ ch1: e.target.value });
  $("ch2rangeSel").onchange = (e) => pushCfg({ ch2: e.target.value });
  $("trigOn").onchange = (e) => pushCfg({ trigger: e.target.checked });
  $("trigLevel").oninput = (e) => {
    $("trigVal").textContent = e.target.value + "%";
    pushCfg({ trigger_level: parseInt(e.target.value, 10) });
  };
  $("ac1").onchange = (e) => pushCfg({ ac1: e.target.checked });
  $("ac2").onchange = (e) => pushCfg({ ac2: e.target.checked });
  $("skip").onchange = (e) => pushCfg({ skip: Math.max(0, parseInt(e.target.value || "0", 10)) });
  $("samples").onchange = (e) => pushCfg({ samples: parseInt(e.target.value, 10) });
  $("runBtn").onclick = () => pushCfg({ run: !state.cfg.run });
  $("singleBtn").onclick = () => pushCfg({ run: false });
  $("csvBtn").onclick = () => (window.location = "/api/export?kind=csv");
  $("svgBtn").onclick = () => (window.location = "/api/export?kind=svg");
  $("rate").addEventListener("change", updateCapacityHint);
  $("recBtn").onclick = async () => {
    const seconds = Math.max(0.5, parseFloat($("recSeconds").value || "5"));
    await fetch("/api/record", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seconds }),
    });
  };
  $("band").onchange = (e) => {
    state.band = e.target.checked;
    try { localStorage.setItem("dds140.band", state.band ? "1" : "0"); } catch (_) {}
    draw();
  };

  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.code === "Space") { e.preventDefault(); pushCfg({ run: !state.cfg.run }); }
    if (e.key === "s") pushCfg({ run: false });
    if (e.key === "e") window.location = "/api/export?kind=csv";
  });
}

// ------------------------------------------------------------------ ポーリング
async function loop() {
  try {
    const res = await (await fetch("/api/frame")).json();
    updateStatus(res.status);
    if (res.frame && res.frame.seq !== state.lastSeq) {
      state.lastSeq = res.frame.seq;
      state.frame = res.frame;
      updateMeasurements(res.frame);
      draw();
    } else if (!state.frame) {
      draw();
    }
  } catch (err) {
    updateStatus({ connected: false, error: "サーバに繋がりません" });
  }
  setTimeout(loop, 120);
}

function updateStatus(st) {
  const dot = $("statusDot");
  const text = $("statusText");
  dot.className = "dot";
  if (st.error) {
    dot.classList.add("err");
    text.textContent = "エラー";
    $("msg").textContent = st.error;
  } else if (!st.connected) {
    text.textContent = "デバイス待ち";
    $("msg").textContent = "DDS140 を USB に直挿ししてください";
  } else if (!state.cfg.run) {
    dot.classList.add("hold");
    text.textContent = "Hold";
    $("msg").textContent = "停止中（Run で再開）";
  } else {
    dot.classList.add("ok");
    text.textContent = "Live";
    $("msg").textContent = `フレーム ${st.frames} 受信`;
  }
  $("fps").textContent = (st.fps || 0).toFixed(1) + " fps";
  updateRecordStatus(st);
}

function updateCapacityHint() {
  const meta = state.meta;
  if (!meta || !meta.capacity) return;
  const max = meta.capacity[$("rate").value];
  const hint = $("recHint");
  if (hint && max) {
    hint.textContent = `このレートで 1 回に記録できるのは最大 ${max.toFixed(2)} 秒` +
      `（${meta.max_mb} MB まで）`;
  }
}

let lastRecordKey = null;
function updateRecordStatus(st) {
  const box = $("recStatus");
  const btn = $("recBtn");
  if (st.recording) {
    btn.disabled = true;
    box.innerHTML = `<span class="recording">● 記録中… ${st.record_seconds} 秒ぶん</span>`;
    return;
  }
  btn.disabled = false;
  const last = st.last_record;
  if (!last) { box.textContent = ""; return; }
  const key = last.path + "|" + (last.error || "");
  if (key === lastRecordKey) return;
  lastRecordKey = key;
  if (last.error) {
    box.innerHTML = `<span class="warn">記録に失敗: ${last.error}</span>`;
    return;
  }
  const name = last.path.split("/").pop();
  const rt = last.realtime || 0;
  box.innerHTML =
    `記録しました: ${last.samples.toLocaleString()} サンプル/ch<br>` +
    `<a href="/api/download?name=${encodeURIComponent(name)}&format=bin">.bin</a> / ` +
    `<a href="/api/download?name=${encodeURIComponent(name)}&format=csv">.csv</a><br>` +
    (last.warning ? `<span class="warn">${last.warning}</span>` : `連続性 OK (×${rt.toFixed(2)})`);
}

function updateMeasurements(f) {
  for (const ch of ["ch1", "ch2"]) {
    const s = f[ch].stats || {};
    $(ch + "pp").textContent = fmt(s.pp);
    $(ch + "max").textContent = fmt(s.max);
    $(ch + "min").textContent = fmt(s.min);
    $(ch + "mean").textContent = fmt(s.mean);
    $(ch + "rms").textContent = fmt(s.rms);
    $(ch + "freq").textContent = fmtHz(f[ch].freq);
  }
  $("spanInfo").textContent = `${fmtTime(f.samples * f.dt)} / ${f.samples} smp`;
}

// ------------------------------------------------------------------ 描画
function resize() {
  const c = $("scope");
  const dpr = window.devicePixelRatio || 1;
  const r = c.getBoundingClientRect();
  c.width = Math.max(320, Math.floor(r.width * dpr));
  c.height = Math.max(200, Math.floor(r.height * dpr));
  draw();
}

function draw() {
  const c = $("scope");
  const ctx = c.getContext("2d");
  const w = c.width;
  const h = c.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#070b0f";
  ctx.fillRect(0, 0, w, h);

  const padL = 8, padR = 8, padT = 8, padB = 8;
  const gw = w - padL - padR;
  const gh = h - padT - padB;

  // グリッド（10 x 8）
  ctx.strokeStyle = "#131c26";
  ctx.lineWidth = 1 * (window.devicePixelRatio || 1);
  for (let i = 0; i <= 10; i++) {
    const x = padL + (gw * i) / 10;
    ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + gh); ctx.stroke();
  }
  for (let i = 0; i <= 8; i++) {
    const y = padT + (gh * i) / 8;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + gw, y); ctx.stroke();
  }
  ctx.strokeStyle = "#223042";
  ctx.strokeRect(padL + 0.5, padT + 0.5, gw - 1, gh - 1);

  const f = state.frame;
  if (!f) {
    ctx.fillStyle = "#33414f";
    ctx.font = `${13 * (window.devicePixelRatio || 1)}px ui-monospace, monospace`;
    ctx.fillText("波形待ち…", padL + 14, padT + 26);
    return;
  }

  // 縦はサーバが決めた表示レンジ（1-99 パーセンタイル + 1-2-5 丸め）
  let lo, hi;
  if (f.ylim) {
    [lo, hi] = f.ylim;
  } else {
    const all = f.ch1.envelope.concat(f.ch2.envelope);
    lo = Math.min(...all);
    hi = Math.max(...all);
  }
  if (!isFinite(lo) || !isFinite(hi)) { lo = -1; hi = 1; }
  const span = hi - lo || 1;

  const toY = (v) => padT + gh * (1 - (v - lo) / span);

  // 0V ライン
  if (lo < 0 && hi > 0) {
    ctx.strokeStyle = "#24313f";
    const y0 = toY(0);
    ctx.beginPath(); ctx.moveTo(padL, y0); ctx.lineTo(padL + gw, y0); ctx.stroke();
  }

  drawTrace(ctx, f.ch1.envelope, f.samples, "#3ec6ff", padL, gw, toY, 1);
  drawTrace(ctx, f.ch2.envelope, f.samples, "#ff5e8a", padL, gw, toY, 1);

  // 目盛り（右端に電圧範囲）
  const dpr = window.devicePixelRatio || 1;
  ctx.fillStyle = "#5b6b7b";
  ctx.font = `${11 * dpr}px ui-monospace, monospace`;
  ctx.fillText(`${hi.toFixed(2)}V`, padL + 6, padT + 12 * dpr);
  ctx.fillText(`${lo.toFixed(2)}V`, padL + 6, padT + gh - 4 * dpr);
}

function drawTrace(ctx, env, samples, color, x0, gw, toY, width) {
  const n = env.length;
  if (!n) return;
  const dpr = window.devicePixelRatio || 1;
  const triplets = n !== samples;      // [min, mean, max] の 3 値/列か
  const cols = triplets ? n / 3 : n;
  const dx = gw / Math.max(1, cols - 1);

  if (!triplets) {
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(width, 1.2) * dpr;
    ctx.lineJoin = "round";
    ctx.beginPath();
    for (let i = 0; i < cols; i++) {
      const x = x0 + dx * i;
      const y = toY(env[i]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    return;
  }

  // min/max の帯（うすく） + 平均の線（はっきり）
  if (!state.band) {
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(width, 1.2) * dpr;
    ctx.lineJoin = "round";
    ctx.beginPath();
    for (let i = 0; i < cols; i++) {
      const x = x0 + dx * i;
      const y = toY(env[i * 3 + 1]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    return;
  }
  ctx.save();
  ctx.globalAlpha = 0.30;
  ctx.fillStyle = color;
  ctx.beginPath();
  for (let i = 0; i < cols; i++) {
    const x = x0 + dx * i;
    ctx.lineTo(x, toY(env[i * 3 + 2]));
  }
  for (let i = cols - 1; i >= 0; i--) {
    const x = x0 + dx * i;
    ctx.lineTo(x, toY(env[i * 3]));
  }
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(width, 1.2) * dpr;
  ctx.lineJoin = "round";
  ctx.beginPath();
  for (let i = 0; i < cols; i++) {
    const x = x0 + dx * i;
    const y = toY(env[i * 3 + 1]);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

init();
