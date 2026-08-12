/* BPPM Mini App — worker checklist UI. Vanilla JS, no build step. */
"use strict";

const tg = window.Telegram ? window.Telegram.WebApp : null;
const initData = tg ? tg.initData : "";

const $app = document.getElementById("app");
const $sheetRoot = document.getElementById("sheet-root");

const esc = (s) => String(s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "X-Tg-Init-Data": initData, ...(opts.headers || {}) },
  });
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.json();
}

function haptic(kind) {
  try { tg.HapticFeedback.notificationOccurred(kind); } catch (e) { /* no-op */ }
}
function tap() {
  try { tg.HapticFeedback.selectionChanged(); } catch (e) { /* no-op */ }
}

/* ------------------------------------------------------------------ state */

const state = {
  homeData: null,
  cl: null,          // current checklist {code, name, categories, freq_labels}
  answers: {},       // "cat:taskId" -> {result, note, photo}
};

const monthKey = () => new Date().toISOString().slice(0, 7);
// v2: answers carry values{} and photos[] — old-format drafts are ignored.
const draftKey = (code) => `bppm2:${code}:${monthKey()}`;

function loadDraft(code) {
  try { return JSON.parse(localStorage.getItem(draftKey(code))) || {}; }
  catch (e) { return {}; }
}
function saveDraft() {
  if (state.cl) {
    localStorage.setItem(draftKey(state.cl.code), JSON.stringify(state.answers));
  }
}
function clearDraft(code) { localStorage.removeItem(draftKey(code)); }

function taskList() {
  const out = [];
  for (const cat of state.cl.categories) {
    for (const t of cat.tasks) out.push({ cat: cat.key, id: t.id });
  }
  return out;
}
function answeredCount() {
  return taskList().filter((t) => state.answers[`${t.cat}:${t.id}`]).length;
}

/* ---------------------------------------------------------------- screens */

function renderNote(html) {
  $app.innerHTML = `<div class="center-note">${html}</div>`;
}

