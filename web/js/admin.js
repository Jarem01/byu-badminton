// Admin controller: import/validate, player overrides, divisions, brackets.
let currentDivision = null;

// --- tabs -------------------------------------------------------------------
document.querySelectorAll(".tabs button").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll(".tabs button").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    document.getElementById("tab-" + b.dataset.tab).classList.add("active");
    if (b.dataset.tab === "draw") { loadDivisions(); loadPlanWindow(); }
    if (b.dataset.tab === "manage") { manageView === "board" ? loadBoard() : loadManagerDivisions(); }
    if (b.dataset.tab === "schedule") { loadBestDates(); loadSchedule(); }
    if (b.dataset.tab === "settings") loadSettings();
  };
});

// Manager sub-nav: Court board (live) vs per-division view.
let manageView = "board";
document.querySelectorAll("#msubnav button").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll("#msubnav button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    manageView = b.dataset.mv;
    document.getElementById("mview-board").style.display = manageView === "board" ? "" : "none";
    document.getElementById("mview-division").style.display = manageView === "division" ? "" : "none";
    manageView === "board" ? loadBoard() : loadManagerDivisions();
  };
});

// --- help modal -------------------------------------------------------------
document.getElementById("btn-help").onclick = () =>
  document.getElementById("help-modal").classList.add("show");
document.getElementById("help-modal").addEventListener("click", (e) => {
  if (e.target.id === "help-modal" || e.target.dataset.act === "close-help")
    document.getElementById("help-modal").classList.remove("show");
});

// --- format explainers ------------------------------------------------------
const FORMAT_HELP = {
  single_elim: "Single elimination — lose once and you're out. Fast; best when time is tight.",
  double_elim: "Double elimination — a losers bracket gives everyone a second chance (needs 4/8/16 entrants).",
  round_robin: "Round robin — everyone plays everyone. Most games; best for small fields (≤6).",
  group_knockout: "Groups → knockout — round-robin pools, then top finishers advance to a knockout. Great for medium fields.",
};
function wireFormatHelp(selectId, outId) {
  const sel = document.getElementById(selectId), out = document.getElementById(outId);
  if (!sel || !out) return;
  const upd = () => { out.textContent = FORMAT_HELP[sel.value] || ""; };
  sel.addEventListener("change", upd); upd();
}
wireFormatHelp("cb-format", "cb-format-help");

// --- stepper status (guides the organizer through the flow) -----------------
async function updateStepper() {
  let players = 0, hasBracket = false, sched = 0;
  try { players = (await API.get("/api/players")).players.length; } catch {}
  try { hasBracket = (await API.get("/api/divisions")).divisions.some(d => d.has_bracket); } catch {}
  try { sched = (await API.get("/api/schedule")).blocks.length; } catch {}

  const state = {
    import: players > 0 ? "done" : "current",
    draw: !players ? "locked" : (hasBracket ? "done" : "current"),
    schedule: !hasBracket ? "locked" : (sched ? "done" : "current"),
    settings: "",
    manage: !hasBracket ? "locked" : "current",
  };
  const numbers = { import: 1, draw: 2, schedule: 3, manage: 4 };
  document.querySelectorAll("#tabs button").forEach(b => {
    const s = state[b.dataset.tab];
    b.classList.remove("done", "current", "locked");
    if (s) b.classList.add(s);
    const dot = b.querySelector(".dot");        // Settings has no dot (unnumbered)
    if (dot) dot.textContent = s === "done" ? "✓" : numbers[b.dataset.tab];
  });

  const set = (id, html) => { const e = document.getElementById(id); if (e) e.innerHTML = html; };
  set("guide-import-status", players ? `<b style="color:var(--ok)">✓ ${players} players imported.</b>` : "");
  set("guide-draw-status", !players
    ? '<b style="color:var(--warn)">Import data first (Step 1).</b>'
    : (hasBracket ? '<b style="color:var(--ok)">✓ bracket(s) generated.</b>' : ""));
  set("guide-schedule-status", !hasBracket
    ? '<b style="color:var(--warn)">Generate a bracket first (Step 2).</b>'
    : (sched ? `<b style="color:var(--ok)">✓ ${sched} matches scheduled.</b>` : ""));
  document.getElementById("guide-draw").classList.toggle("locked", !players);
  document.getElementById("guide-schedule").classList.toggle("locked", !hasBracket);
}

// --- health -----------------------------------------------------------------
async function ping() {
  try { await API.get("/api/health"); document.getElementById("status").textContent = "connected"; }
  catch { document.getElementById("status").textContent = "offline"; }
}

// --- import -----------------------------------------------------------------
function srcValue() { return document.querySelector('input[name="src"]:checked').value; }

document.getElementById("btn-preview").onclick = async () => {
  try {
    const res = await API.post("/api/import", {
      source: srcValue(), ref: document.getElementById("ref").value,
      schema: document.getElementById("schema").value,
    });
    document.getElementById("import-stats").textContent =
      `Adapter: ${res.adapter} · players ${res.stats.players} (+${res.stats.stub_players} placeholders) · ` +
      `registrations ${res.stats.registrations}`;
    renderIssues(res.validation);
    loadPlayers();     // show preview roster so gender/skill fixes apply pre-commit
    loadPartnerships();
    document.getElementById("btn-commit").disabled = false;
    toast("Preview ready — review and fix below, then Commit");
  } catch (e) { toast(e.message, true); }
};

document.getElementById("btn-commit").onclick = async () => {
  try {
    const r = await API.post("/api/import/commit", {});
    document.getElementById("btn-commit").disabled = true;
    toast(`Committed ${r.players} players`);
    refreshAll();
  } catch (e) { toast(e.message, true); }
};

document.getElementById("btn-revalidate").onclick = () => refreshAll();

// --- validation -------------------------------------------------------------
async function mergeInto(keep, people) {
  const others = people.filter(p => p.id !== keep.id);
  const names = others.map(o => `"${o.name}"`).join(", ");
  const ok = window.confirm(
    `Keep "${keep.name}" and merge ${names} into them?\n\n` +
    `Their registrations, partner requests, pairs and events move to ` +
    `"${keep.name}" and the duplicate is removed. The merge is logged.`);
  if (!ok) return;
  try {
    let last = null;
    for (const o of others) {
      last = await API.post("/api/player/merge", { keep: keep.id, drop: o.id });
    }
    if (last && last.view) { partnerView = last.view; renderPartnerships(); }
    toast(`Kept ${keep.name} — merged ${others.length} duplicate` +
          `${others.length === 1 ? "" : "s"}`);
    loadPlayers(); loadValidation();
  } catch (e) { toast(e.message, true); loadValidation(); }
}

document.getElementById("btn-undo-merge").onclick = async () => {
  try {
    const r = await API.post("/api/player/merge/undo", {});
    toast((r.notes && r.notes[0]) || "merge undone");
    loadPlayers(); loadPartnerships(); loadValidation();
  } catch (e) { toast(e.message, true); }
};