function renderRegister() {
  $app.innerHTML = `
    <div class="topbar"><h1>BPPM Inspections</h1></div>
    <div class="card">
      <p>👋 Welcome! Enter your <b>full name</b> to register. The admin will
      approve you before you can submit inspections.</p>
      <input class="form-field" id="reg-name" placeholder="Full name" maxlength="100">
      <button class="big-btn" id="reg-btn">Register</button>
    </div>`;
  document.getElementById("reg-btn").addEventListener("click", async () => {
    const name = document.getElementById("reg-name").value.trim();
    if (!name) return;
    try {
      const r = await api("/api/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      haptic("success");
      if (r.approved) { state.workerName = name; renderMenu(); }
      else renderNote("⏳ Registration sent!<br>You'll be able to start once the admin approves you — check back soon.");
    } catch (e) {
      alert("Registration failed: " + e.message);
    }
  });
}

function renderMenu() {
  state.cl = null;
  const name = state.workerName ? ` · ${esc(state.workerName)}` : "";
  $app.innerHTML = `
    <div class="topbar">
      <h1>BPPM<br><span class="sub">Booster pump maintenance${name}</span></h1>
    </div>
    <button class="menu-card" data-action="pm">
      <span class="menu-emoji">🔧</span>
      <span class="menu-body">
        <b>Preventive Maintenance</b>
        <span>Daily checklist inspections — 72 pump houses</span>
      </span>
      <span class="menu-arrow">›</span>
    </button>
    <div class="menu-card disabled">
      <span class="menu-emoji">🚨</span>
      <span class="menu-body">
        <b>Emergency Work</b>
        <span>Breakdown &amp; repair reporting</span>
      </span>
      <span class="chip due">Coming soon</span>
    </div>`;
}

async function loadHome() {
  renderNote("Loading pump houses…");
  let data;
  try { data = await api("/api/houses"); }
  catch (e) { renderNote("⚠️ " + esc(e.message)); return; }
  state.homeData = data;
  state.workerName = data.worker;
  state.cl = null;
  renderHome();
}

function houseRow(house) {
  const chip = house.done
    ? `<span class="chip done">✅ ${esc(house.done_date)}</span>`
    : `<span class="chip due">Due</span>`;
  return `
    <button class="house-row" data-action="open" data-code="${esc(house.code)}">
      <span class="house-code">${esc(house.code)}</span>
      <span class="house-name">${esc(house.name)}</span>
      ${chip}
    </button>`;
}

function renderHome(filter = "") {
  const d = state.homeData;
  const f = filter.trim().toUpperCase();
  const houses = d.houses.filter((houseItem) =>
    !f || houseItem.code.includes(f) || houseItem.name.toUpperCase().includes(f) ||
    houseItem.code.replace("BPH", "").replace(/^0/, "") === f);
  const pct = d.total ? Math.round((100 * d.covered) / d.total) : 0;
  $app.innerHTML = `
    <div class="topbar">
      <button class="back-btn" data-action="menu">‹ Back</button>
      <h1>Preventive Maintenance<br><span class="sub">${esc(d.month)} · ${esc(d.worker)}</span></h1>
    </div>
    <div class="card progress-wrap">
      <div class="progress-label"><span>Pump houses covered this month</span>
        <b>${d.covered}/${d.total}</b></div>
      <div class="progress-track">
        <div class="progress-fill ${d.covered === d.total ? "full" : ""}" style="width:${pct}%"></div>
      </div>
    </div>
    <input class="search" id="search" placeholder="🔍 Search — e.g. 23 or likas"
           value="${esc(filter)}" autocomplete="off">
    <div id="house-list">${houses.map(houseRow).join("") ||
      '<div class="center-note">No pump house matches.</div>'}</div>`;
  const search = document.getElementById("search");
  search.addEventListener("input", () => {
    const pos = search.selectionStart;
    renderHome(search.value);
    const s2 = document.getElementById("search");
    s2.focus(); s2.setSelectionRange(pos, pos);
  });
}

async function openChecklist(code) {
  renderNote("Loading checklist…");
  let cl;
  try { cl = await api("/api/checklist/" + encodeURIComponent(code)); }
  catch (e) { renderNote("⚠️ " + esc(e.message)); return; }
  if (!cl.categories.length) {
    haptic("success");
    renderNote(`🎉 Nothing is due at <b>${esc(cl.code)} · ${esc(cl.name)}</b> —
      everything was already completed this period.<br><br>
      <button class="big-btn secondary" data-action="back">Back</button>`);
    return;
  }
  state.cl = cl;
  state.answers = loadDraft(cl.code);
  renderChecklist();
}

function segButton(cat, task, res, label, cls, current) {
  const sel = current === res ? ` sel-${cls}` : "";
  return `<button class="${sel.trim() ? "sel " + sel.trim() : ""}"
      data-action="ans" data-cat="${esc(cat)}" data-task="${task}"
      data-res="${res}">${label}</button>`;
}

function renderChecklist() {
  const cl = state.cl;
  const total = taskList().length;
  const done = answeredCount();
  const pct = Math.round((100 * done) / total);
  const scroll = window.scrollY;

  const cats = cl.categories.map((cat) => {
    const catDone = cat.tasks.filter((t) => state.answers[`${cat.key}:${t.id}`]).length;
    const allDone = catDone === cat.tasks.length;
    const tasks = cat.tasks.map((t) => {
      const a = state.answers[`${cat.key}:${t.id}`];
      const cur = a ? a.result : null;
      const freq = t.freq !== "M"
        ? `<span class="freq-badge">${esc(cl.freq_labels[t.freq] || t.freq)}</span>` : "";
      let meta = "";
      if (a) {
        const bits = [];
        const vals = a.values || {};
        for (const k of Object.keys(vals)) {
          if (String(vals[k]).trim()) bits.push(`📏 ${esc(k)}: ${esc(vals[k])}`);
        }
        if (a.result === "issue" && a.note) bits.push(`📝 ${esc(a.note)}`);
        if (a.photos && a.photos.length) {
          bits.push(`📷 ${a.photos.map((p) => esc(p.label)).join(" · ")}`);
        }
        if (bits.length) {
          const cls = a.result === "issue" ? "task-note" : "task-meta";
          meta = `<div class="${cls}">${bits.join("&ensp;·&ensp;")}</div>`;
        }
      }
      return `
        <div class="task">
          <div class="task-desc"><span class="num">${t.id}.</span> ${esc(t.desc)}${freq}</div>
          ${meta}
          <div class="seg">
            ${segButton(cat.key, t.id, "ok", "✅ OK", "ok", cur)}
            ${segButton(cat.key, t.id, "issue", "⚠️ Issue", "issue", cur)}
            ${segButton(cat.key, t.id, "skipped", "⏭ N/A", "na", cur)}
          </div>
        </div>`;
    }).join("");
    const headRight = allDone ? `<span class="cat-done-tick">✓ done</span>` : "";
    return `
      <div class="card" data-cat-card="${esc(cat.key)}">
        <div class="cat-head">
          <h2>${esc(cat.emoji)} ${esc(cat.name)}</h2>
          <span class="cat-count">${catDone}/${cat.tasks.length}</span>
          ${headRight}
        </div>
        ${tasks}
      </div>`;
  }).join("");

  $app.innerHTML = `
    <div class="topbar">
      <button class="back-btn" data-action="back">‹ Back</button>
      <h1>${esc(cl.code)}<br><span class="sub">${esc(cl.name)}</span></h1>
    </div>
    <div class="card progress-wrap">
      <div class="progress-label"><span>Tasks answered</span><b>${done}/${total}</b></div>
      <div class="progress-track">
        <div class="progress-fill ${done === total ? "full" : ""}" style="width:${pct}%"></div>
      </div>
    </div>
    ${cats}
    <div class="bottom-bar"><div class="inner">
      <button class="big-btn" data-action="submit" ${done === total ? "" : "disabled"}>
        ${done === total ? "📤 Submit inspection" : `Answer all tasks (${done}/${total})`}
      </button>
    </div></div>`;
  window.scrollTo(0, scroll);
}

function setAnswer(cat, task, answer) {
  state.answers[`${cat}:${task}`] = answer;
  saveDraft();
  renderChecklist();
}

/* ------------------------------------------------------- OK / issue sheet */

function openSheet(cat, taskId, kind) {
  const catDef = state.cl.categories.find((c) => c.key === cat);
  const task = catDef.tasks.find((t) => t.id === taskId);
  const existing = state.answers[`${cat}:${taskId}`] || {};
  const isIssue = kind === "issue";
  const photoLabels = state.cl.photo_labels || ["Before", "During", "After"];

  // {label: ref} of already-uploaded photos
  const photoRefs = {};
  for (const p of existing.photos || []) photoRefs[p.label] = p.ref;

  const noteField = isIssue
    ? `<textarea id="sheet-note" placeholder="Describe the issue… (required)"
         maxlength="1000">${esc(existing.note || "")}</textarea>` : "";

  const fieldsHtml = (task.fields || []).map((f, i) => `
      <label class="field-label" for="fld-${i}">${esc(f.label)}
        <span class="unit">${esc(f.unit)}</span></label>
      <input class="value-field" id="fld-${i}" data-field="${esc(f.label)}"
        type="text" ${f.type === "number" ? 'inputmode="decimal"' : ""}
        maxlength="60" placeholder="${esc(f.unit)}"
        value="${esc((existing.values || {})[f.label] || "")}">`).join("");

  const slotsHtml = photoLabels.map((pl) => {
    const done = !!photoRefs[pl];
    const required = !isIssue || pl === photoLabels[0];
    return `
      <button class="photo-slot ${done ? "done" : ""}" data-slot="${esc(pl)}">
        <span class="slot-icon">${done ? "✅" : "📷"}</span>
        <span class="slot-label">${esc(pl)}</span>
        <span class="slot-req">${done ? "attached" : (required ? "required" : "optional")}</span>
      </button>`;
  }).join("");

  $sheetRoot.innerHTML = `
    <div class="sheet-backdrop" id="sheet-bd"></div>
    <div class="sheet">
      <h3>${isIssue ? "⚠️" : "✅"} ${esc(task.desc)}</h3>
      ${noteField}
      ${fieldsHtml ? `<div class="fields">${fieldsHtml}</div>` : ""}
      <div class="photo-req-note">${isIssue
        ? "Evidence photo required (Before = defect found)"
        : "Work-proof photos required: Before, During, After"}</div>
      <div class="photo-slots">${slotsHtml}</div>
      <input type="file" id="photo-input" accept="image/*" capture="environment" hidden>
      <div class="sheet-actions">
        <button class="big-btn secondary" id="sheet-cancel">Cancel</button>
        <button class="big-btn ${isIssue ? "" : "ok"}" id="sheet-save">
          ${isIssue ? "Save issue" : "Save OK"}</button>
      </div>
    </div>`;

  const close = () => { $sheetRoot.innerHTML = ""; };
  document.getElementById("sheet-bd").addEventListener("click", close);
  document.getElementById("sheet-cancel").addEventListener("click", close);

  const input = document.getElementById("photo-input");
  let currentSlot = null;
  for (const btn of $sheetRoot.querySelectorAll(".photo-slot")) {
    btn.addEventListener("click", () => {
      currentSlot = btn.dataset.slot;
      input.click();
    });
  }
  input.addEventListener("change", async () => {
    if (!input.files.length || !currentSlot) return;
    const btn = $sheetRoot.querySelector(`.photo-slot[data-slot="${currentSlot}"]`);
    btn.querySelector(".slot-req").textContent = "uploading…";
    try {
      const fd = new FormData();
      fd.append("photo", input.files[0]);
      const r = await api("/api/photo", { method: "POST", body: fd });
      photoRefs[currentSlot] = r.photo;
      btn.classList.add("done");
      btn.querySelector(".slot-icon").textContent = "✅";
      btn.querySelector(".slot-req").textContent = "attached";
      tap();
    } catch (e) {
      btn.querySelector(".slot-req").textContent = "failed — retry";
    }
    input.value = "";
  });

  document.getElementById("sheet-save").addEventListener("click", () => {
    const note = isIssue ? document.getElementById("sheet-note").value.trim() : "";
    const values = {};
    for (const inp of $sheetRoot.querySelectorAll(".value-field")) {
      values[inp.dataset.field] = inp.value.trim();
    }
    // Enforcement: OK needs every reading + all photos; Issue needs
    // description + the "Before" (defect) photo at minimum.
    if (!isIssue) {
      for (const f of task.fields || []) {
        const v = values[f.label];
        if (!v) { alert(`Please enter: ${f.label} (${f.unit})`); return; }
        if (f.type === "number" && isNaN(parseFloat(v.replace(",", ".")))) {
          alert(`${f.label} must be a number (${f.unit})`); return;
        }
      }
      const missing = photoLabels.filter((pl) => !photoRefs[pl]);
      if (missing.length) {
        alert(`Photo required: ${missing.join(", ")}`); return;
      }
    } else {
      if (!note) { alert("Please describe the issue."); return; }
      if (!Object.keys(photoRefs).length) {
        alert("Please attach at least the 'Before' (defect) photo."); return;
      }
    }
    const photos = photoLabels
      .filter((pl) => photoRefs[pl])
      .map((pl) => ({ label: pl, ref: photoRefs[pl] }));
    close();
    haptic(isIssue ? "warning" : "success");
    setAnswer(cat, taskId, { result: kind, note, values, photos });
  });
}

/* ----------------------------------------------------------------- submit */

async function submit() {
  const cl = state.cl;
  const results = taskList().map((t) => {
    const a = state.answers[`${t.cat}:${t.id}`];
    return { category: t.cat, task_id: t.id, result: a.result,
             note: a.note || null, values: a.values || {},
             photos: a.photos || [] };
  });
  const doSubmit = async () => {
    renderNote("Submitting…");
    try {
      const r = await api("/api/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ house: cl.code, results }),
      });
      clearDraft(cl.code);
      haptic("success");
      renderSuccess(cl, r.counts);
    } catch (e) {
      haptic("error");
      alert("Submit failed: " + e.message);
      renderChecklist();
    }
  };
  const msg = `Submit inspection for ${cl.code} · ${cl.name}?`;
  if (tg && tg.showConfirm) tg.showConfirm(msg, (ok) => { if (ok) doSubmit(); });
  else if (confirm(msg)) doSubmit();
}

function renderSuccess(cl, counts) {
  state.cl = null;
  $app.innerHTML = `
    <div class="success card">
      <div class="emoji">✅</div>
      <h2>Inspection submitted</h2>
      <p><b>${esc(cl.code)} · ${esc(cl.name)}</b></p>
      <p class="counts">✅ OK: ${counts.ok} &nbsp; ⚠️ Issues: ${counts.issue}
        &nbsp; ⏭ N/A: ${counts.skipped}</p>
      <button class="big-btn" data-action="back">Next pump house</button>
    </div>`;
}

/* ------------------------------------------------------------- delegation */

$app.addEventListener("click", (ev) => {
  const btn = ev.target.closest("[data-action]");
  if (!btn) return;
  const a = btn.dataset;
  if (a.action === "open") { tap(); openChecklist(a.code); }
  else if (a.action === "pm") { tap(); loadHome(); }
  else if (a.action === "menu") { tap(); renderMenu(); }
  else if (a.action === "back") { tap(); loadHome(); }
  else if (a.action === "submit" && !btn.disabled) submit();
  else if (a.action === "ans") {
    tap();
    // OK and Issue prompt for reading/photo; N/A needs nothing.
    if (a.res === "skipped") setAnswer(a.cat, parseInt(a.task, 10), { result: "skipped" });
    else openSheet(a.cat, parseInt(a.task, 10), a.res);
  }
});

/* ------------------------------------------------------------------- boot */

async function boot() {
  if (!tg || !initData) {
    renderNote("Please open this app from inside Telegram (via the BPPM bot).");
    return;
  }
  tg.ready();
  tg.expand();
  try {
    const me = await api("/api/me");
    if (!me.worker) renderRegister();
    else if (!me.worker.approved) {
      renderNote("⏳ Waiting for admin approval.<br>Check back soon!");
    } else {
      state.workerName = me.worker.name;
      renderMenu();
    }
  } catch (e) {
    renderNote("⚠️ Could not connect: " + esc(e.message));
  }
}

boot();