function renderIssues(val) {
  const c = val.counts || { error: 0, warning: 0, info: 0 };
  document.getElementById("val-counts").textContent =
    `(${c.error} errors · ${c.warning} warnings · ${c.info} info)`;
  const box = document.getElementById("issues");
  box.innerHTML = "";
  (val.issues || []).forEach(i => {
    const d = document.createElement("div");
    d.className = "issue " + i.severity;
    d.innerHTML = `<span class="badge ${i.severity === "error" ? "err" : i.severity}">${i.severity}</span> ` +
      `${i.message}` + (i.suggestion ? ` <span class="sugg">→ ${i.suggestion}</span>` : "");
    const people = (i.data && i.data.players) || [];
    if (people.length > 1) {
      const wrap = document.createElement("span");
      wrap.className = "issue-actions";
      const seen = people.map(p => people.filter(o => o.name === p.name).length);
      // The longest name is usually the fullest one ("Zhi-Han Tsai" over
      // "Zhihan"), so keeping it is offered first and highlighted; any of the
      // others can still be kept instead.
      const order = people.map((_p, i) => i).sort((x, y) =>
        people[y].name.length - people[x].name.length || x - y);
      order.forEach((i, rank) => {
        const p = people[i];
        const b = document.createElement("button");
        b.className = "btn merge-btn" + (rank ? " ghost" : "");
        // two entries with the same name would otherwise give identical buttons
        b.textContent = `Merge into ${p.name}` +
          (seen[i] > 1 ? ` (entry ${i + 1})` : "");
        b.title = rank
          ? `Keep ${p.name} and fold the other ${people.length - 1} into them`
          : `Keep ${p.name} (the fuller name — the default) and fold the ` +
            `other ${people.length - 1} into them`;
        b.onclick = () => mergeInto(p, people);
        wrap.appendChild(b);
      });
      d.appendChild(wrap);
    }
    box.appendChild(d);
  });
  if (!(val.issues || []).length) box.innerHTML = '<p class="muted">No issues found.</p>';
}

async function loadValidation() {
  try { renderIssues(await API.get("/api/validation")); } catch (e) {}
}

// --- players (inline overrides) --------------------------------------------
const ALL_EVENTS = ["MS", "WS", "MD", "WD", "XD"];

async function loadPlayers() {
  let data;
  try { data = await API.get("/api/players"); } catch { return; }
  // A preview lives on the server, so it survives a reload; the button must
  // follow that, not just whether Preview was clicked in this page session.
  const commit = document.getElementById("btn-commit");
  if (commit) commit.disabled = !data.preview;
  const tb = document.querySelector("#players tbody");
  tb.innerHTML = "";
  document.getElementById("player-count").textContent = `(${data.players.length})`;
  const undo = document.getElementById("btn-undo-merge");
  if (undo) {
    const merges = data.merges || [];
    undo.disabled = !merges.length;
    undo.textContent = merges.length
      ? `Undo merge (${merges.length})` : "Undo merge";
    undo.title = merges.length
      ? `Put "${merges[merges.length - 1].dropped}" back as its own entry, ` +
        `undone the merge into "${merges[merges.length - 1].kept}"`
      : "No merge to undo";
  }
  data.players.forEach(p => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${p.name}</td>
      <td><select data-f="gender">${["M","F","U"].map(g =>
        `<option ${g === p.gender ? "selected" : ""}>${g}</option>`).join("")}</select></td>
      <td><input data-f="skill" type="number" min="1" max="9" value="${p.skill ?? ""}" style="width:60px"></td>
      <td class="ev-cell">${ALL_EVENTS.map(e => {
        const on = (p.events || []).includes(e);
        return `<button type="button" class="ev-chip${on ? " on" : ""}" data-ev="${e}" ` +
          `title="${on ? "in " + e + " — click to take them out" : "not in " + e + " — click to add them"}">${e}</button>`;
      }).join("")}</td>
      <td>${p.stub ? '<span class="badge stub">placeholder</span>' : ""}
          ${p.willing_random ? '<span class="pill">random ok</span>' : ""}</td>
      <td><input data-f="withdrawn" type="checkbox" ${p.withdrawn ? "checked" : ""}></td>`;
    tr.querySelectorAll(".ev-chip").forEach(chip => {
      chip.onclick = async () => {
        const want = new Set(p.events || []);
        want.has(chip.dataset.ev) ? want.delete(chip.dataset.ev) : want.add(chip.dataset.ev);
        try {
          const r = await API.post("/api/player/events",
                                   { player: p.id, events: [...want] });
          toast(`${p.name}: ${(r.notes || []).join(", ") || "events updated"}`);
          loadPlayers(); loadPartnerships(); loadValidation();
        } catch (e) { toast(e.message, true); }
      };
    });
    tr.querySelectorAll("[data-f]").forEach(el => {
      el.addEventListener("change", async () => {
        const field = el.dataset.f;
        const value = el.type === "checkbox" ? el.checked : el.value;
        try {
          await API.post("/api/override", { target: `player:${p.id}`, field, value: String(value) });
          toast(`${p.name}: ${field} updated`);
          loadValidation();
        } catch (e) { toast(e.message, true); loadPlayers(); }
      });
    });
    tb.appendChild(tr);
  });
}

// --- partnerships: one row per player per doubles event ---------------------
let partnerView = null;

const PARTNER_RULE = { MM: ["M"], FF: ["F"] };
const PARTNER_STATUS = {
  paired:   ["ok", "paired"],
  agreed:   ["ok", "agreed"],
  waiting:  ["warn", "waiting on them"],
  incoming: ["info", "they asked you"],
  blocked:  ["err", "not honoured"],
  open:     ["", "no partner"],
};

function partnerGenderOk(ev, self, cand) {
  if (!self.gender || !cand.gender) return true;
  if (self.gender === "U" || cand.gender === "U") return true;   // unknown
  if (ev.rule === "MF") return cand.gender !== self.gender;
  return cand.gender === PARTNER_RULE[ev.rule][0];
}

async function loadPartnerships() {
  try { partnerView = await API.get("/api/partnerships"); } catch { partnerView = null; }
  renderPartnerships();
}

function renderPartnerships() {
  const box = document.getElementById("partnerships-body");
  const note = document.getElementById("partnerships-note");
  if (!box) return;
  if (!partnerView || !(partnerView.events || []).length) {
    box.innerHTML = '<p class="muted">No doubles players yet — import registrations first.</p>';
    note.textContent = "";
    return;
  }
  const locked = !partnerView.editable;
  note.textContent = locked ? partnerView.reason
    : "One row per player. Pick a partner to pair them, or Unpair to free both players. " +
      "Gender and skill come from the roster — fix those in Players above.";
  box.innerHTML = partnerView.events.map(ev => {
    const head = `<div class="partner-head"><b>${ev.label}</b> <span class="muted">` +
      `${ev.players} players · ${ev.paired} pair(s) · ${ev.open} without a partner</span>` +
      `<span class="partner-actions">` +
      `<label class="inline" title="Same number reproduces the same shuffle">Shuffle ` +
      `<input type="number" value="1" data-seed="${ev.event}" style="width:64px" ${locked ? "disabled" : ""}></label>` +
      `<button class="btn secondary" data-shuffle="${ev.event}" ${locked ? "disabled" : ""}>Shuffle this event</button>` +
      `<button class="btn secondary" data-repair="${ev.event}" ${locked ? "disabled" : ""}>Re-pair from forms</button>` +
      `<button class="btn ghost" data-undo="${ev.event}" ${locked ? "disabled" : ""}>Undo last change</button>` +
      `</span></div>`;
    const rows = ev.rows.map(r => partnerRow(ev, r, locked)).join("");
    return `<div class="partner-event">${head}<div class="partner-scroll">` +
      `<table class="partners"><thead><tr><th>Name</th><th>G</th><th>Skill</th>` +
      `<th>Partner</th><th>G</th><th>Skill</th><th>Status</th>` +
      `<th>Set partner</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
  }).join("");
  box.querySelectorAll("select[data-player]").forEach(s => { s.onchange = onPartnerPick; });
  box.querySelectorAll("button[data-clear]").forEach(b => { b.onclick = onPartnerClear; });
  box.querySelectorAll("button[data-confirm]").forEach(b => { b.onclick = onPartnerConfirm; });
  box.querySelectorAll("button[data-shuffle]").forEach(b => { b.onclick = onPartnerShuffle; });
  box.querySelectorAll("button[data-repair]").forEach(b => { b.onclick = onPartnerRepair; });
  box.querySelectorAll("button[data-undo]").forEach(b => { b.onclick = onPartnerUndo; });
}

function partnerRow(ev, r, locked) {
  const p = r.player, q = r.partner;
  const [cls, label] = PARTNER_STATUS[r.status] || ["", r.status];
  const current = q ? q.id : "";
  const cands = (ev.candidates || []).filter(c => c.id !== p.id);
  const option = (c) => `<option value="${c.id}"${c.id === current ? " selected" : ""}>` +
    `${c.name}${c.stub ? " (placeholder)" : ""}` +
    `${c.gender ? " (" + c.gender + ")" : ""}` +
    `${c.skill != null ? " · " + c.skill : ""}` +
    `${c.paired_with && c.id !== current ? " — paired with " + c.paired_with : ""}</option>`;
  const group = (title, list) => list.length
    ? `<optgroup label="${title}">${list.map(option).join("")}</optgroup>` : "";
  const inEvent = cands.filter(c => c.entered);
  const opts = '<option value="">— none —</option>' +
    group(`In ${ev.event}`, inEvent.filter(c => partnerGenderOk(ev, p, c))) +
    group(`${ev.event} — gender rule mismatch`, inEvent.filter(c => !partnerGenderOk(ev, p, c))) +
    group(`Not in ${ev.event} (will be added)`, cands.filter(c => !c.entered));
  const note = r.note ? `<div class="partner-note">${r.note}</div>` : "";
  const issue = r.issue ? `<div class="pair-issue">${r.issue}</div>` : "";
  const linked = r.status !== "open";
  const open_to_confirm = q && (r.status === "waiting" || r.status === "incoming"
                                || r.status === "agreed");
  const confirm = open_to_confirm
    ? `<button class="btn" data-ev="${ev.event}" data-confirm="${p.id}" ` +
      `data-partner="${q.id}" ${locked ? "disabled" : ""} ` +
      `title="Make this an accepted pair">Confirm</button> ` : "";
  const clear = linked
    ? `<button class="btn ghost" data-ev="${ev.event}" data-clear="${p.id}" ` +
      `${locked ? "disabled" : ""}>${r.status === "paired" || r.status === "agreed"
        ? "Unpair" : "Clear"}</button>` : "";
  return `<tr class="partner-${r.status}">` +
    `<td>${p.name}</td><td>${p.gender || "?"}</td><td>${p.skill != null ? p.skill : "—"}</td>` +
    `<td>${q ? q.name : '<span class="muted">—</span>'}</td>` +
    `<td>${q ? (q.gender || "?") : ""}</td>` +
    `<td>${q && q.skill != null ? q.skill : ""}</td>` +
    `<td class="status-cell"><span class="badge ${cls}">${label}</span>${issue}${note}</td>` +
    `<td class="partner-pick">` +
      `<select data-ev="${ev.event}" data-player="${p.id}" ${locked ? "disabled" : ""}>${opts}</select>` +
      `${confirm || clear ? `<div class="partner-buttons">${confirm}${clear}</div>` : ""}</td>` +
    `</tr>`;
}

async function savePartnership(path, body) {
  try {
    const r = await API.post(path, body);
    partnerView = r.view;
    renderPartnerships();
    loadValidation();
    loadPlayers();
    if (r.rebuilt) loadDivisions();
    return r;
  } catch (e) { toast(e.message, true); loadPartnerships(); return null; }
}

async function onPartnerPick(e) {
  const sel = e.target;
  const r = sel.value
    ? await savePartnership("/api/partnership/assign",
        { event: sel.dataset.ev, player: sel.dataset.player, partner: sel.value })
    : await savePartnership("/api/partnership/clear",
        { event: sel.dataset.ev, player: sel.dataset.player });
  if (r) toast(r.notes && r.notes.length ? `Saved — ${r.notes.join(", ")}` : "Partnership saved");
}

async function onPartnerConfirm(e) {
  const b = e.target;
  const r = await savePartnership("/api/partnership/assign",
    { event: b.dataset.ev, player: b.dataset.confirm, partner: b.dataset.partner });
  if (r) toast("Partnership confirmed");
}

async function onPartnerShuffle(e) {
  const b = e.target;
  const ev = b.dataset.shuffle;
  const seedEl = document.querySelector(`input[data-seed="${ev}"]`);
  const seed = seedEl ? parseInt(seedEl.value, 10) : 1;
  try {
    const r = await API.post("/api/pairs/shuffle",
      { event: ev, rng_seed: isNaN(seed) ? null : seed });
    await loadPartnerships();
    loadValidation();
    if (r.rebuilt) loadDivisions();
    toast(`${ev} shuffled`);
  } catch (err) { toast(err.message, true); }
}

async function onPartnerRepair(e) {
  const b = e.target;
  const ev = b.dataset.repair;
  const seedEl = document.querySelector(`input[data-seed="${ev}"]`);
  const seed = seedEl ? parseInt(seedEl.value, 10) : 1;
  try {
    const r = await API.post("/api/pairs/auto",
      { event: ev, rng_seed: isNaN(seed) ? null : seed });
    await loadPartnerships();
    loadValidation();
    if (r.rebuilt) loadDivisions();
    const made = (r.auto_paired || []).length;
    toast(made ? `${ev} re-paired (${made} auto pair(s))` : `${ev} re-paired from forms`);
  } catch (err) { toast(err.message, true); }
}

async function onPartnerUndo(e) {
  const b = e.target;
  const ev = b.dataset.undo;
  try {
    const r = await API.post("/api/pairs/undo", { event: ev });
    await loadPartnerships();
    loadPlayers();      // an undo can take an event back off a partner's entry
    loadValidation();
    if (r.rebuilt) loadDivisions();
    toast((r.notes && r.notes[0]) || `${ev} pair change undone`);
  } catch (err) { toast(err.message, true); }
}

async function onPartnerClear(e) {
  const b = e.target;
  const r = await savePartnership("/api/partnership/clear",
    { event: b.dataset.ev, player: b.dataset.clear });
  if (r) toast(r.notes && r.notes.length ? `Cleared — ${r.notes.join(", ")}` : "Partnership cleared");
}

// --- divisions & brackets ---------------------------------------------------
const FORMATS = ["single_elim", "double_elim", "round_robin", "group_knockout"];

document.getElementById("btn-build").onclick = async () => {
  try {
    const seed = parseInt(document.getElementById("group-seed").value, 10);
    const r = await API.post("/api/divisions/build", { rng_seed: isNaN(seed) ? null : seed });
    const notes = document.getElementById("group-notes");
    notes.innerHTML = (r.auto_paired.length ? `<b>Auto-paired:</b><br>${r.auto_paired.join("<br>")}` : "") +
      (r.unpaired.length ? `<br><b>Unpaired (need attention):</b> ${r.unpaired.join(", ")}` : "");
    toast("Divisions built");
    loadDivisions();
    loadPartnerships();
  } catch (e) { toast(e.message, true); }
};

async function loadDivisions() {
  let data;
  try { data = await API.get("/api/divisions"); } catch { return; }
  const tb = document.querySelector("#divisions tbody");
  tb.innerHTML = "";
  data.divisions.forEach(d => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><b>${d.label}</b></td>
      <td>${d.entries}</td>
      <td><select data-f="format">${FORMATS.map(f =>
        `<option ${f === d.format ? "selected" : ""}>${f}</option>`).join("")}</select></td>
      <td><select data-f="method">
        <option value="ranking"${d.seed_method === "ranking" ? " selected" : ""}>ranking (skill)</option>
        <option value="random"${d.seed_method === "random" ? " selected" : ""}>random</option></select></td>
      <td><input data-f="seed" type="number" value="${d.seed_no == null ? "" : d.seed_no}" placeholder="opt" style="width:70px"></td>
      <td>
        <button class="btn" data-act="plan">Plan / preview</button>
        <button class="btn secondary" data-act="gen">Generate</button>
        <button class="btn ghost" data-act="final">${d.finalized ? "Un-finalize" : "Finalize"}</button>
      </td>
      <td>${d.has_bracket ? '<span class="badge ok">bracket</span>' : '<span class="pill">no bracket</span>'}
          ${d.finalized ? '<span class="badge info">final</span>' : ""}</td>`;
    tr.querySelector('[data-f="format"]').onchange = (e) =>
      API.post("/api/division/format", { division: d.id, format: e.target.value }).catch(x => toast(x.message, true));
    // Remember the seeding too, so a rebuild keeps it.
    const saveSeed = () => {
      const seed = parseInt(tr.querySelector('[data-f="seed"]').value, 10);
      API.post("/api/division/seed", {
        division: d.id, method: tr.querySelector('[data-f="method"]').value,
        rng_seed: isNaN(seed) ? null : seed,
      }).catch(x => toast(x.message, true));
    };
    tr.querySelector('[data-f="method"]').onchange = saveSeed;
    tr.querySelector('[data-f="seed"]').onchange = saveSeed;
    tr.querySelector('[data-act="plan"]').onclick = () => planDivision(d);
    tr.querySelector('[data-act="gen"]').onclick = () => generate(d, tr);
    tr.querySelector('[data-act="final"]').onclick = () => toggleFinal(d);
    tb.appendChild(tr);
  });
  syncPlannerInputs();   // keep the planner window aligned with Settings
  updateStepper();
}

async function generate(d, tr) {
  const method = tr.querySelector('[data-f="method"]').value;
  const seedVal = tr.querySelector('[data-f="seed"]').value;
  const format = tr.querySelector('[data-f="format"]').value;
  try {
    await API.post("/api/bracket/generate", {
      division: d.id, format, method,
      rng_seed: seedVal === "" ? null : parseInt(seedVal, 10),
      force: d.finalized ? confirm("Bracket finalized. Replace it?") : false,
    });
    toast(`${d.label} bracket generated`);
    loadDivisions();
    showBracket(d.id, d.label);
  } catch (e) {
    if (e.status === 409) toast("Finalized — tick force to replace", true);
    else toast(e.message, true);
  }
}

async function toggleFinal(d) {
  try {
    await API.post(d.finalized ? "/api/bracket/unfinalize" : "/api/bracket/finalize", { division: d.id });
    toast(d.finalized ? "Un-finalized" : "Finalized");
    loadDivisions();
  } catch (e) { toast(e.message, true); }
}

// --- planner / compare formats ---------------------------------------------
let planDiv = null, planLabel = null, lastPlan = null, appliedKey = null;
const planKey = (o) => `${o.format}|${(o.params && o.params.num_groups) || ""}|${(o.params && o.params.main_draw) || ""}`;
const FMT_LABEL = {
  single_elim: "Single elimination", double_elim: "Double elimination",
  round_robin: "Round robin", group_knockout: "Groups → knockout",
};

async function planDivision(d) {
  if (planDiv !== d.id) appliedKey = null;   // new division -> clear "in use" mark
  planDiv = d.id; planLabel = d.label;
  document.getElementById("plan-div-label").textContent = "· " + d.label;
  document.getElementById("btn-recompare").disabled = false;
  document.getElementById("plan-gallery").scrollIntoView({ behavior: "smooth", block: "nearest" });
  await runPlan();
}

async function syncPlannerInputs() {
  // Planner window mirrors the Settings tab (single source of truth).
  try {
    const s = await API.get("/api/settings");
    document.getElementById("plan-start").value = s.day_start || "";
    document.getElementById("plan-end").value = s.day_end || "";
    document.getElementById("plan-courts").value = s.court_count;
  } catch {}
}

async function runPlan() {
  if (!planDiv) return;
  const start = document.getElementById("plan-start").value || "17:00";
  const end = document.getElementById("plan-end").value || null;
  const courts = parseInt(document.getElementById("plan-courts").value, 10) || 4;
  const poolsVal = parseInt(document.getElementById("plan-pools").value, 10);
  const num_groups = isNaN(poolsVal) ? null : poolsVal;   // blank = auto
  try {
    // Persist the window to Settings so both tabs (and the scheduler) agree.
    await API.post("/api/settings", { day_start: start, day_end: end || "", court_count: courts });
    lastPlan = await API.post("/api/plan", { division: planDiv, start, end, courts, num_groups });
    renderPlanGallery(lastPlan);
  } catch (e) { toast(e.message, true); }
}
document.getElementById("btn-recompare").onclick = runPlan;

// Populate the Compare window (Start/End/Courts) from the SAVED settings so a
// refresh keeps your last values instead of a hardcoded default.
async function loadPlanWindow() {
  try {
    const s = await API.get("/api/settings");
    if (s.day_start) document.getElementById("plan-start").value = s.day_start;
    document.getElementById("plan-end").value = s.day_end || "";
    if (s.court_count) document.getElementById("plan-courts").value = s.court_count;
  } catch (e) {}
}

// Team-only scoring panel in the Compare view: finalize the point system here;
// changing it updates the division and re-previews (so the rubbers/standings
// reflect the choice).
let planEvents = [];
function syncScoringPanel(plan) {
  const panel = document.getElementById("plan-scoring");
  if (!plan.team || !plan.team_format) { panel.style.display = "none"; return; }
  panel.style.display = "";
  const tf = plan.team_format;
  planEvents = tf.events || [];
  document.getElementById("ps-tie").value = tf.tie_format || "position";
  document.getElementById("ps-length").value = tf.match_length || "full";
  document.getElementById("ps-handicap").checked = !!tf.handicap;
  document.getElementById("ps-rank").value = tf.rank_by;
  document.getElementById("ps-wp").value = tf.win_points;
  document.getElementById("ps-dp").value = tf.draw_points;
  document.getElementById("ps-lp").value = tf.loss_points;
  document.getElementById("ps-draw").checked = tf.allow_draw;
  document.getElementById("ps-play").value = tf.play_mode;
  document.getElementById("ps-dead").value = tf.dead_rubbers;
  const lp = tf.rank_by === "league_points";
  ["ps-wp-wrap", "ps-dp-wrap", "ps-lp-wrap"].forEach(id =>
    document.getElementById(id).style.display = lp ? "" : "none");
  // Per-event tie-rule overrides (one select per event in play).
  const er = tf.event_rules || {};
  document.getElementById("ps-event-rules").innerHTML =
    '<span class="muted" style="font-size:12px">Per-event:</span>' +
    planEvents.map(ev =>
      `<label class="inline" style="font-size:12px">${ev}
        <select class="ps-er" data-ev="${ev}">
          <option value="">(default)</option>
          <option value="position" ${er[ev] === "position" ? "selected" : ""}>position</option>
          <option value="cross" ${er[ev] === "cross" ? "selected" : ""}>cross</option>
        </select></label>`).join("");
  document.querySelectorAll(".ps-er").forEach(s => s.addEventListener("change", saveScoring));
  document.getElementById("ps-desc").textContent = plan.scoring_note || "";
}
async function saveScoring() {
  if (!planDiv) return;
  const event_rules = {};
  document.querySelectorAll(".ps-er").forEach(s => {
    if (s.value) event_rules[s.dataset.ev] = s.value;
  });
  const template = {
    events: planEvents,
    tie_format: document.getElementById("ps-tie").value,
    match_length: document.getElementById("ps-length").value,
    handicap: document.getElementById("ps-handicap").checked,
    event_rules,
    rank_by: document.getElementById("ps-rank").value,
    win_points: parseInt(document.getElementById("ps-wp").value, 10) || 0,
    draw_points: parseInt(document.getElementById("ps-dp").value, 10) || 0,
    loss_points: parseInt(document.getElementById("ps-lp").value, 10) || 0,
    allow_draw: document.getElementById("ps-draw").checked,
    play_mode: document.getElementById("ps-play").value,
    dead_rubbers: document.getElementById("ps-dead").value,
  };
  try {
    await API.post("/api/division/team-format", { division: planDiv, template });
    await runPlan();                       // re-preview with the new scoring
  } catch (e) { toast(e.message, true); }
}
["ps-tie", "ps-length", "ps-handicap", "ps-rank", "ps-wp", "ps-dp", "ps-lp",
 "ps-draw", "ps-play", "ps-dead"]
  .forEach(id => document.getElementById(id).addEventListener("change", saveScoring));

function renderPlanGallery(plan) {
  document.getElementById("plan-meta").textContent =
    `${plan.entries} entries · ${plan.courts} courts · ${plan.slot_min}-min slots · ` +
    `window ${plan.start}${plan.end ? "–" + plan.end : ""}`;
  syncScoringPanel(plan);
  const g = document.getElementById("plan-gallery");
  g.innerHTML = "";
  // Recommended first, then the rest in server order.
  const ordered = [...plan.options].sort((a, b) => (b.recommended ? 1 : 0) - (a.recommended ? 1 : 0));
  ordered.forEach(o => {
    const card = document.createElement("div");
    card.className = "plan-card";
    const title = o.label || FMT_LABEL[o.format] || o.format;
    if (!o.ok) {
      card.classList.add("unavail");
      card.innerHTML = `<div class="head"><span>${title}</span></div>
        <div class="stats">Not available for this field.<br>
        <span class="muted">${o.reason}</span></div>`;
      g.appendChild(card); return;
    }
    const inUse = appliedKey && planKey(o) === appliedKey;
    if (inUse) card.classList.add("recommended");
    else if (o.recommended) card.classList.add("recommended");
    if (plan.end && !o.fits) card.classList.add("unfit");
    const tags = (inUse ? `<span class="badge ok">✓ In use</span>` : "") +
      (o.recommended ? `<span class="badge info">Recommended</span>` : "") +
      (o.combined ? `<span class="badge info">combined</span>` : "");
    const fit = !plan.end ? "" : (o.fits
      ? `<span class="badge fit-ok">fits</span>`
      : `<span class="badge fit-over">~${o.overtime_min}m over</span>`);
    const dur = `${Math.floor(o.duration_min / 60)}h ${o.duration_min % 60}m`;
    const scoring = o.scoring ? `<div class="scoring-line">${o.scoring}</div>` : "";
    card.innerHTML = `<div class="head"><span>${title}</span>${fit}</div>
      <div class="stats">${tags ? tags + "<br>" : ""}
        <span class="muted">${o.note || ""}</span><br>
        ${o.matches} ${plan.team ? "rubbers" : "matches"} · ${o.rounds} rounds · est. ${dur} → ends ${o.end_time}</div>
      ${scoring}
      <div class="mini"></div>
      <div class="foot"><button class="btn">Use this format</button></div>`;
    renderBracket(card.querySelector(".mini"), o.preview, { editable: false });
    card.querySelector("button").onclick = () => approveFormat(o);
    g.appendChild(card);
  });
}

async function approveFormat(o) {
  const body = { division: planDiv, format: o.format, method: "ranking" };
  if (o.params && o.params.num_groups) {
    body.num_groups = o.params.num_groups; body.main_draw = o.params.main_draw;
  }
  try {
    await API.post("/api/bracket/generate", body);
  } catch (e) {
    if (e.status === 409 && confirm("This bracket is finalized. Replace it?")) {
      body.force = true;
      await API.post("/api/bracket/generate", body);
    } else { toast(e.message, true); return; }
  }
  appliedKey = planKey(o);
  toast(`${planLabel}: ${FMT_LABEL[o.format]} selected`);
  loadDivisions();
  if (lastPlan) renderPlanGallery(lastPlan);   // mark the applied card "✓ In use"
  showBracket(planDiv, planLabel);
}

async function showBracket(divId, label) {
  currentDivision = divId;
  document.getElementById("bracket-title").textContent = "· " + label;
  document.getElementById("print-title").textContent = "BYU Badminton — " + label;
  try {
    const view = await API.get("/api/bracket?division=" + encodeURIComponent(divId));
    const box = document.getElementById("bracket");
    // Read-only preview here; scores are entered only in the Tournament Manager tab.
    renderBracket(box, view, { editable: false });
    if (view.division && view.division.format === "group_knockout") {
      const note = document.createElement("div");
      note.className = "combined-note";
      note.innerHTML = "<b>Combined strategy:</b> round-robin pools feed a power-of-2 knockout. Enter pool results first; the top finishers auto-fill the knockout draw.";
      box.insertBefore(note, box.firstChild);
    }
    box.scrollIntoView({ behavior: "smooth", block: "start" });   // jump to it
  } catch (e) { toast(e.message, true); }
}

document.getElementById("btn-print").onclick = () => window.print();

// --- tournament manager -----------------------------------------------------
let mgDivId = null;

async function loadManagerDivisions() {
  let data;
  try { data = await API.get("/api/divisions"); } catch { return; }
  const sel = document.getElementById("mg-div");
  const withB = data.divisions.filter(d => d.has_bracket);
  const prev = sel.value;
  sel.innerHTML = withB.map(d => `<option value="${d.id}">${d.label}</option>`).join("");
  if (!withB.length) {
    document.getElementById("mg-meta").textContent = "No brackets yet — generate one on the Divisions tab.";
    ["mg-queue", "mg-bracket", "mg-schedule"].forEach(id => document.getElementById(id).innerHTML = "");
    return;
  }
  sel.value = withB.some(d => d.id === prev) ? prev : withB[0].id;
  mgDivId = sel.value;
  loadManager();
}
document.getElementById("mg-div").onchange = (e) => { mgDivId = e.target.value; loadManager(); };
document.getElementById("mg-refresh").onclick = () => loadManager();
document.getElementById("mg-print").onclick = () => window.print();

async function loadManager() {
  if (!mgDivId) return;
  let view;
  try { view = await API.get("/api/bracket?division=" + encodeURIComponent(mgDivId)); }
  catch (e) { toast(e.message, true); return; }
  document.getElementById("mg-meta").textContent =
    view.champion ? `Champion: ${view.champion.label}` : "In progress";
  document.getElementById("mg-print-title").textContent = "BYU Badminton — " + view.division.label;

  // Section 1: Scores (editable bracket, no standings inside — those get their
  // own section below).
  renderBracket(document.getElementById("mg-bracket"), view, {
    editable: true, section: "bracket",
    onResult: async (matchId, games) => {
      try {
        await API.post("/api/result", { division: mgDivId, match: matchId, games });
        toast("Result saved");
        loadManager();      // standings + advancement update immediately
      } catch (e) { toast(e.message, true); }
    },
    onClear: async (matchId) => {
      try {
        await API.post("/api/result/clear", { division: mgDivId, match: matchId });
        toast("Match cleared");
        loadManager();
      } catch (e) { toast(e.message, true); }
    },
  });
  // Section 2: Standings (only when the format has pools).
  const stCard = document.getElementById("mg-standings-card");
  const st = document.getElementById("mg-standings");
  if (view.standings && view.standings.length) {
    st.innerHTML = "";
    st.appendChild(renderStandings(view.standings));
    stCard.style.display = "";
  } else {
    stCard.style.display = "none";
  }
  // Section 3: Current & up next.
  renderQueue(view.queue || { ready: [], upcoming: [] });
  // Section 4: Schedule.
  loadMgSchedule(view.division.label);
}

function renderQueue(q) {
  const col = (title, items, cls) => {
    const list = items.length ? items.map(m => {
      const s1 = (m.side1 && m.side1.label) || "TBD", s2 = (m.side2 && m.side2.label) || "TBD";
      return `<div class="queue-item ${cls}"><span class="rd">${m.round}</span><br>${s1} vs ${s2}</div>`;
    }).join("") : '<p class="muted">None right now.</p>';
    return `<div class="queue-col"><h4>${title}</h4>${list}</div>`;
  };
  document.getElementById("mg-queue").innerHTML =
    `<div class="queue-cols">${col("Ready to play now", q.ready, "ready")}` +
    `${col("Up next (once current matches finish)", q.upcoming, "next")}</div>`;
}

async function loadMgSchedule(label) {
  const box = document.getElementById("mg-schedule");
  let v;
  try { v = await API.get("/api/schedule"); } catch { box.innerHTML = ""; return; }
  const rows = v.blocks.filter(b => b.division === label).map(b => {
    const s1 = (b.side1 && b.side1.label) || "TBD", s2 = (b.side2 && b.side2.label) || "TBD";
    return `<tr><td>${b.start}</td><td>${b.court}</td><td>${b.round}</td><td>${s1} vs ${s2}</td></tr>`;
  }).join("");
  box.innerHTML = rows
    ? `<table><thead><tr><th>Time</th><th>Court</th><th>Round</th><th>Match</th></tr></thead><tbody>${rows}</tbody></table>`
    : '<p class="muted">No schedule generated yet (use the Schedule tab).</p>';
}

// --- court board (live, drag-and-drop) --------------------------------------
document.getElementById("board-refresh").onclick = () => loadBoard();

// Live auto-refresh: while the Court board is visible, poll every few seconds so
// newly-ready matches and freed-up courts appear without hitting Refresh. Skip a
// cycle if a score is being typed on a court, so we never steal focus or wipe a
// half-entered score.
setInterval(() => {
  if (!document.getElementById("tab-manage").classList.contains("active")
      || manageView !== "board") return;
  const grid = document.getElementById("court-grid");
  if (!grid) return;
  const ae = document.activeElement;
  const typing = (ae && grid.contains(ae))
    || [...grid.querySelectorAll(".gin")].some(i => i.value !== "");
  if (!typing) loadBoard();
}, 4000);

let boardData = { courts: [], on_deck: [], queue: [], completed: [] };
let selectedMatchId = null;

async function loadBoard() {
  try { applyBoard(await API.get("/api/board")); }
  catch (e) { toast(e.message, true); }
}
function applyBoard(v) {
  boardData = v;
  const all = [...(v.queue || []), ...(v.on_deck || [])];
  if (!all.some(m => m.id === selectedMatchId)) selectedMatchId = null;
  renderBoard();
}
function selectedMatch() {
  return (boardData.queue || []).find(m => m.id === selectedMatchId)
      || (boardData.on_deck || []).find(m => m.id === selectedMatchId) || null;
}
function renderBoard() {
  renderCourtGrid(boardData.courts || []);
  renderChips("court-queue", boardData.queue || [], false);
  document.getElementById("queue-count").textContent = `(${(boardData.queue || []).length})`;
  renderUpcoming(boardData.upcoming || []);
  renderCompleted(boardData.completed || []);
}

// Read-only placeholder cards for knockout matches not yet playable. They
// autofill as pools finish (each poll) and, once both sides are real, the
// backend moves them into "All ready matches" where they become draggable.
function renderUpcoming(list) {
  const box = document.getElementById("court-upcoming");
  document.getElementById("upcoming-count").textContent = `(${list.length})`;
  box.innerHTML = list.length ? "" : '<p class="muted">No upcoming knockout matches.</p>';
  list.forEach(m => {
    const s1 = (m.side1 && m.side1.label) || "TBD", s2 = (m.side2 && m.side2.label) || "TBD";
    const card = document.createElement("div");
    card.className = "qchip upcoming";
    card.innerHTML = `<div class="q-div">${m.division_label} · ${m.round} · pending</div>${s1} vs ${s2}`;
    box.appendChild(card);
  });
}

function ginCells(m, idx) {
  const maxG = m.max_games || 3;
  let s = "";
  for (let g = 0; g < maxG; g++) {
    const val = m.games && m.games[g] ? m.games[g][idx] : "";
    s += `<input class="gin" type="number" min="0" data-g="${g}" data-side="${idx}" value="${val}">`;
  }
  return s;
}

// Read the score boxes on a court tile and decide the match locally (no save).
function readCourtScore(body, maxG) {
  const needed = Math.floor(maxG / 2) + 1;
  const games = [];
  let complete = true;
  for (let g = 0; g < maxG; g++) {
    const a = body.querySelector(`.gin[data-g="${g}"][data-side="0"]`).value;
    const b = body.querySelector(`.gin[data-g="${g}"][data-side="1"]`).value;
    if (a === "" && b === "") continue;
    if (a === "" || b === "") { complete = false; continue; }  // half-entered game
    games.push([parseInt(a, 10), parseInt(b, 10)]);
  }
  let w0 = 0, w1 = 0;
  games.forEach(([a, b]) => { if (a > b) w0++; else if (b > a) w1++; });
  const decided = complete && games.length > 0 && Math.max(w0, w1) >= needed && w0 !== w1;
  return { games, decided, winnerIdx: w0 > w1 ? 0 : 1 };
}

// Live preview on a court tile: highlight each game's winning box blue and, once
// the match is decided, show the winner line + reveal the Approve button.
function refreshCourtPreview(body, m, winline, approve) {
  const maxG = m.max_games || 3;
  for (let g = 0; g < maxG; g++) {
    const a = body.querySelector(`.gin[data-g="${g}"][data-side="0"]`);
    const b = body.querySelector(`.gin[data-g="${g}"][data-side="1"]`);
    const av = a.value === "" ? null : parseInt(a.value, 10);
    const bv = b.value === "" ? null : parseInt(b.value, 10);
    a.classList.toggle("gwin", av !== null && bv !== null && av > bv);
    b.classList.toggle("gwin", av !== null && bv !== null && bv > av);
  }
  const r = readCourtScore(body, maxG);
  if (r.decided) {
    winline.textContent = "Winner: " + (r.winnerIdx === 0 ? m.side1.label : m.side2.label);
    winline.style.display = ""; approve.style.display = "";
  } else {
    winline.style.display = "none"; approve.style.display = "none";
  }
}

const expandedCourts = new Set();   // court nums whose On-deck panel is open

function renderCourtGrid(courts) {
  const grid = document.getElementById("court-grid");
  grid.innerHTML = "";
  const sel = selectedMatch();
  courts.forEach(c => {
    const el = document.createElement("div");
    el.className = "court-tile" + (c.center ? " center" : "");
    // Center courts only gate knockout matches when the server enforces them
    // (it doesn't when fewer than two center courts exist).
    const centerEnforced = (boardData.center_courts || []).length > 0;
    const canPlace = sel && !c.match
      && (!sel.knockout || !centerEnforced || c.center);
    if (canPlace) {
      el.classList.add("valid-target");
      el.addEventListener("click", () => boardAssign(c.num, sel.id));
    }
    // Header
    const hd = document.createElement("div");
    hd.className = "court-hd";
    hd.innerHTML = `<span>Court ${c.num}</span>` +
      (c.center ? '<span class="badge info">center</span>' : '<span class="pill">outer</span>');
    el.appendChild(hd);
    // Body: occupied match (with score boxes) or an open drop zone
    const body = document.createElement("div");
    body.className = "court-body";
    if (!c.match) {
      body.innerHTML = `<div class="court-open">${canPlace
        ? "tap to place the selected match" : "open — drop a match, or use On deck"}</div>`;
    } else {
      const m = c.match;
      body.innerHTML =
        `<div class="cm-div">${m.division_label} · ${m.round}</div>` +
        `<div class="cm-side"><span class="nm">${m.side1.label}</span><span class="games">${ginCells(m, 0)}</span></div>` +
        `<div class="cm-side"><span class="nm">${m.side2.label}</span><span class="games">${ginCells(m, 1)}</span></div>`;
      const x = document.createElement("button");
      x.className = "cm-clear"; x.textContent = "×"; x.title = "Send back to the queue";
      x.addEventListener("click", e => { e.stopPropagation(); boardClear(c.num); });
      body.appendChild(x);
      // Winner line + Approve button: typing does NOT auto-submit. The final
      // score previews live (winner boxes turn blue) and the organizer clicks
      // Approve to commit the result and free the court.
      const winline = document.createElement("div");
      winline.className = "cm-winline"; winline.style.display = "none";
      body.appendChild(winline);
      const approve = document.createElement("button");
      approve.className = "btn primary cm-approve"; approve.textContent = "Approve result";
      approve.style.display = "none";
      approve.addEventListener("click", e => {
        e.stopPropagation();
        const r = readCourtScore(body, m.max_games || 3);
        if (r.decided) boardResult(c.num, r.games);
      });
      body.appendChild(approve);
      const preview = () => refreshCourtPreview(body, m, winline, approve);
      body.addEventListener("input", preview);
      preview();   // reflect any already-typed values after a re-render
    }
    el.appendChild(body);
    // On-deck tab (always present) + collapsible panel
    const open = expandedCourts.has(c.num);
    const opts = c.options || [];
    const tab = document.createElement("div");
    tab.className = "ondeck-tab";
    tab.innerHTML = `<span>On deck (${opts.length})</span><span>${open ? "▾" : "▸"}</span>`;
    tab.addEventListener("click", e => {
      e.stopPropagation();
      open ? expandedCourts.delete(c.num) : expandedCourts.add(c.num);
      renderCourtGrid(boardData.courts);
    });
    el.appendChild(tab);
    const panel = document.createElement("div");
    panel.className = "ondeck-panel" + (open ? " open" : "");
    if (!opts.length) {
      panel.innerHTML = '<p class="muted" style="margin:4px 0">No matches left for this court.</p>';
    } else {
      opts.forEach(m => {
        const it = document.createElement("div");
        it.className = "od-item" + (m.ready ? "" : " waiting");
        it.draggable = true;
        it.innerHTML = `<span class="od-r">${m.division_label} · ${m.round}` +
          `${m.ready ? "" : " · waiting"}</span><br>${m.side1.label} vs ${m.side2.label}`;
        it.addEventListener("dragstart", e => {
          e.dataTransfer.setData("mid", m.id); e.dataTransfer.effectAllowed = "move";
        });
        it.addEventListener("click", e => { e.stopPropagation(); boardAssign(c.num, m.id); });
        panel.appendChild(it);
      });
    }
    el.appendChild(panel);
    // Whole tile is a drop target
    el.addEventListener("dragover", e => { e.preventDefault(); el.classList.add("dragover"); });
    el.addEventListener("dragleave", () => el.classList.remove("dragover"));
    el.addEventListener("drop", e => {
      e.preventDefault(); el.classList.remove("dragover");
      const mid = e.dataTransfer.getData("mid");
      if (mid) boardAssign(c.num, mid);
    });
    grid.appendChild(el);
  });
}

function chipEl(m, onDeck) {
  const chip = document.createElement("div");
  chip.className = "qchip" + (m.knockout ? " knockout" : "")
    + (onDeck ? " ondeck" : "") + (m.id === selectedMatchId ? " selected" : "");
  chip.draggable = true;
  chip.innerHTML = `<div class="q-div">${m.division_label} · ${m.round}` +
    `${m.knockout ? " · knockout" : ""}` +
    `${onDeck ? ' <span class="ondeck-tag">(on deck)</span>' : ""}</div>` +
    `${m.side1.label} vs ${m.side2.label}`;
  chip.addEventListener("dragstart", e => {
    e.dataTransfer.setData("mid", m.id); e.dataTransfer.effectAllowed = "move";
  });
  chip.addEventListener("click", () => {
    selectedMatchId = (selectedMatchId === m.id) ? null : m.id;
    renderBoard();                        // refresh highlights + selection
  });
  return chip;
}

function renderChips(containerId, list, onDeck) {
  const box = document.getElementById(containerId);
  box.innerHTML = "";
  if (!list.length) {
    box.innerHTML = `<p class="muted">${onDeck ? "Nothing on deck." : "No other ready matches."}</p>`;
    return;
  }
  list.forEach(m => box.appendChild(chipEl(m, onDeck)));
}

function renderCompleted(list) {
  const box = document.getElementById("court-completed");
  document.getElementById("done-count").textContent = `(${list.length})`;
  box.innerHTML = list.length ? "" : '<p class="muted">No completed matches yet.</p>';
  list.forEach(m => {
    const loser = m.winner_label === (m.side1 && m.side1.label) ? (m.side2 && m.side2.label)
                                                                : (m.side1 && m.side1.label);
    const row = document.createElement("div");
    row.className = "done-row";
    row.innerHTML = `<span class="dr-div">${m.division_label} · ${m.round}</span>` +
      `<b>${m.winner_label}</b> def. ${loser || ""} <span class="muted">${m.score}</span>`;
    box.appendChild(row);
  });
}

async function boardAssign(court, mid) {
  try { applyBoard(await API.post("/api/board/assign", { court, match: mid })); toast("Placed on court " + court); }
  catch (e) { toast(e.message, true); }
}
async function boardClear(court) {
  try { applyBoard(await API.post("/api/board/clear", { court })); }
  catch (e) { toast(e.message, true); }
}
async function boardResult(court, games) {
  try { applyBoard(await API.post("/api/board/result", { court, games })); toast("Result saved; court freed"); }
  catch (e) { toast(e.message, true); }
}

// --- clear (downstream-only) ------------------------------------------------
async function clearStage(stage, msg) {
  if (!confirm(msg)) return;
  try {
    await API.post("/api/clear", { stage });
    toast("Cleared");
    refreshAll(); loadDivisions(); loadManagerDivisions(); loadSchedule();
  } catch (e) { toast(e.message, true); }
}
document.getElementById("btn-clear-import").onclick = () =>
  clearStage("import", "Clear ALL data — players, divisions, brackets, scores, and schedule? This cannot be undone.");
document.getElementById("btn-clear-divisions").onclick = () =>
  clearStage("divisions", "Clear divisions & brackets (and their scores/schedule)? Imported players are kept.");
document.getElementById("btn-clear-schedule").onclick = () =>
  clearStage("schedule", "Clear the generated schedule? Brackets and scores are kept.");
document.getElementById("mg-clear-scores").onclick = () =>
  clearStage("scores", "Clear ALL scores? Brackets stay intact, but every result is wiped and finalized brackets are reopened.");

// --- schedule ---------------------------------------------------------------
async function loadBestDates() {
  try {
    const r = await API.get("/api/best-dates");
    const fmt = (arr) => arr.slice(0, 5).map(o =>
      `${o.option} — ${o.available}/${o.total} (${o.pct}%)`).join("<br>") || "—";
    document.getElementById("best-dates").innerHTML =
      `<b>Weekends:</b><br>${fmt(r.weekends)}<br><br><b>Weekdays:</b><br>${fmt(r.weekdays)}`;
  } catch (e) {}
}

document.getElementById("btn-schedule").onclick = async () => {
  try { await API.post("/api/schedule/generate", {}); toast("Schedule generated"); loadSchedule(); }
  catch (e) { toast(e.message, true); }
};

async function loadSchedule() {
  let v;
  try { v = await API.get("/api/schedule"); } catch { return; }
  document.getElementById("sched-meta").textContent =
    `${v.blocks.length} matches · ${v.slot_min}-min slots · ${v.day_start}` +
    (v.ends ? ` → ${v.ends} (est. ${Math.floor(v.duration_min / 60)}h ${v.duration_min % 60}m)` : "");
  document.getElementById("sched-stale").innerHTML = v.stale
    ? '<div class="guide locked"><div><b>Settings changed since this schedule was generated.</b> Click <b>Generate schedule</b> again to apply the new courts/timing.</div></div>'
    : "";
  const conf = document.getElementById("sched-conflicts");
  conf.innerHTML = v.conflicts.length
    ? `<div class="issue error"><span class="badge err">conflict</span> ${v.conflicts.join("<br>")}</div>`
    : "";
  const tb = document.querySelector("#sched-table tbody");
  tb.innerHTML = "";
  v.blocks.forEach(b => {
    const tr = document.createElement("tr");
    const s1 = (b.side1 && b.side1.label) || "TBD", s2 = (b.side2 && b.side2.label) || "TBD";
    tr.innerHTML = `<td>${b.start}</td><td>${b.court}</td><td>${b.division}</td>
      <td>${b.round}</td><td>${s1} vs ${s2}</td>`;
    tb.appendChild(tr);
  });
  updateStepper();
}

// --- custom bracket ---------------------------------------------------------
document.getElementById("btn-custom").onclick = async () => {
  const label = document.getElementById("cb-label").value.trim();
  const entries = document.getElementById("cb-entries").value.split("\n").filter(x => x.trim());
  const note = document.getElementById("cb-note");
  if (!label) { toast("Give the bracket a name", true); return; }
  if (entries.length < 2) { toast("Enter at least 2 entrants", true); return; }
  try {
    const r = await API.post("/api/division/custom", {
      label, kind: document.getElementById("cb-kind").value,
      event: document.getElementById("cb-event").value,
      format: document.getElementById("cb-format").value, entries,
    });
    // Lines that could not be read as a pair are reported, not dropped silently.
    const skipped = r.skipped || [];
    note.textContent = skipped.length
      ? `Skipped ${skipped.length} line(s) that are not a pair (use "Name / Name"): ` +
        skipped.slice(0, 5).join("; ") +
        (skipped.length > 5 ? ` (+${skipped.length - 5} more)` : "")
      : "";
    toast(`Created "${r.label}" (${r.entries} entrants)`);
    document.getElementById("cb-label").value = "";
    document.getElementById("cb-entries").value = "";
    loadDivisions();
  } catch (e) { toast(e.message, true); }
};

// --- settings ---------------------------------------------------------------
const SET_FIELDS = {
  "set-courts": "court_count", "set-daystart": "day_start",
  "set-dayend": "day_end", "set-rest": "rest_min",
  "set-warmup": "warmup_min", "set-play": "play_min", "set-buffer": "buffer_min",
  "set-bestof": "best_of", "set-points": "points_to", "set-cap": "hard_cap",
  "set-pwarmup": "pool_warmup_min", "set-pplay": "pool_play_min",
  "set-pbuffer": "pool_buffer_min",
};
function showSlotMeta(s) {
  document.getElementById("set-slot").textContent = `= ${s.slot_min}-min knockout slots`;
  document.getElementById("set-pslot").textContent = `= ${s.pool_slot_min}-min pool slots`;
}
async function loadSettings() {
  try {
    const s = await API.get("/api/settings");
    for (const [id, key] of Object.entries(SET_FIELDS)) document.getElementById(id).value = s[key];
    showSlotMeta(s);
  } catch (e) {}
}
document.getElementById("btn-save-settings").onclick = async () => {
  const patch = {};
  for (const [id, key] of Object.entries(SET_FIELDS)) {
    const el = document.getElementById(id);
    patch[key] = el.type === "time" ? el.value : parseInt(el.value, 10);
  }
  try {
    const s = await API.post("/api/settings", patch);
    showSlotMeta(s);
    toast("Settings saved");
  } catch (e) { toast(e.message, true); }
};

// --- team mode (entry-based) ------------------------------------------------
let tournamentMode = "individual";

function applyMode(mode) {
  tournamentMode = mode;
  document.querySelectorAll("#mode-toggle button").forEach(b =>
    b.classList.toggle("active", b.dataset.mode === mode));
  const team = mode === "team";
  document.getElementById("team-panel").style.display = team ? "" : "none";
  document.getElementById("indiv-build").style.display = team ? "none" : "";
}
document.querySelectorAll("#mode-toggle button").forEach(b => {
  b.onclick = async () => {
    try { const r = await API.post("/api/mode", { mode: b.dataset.mode });
      applyMode(r.mode); loadDivisions(); }
    catch (e) { toast(e.message, true); }
  };
});

// scope toggle: single event dropdown vs multi-event checkboxes
document.getElementById("tf-scope").onchange = (e) => {
  const single = e.target.value === "single";
  document.getElementById("tf-single-wrap").style.display = single ? "" : "none";
  document.getElementById("tf-multi-wrap").style.display = single ? "none" : "";
};

function teamEvents() {
  if (document.getElementById("tf-scope").value === "single")
    return [document.getElementById("tf-event").value];
  return [...document.querySelectorAll(".tf-ev:checked")].map(c => c.value);
}
function teamTemplate() {
  return {
    events: teamEvents(),
    play_mode: document.getElementById("tf-play").value,
    dead_rubbers: document.getElementById("tf-dead").value,
    rank_by: document.getElementById("tf-rank").value,
    allow_draw: document.getElementById("tf-draw").checked,
  };
}
function teamOpts() {
  const numteams = parseInt(document.getElementById("tb-numteams").value, 10);
  const persize = parseInt(document.getElementById("tb-persize").value, 10);
  const opts = {
    method: document.getElementById("tb-method").value,
    team_type: document.getElementById("tb-type").value,
    rng_seed: parseInt(document.getElementById("tb-seed").value, 10) || 0,
    template: teamTemplate(),
    label: document.getElementById("tb-label").value.trim() || "Team Event",
    format: document.getElementById("tb-format").value,
  };
  if (!isNaN(persize)) opts.players_per_team = persize;
  else if (!isNaN(numteams)) opts.num_teams = numteams;
  return opts;
}
function renderTeamPreview(r) {
  const events = r.events || [];
  const grid = (r.report && r.report.grid) || [];
  // per-team x per-event grid
  const gridBox = document.getElementById("tb-grid");
  if (grid.length) {
    const head = events.map(ev => `<th>${ev}</th>`).join("");
    const rows = grid.map(g => `<tr><td>${g.team_name}</td>` +
      events.map(ev => {
        const v = g.by_event[ev] || 0;
        const max = Math.max(...grid.map(x => x.by_event[ev] || 0));
        return `<td class="${v < max ? "short" : ""}">${v}</td>`;
      }).join("") + `<td>${g.size}</td></tr>`).join("");
    gridBox.innerHTML = `<table class="grid-table"><thead><tr><th>Team</th>${head}<th>Total</th></tr></thead><tbody>${rows}</tbody></table>`;
  } else gridBox.innerHTML = "";
  // warnings (gaps)
  document.getElementById("tb-warnings").innerHTML =
    ((r.report && r.report.warnings) || []).map(m => `<div class="warn">${m}</div>`).join("");
  // rosters grouped by event
  const box = document.getElementById("tb-preview-out");
  box.innerHTML = "";
  r.teams.forEach(tm => {
    const groups = tm.by_event.map(g =>
      `<div class="ev-group"><div class="ev-h">${g.event}</div>` +
      g.entries.map(e => `<div class="ev-e"><span>${e.label}</span>` +
        `<span class="g">${e.gender}${e.skill != null ? " · " + e.skill : ""}</span></div>`).join("") +
      `</div>`).join("");
    const el = document.createElement("div");
    el.className = "team-card";
    const clr = tm.color ? `style="background:${tm.color}"` : "";
    el.innerHTML = `<h4 ${clr}><span>${tm.name}</span><span>${tm.size}</span></h4><div class="tc-body">${groups}</div>`;
    box.appendChild(el);
  });
}
document.getElementById("tb-preview").onclick = async () => {
  try { renderTeamPreview(await API.post("/api/teams/preview", teamOpts())); }
  catch (e) { toast(e.message, true); }
};
document.getElementById("tb-commit").onclick = async () => {
  try {
    const r = await API.post("/api/teams/commit", teamOpts());
    toast(`Created ${r.label} with ${r.teams} teams`);
    loadDivisions();
  } catch (e) { toast(e.message, true); }
};

// --- boot -------------------------------------------------------------------
function refreshAll() {
  loadValidation(); loadPlayers(); loadPartnerships(); updateStepper();
}
API.get("/api/mode").then(r => applyMode(r.mode)).catch(() => {});
loadPlanWindow();
ping(); refreshAll();
setInterval(ping, 8000);
