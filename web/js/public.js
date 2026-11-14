// Public read-only display. Master "Overview" page shows standings + bracket
// for a division, plus tabs to focus on Bracket, Standings, or the full Schedule.
let view = "overview";
let selected = null;
let snapshot = { divisions: [] };
let schedule = { blocks: [] };
// A published snapshot (GitHub Pages) has no API behind it: the export writes
// static-data.json next to this page and flips the data-source marker, so the
// page reads that file instead of calling the API, and does not poll.
const DATA_SOURCE = (document.querySelector('meta[name="data-source"]') || {}).content;
let snapshotOnly = DATA_SOURCE === "static";
let staticData = null;

document.querySelectorAll("#viewtabs button").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll("#viewtabs button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    view = b.dataset.view;
    render();
  };
});

async function loadStatic() {
  let data;
  try {
    data = await (await fetch("static-data.json", { cache: "no-cache" })).json();
  } catch {
    if (!staticData) document.getElementById("refresh").textContent = "snapshot unavailable";
    return false;
  }
  // Republishing rewrites the file: only redraw when the snapshot changed.
  if (staticData && data.generated === staticData.generated) return true;
  staticData = data;
  snapshot = staticData.public || { divisions: [] };
  schedule = staticData.schedule || { blocks: [] };
  document.getElementById("tname").textContent = snapshot.name || "Tournament";
  document.getElementById("refresh").textContent =
    "read-only snapshot" + (staticData.generated ? " · " + staticData.generated : "");
  render();
  return true;
}

async function poll() {
  if (snapshotOnly) {          // a published page: look for a newer snapshot
    await loadStatic();
    return;
  }
  try {
    snapshot = await API.get("/api/public");
    schedule = await API.get("/api/schedule");
    document.getElementById("tname").textContent = snapshot.name || "Tournament";
    document.getElementById("refresh").textContent = "live · updating";
    render();
  } catch {
    if (!(await loadStatic())) {
      document.getElementById("refresh").textContent = "reconnecting…";
    }
  }
}

// Title printed at the top of the sheet (the on-screen header is hidden in print).
function setPrintTitle(div) {
  document.getElementById("pub-print-title").textContent =
    (snapshot.name || "Tournament") + (div ? " — " + div.division.label : "");
}

function divTabs(divs) {
  const tabs = document.getElementById("divtabs");
  tabs.innerHTML = "";
  if (view === "schedule") {                        // schedule spans all divisions
    setPrintTitle(null);
    return;
  }
  if (!selected || !divs.find(d => d.division.id === selected)) {
    selected = divs.length ? divs[0].division.id : null;
  }
  setPrintTitle(divs.find(d => d.division.id === selected));
  divs.forEach(d => {
    const b = document.createElement("button");
    b.textContent = d.division.label + (d.champion ? " — Champion" : "");
    b.className = d.division.id === selected ? "active" : "";
    b.onclick = () => { selected = d.division.id; render(); };
    tabs.appendChild(b);
  });
}

function scheduleCard() {
  const card = document.createElement("div");
  card.className = "pub-card";
  const rows = schedule.blocks.map(b => {
    const s1 = (b.side1 && b.side1.label) || "TBD";
    const s2 = (b.side2 && b.side2.label) || "TBD";
    return `<tr><td>${b.start}</td><td>${b.court}</td><td>${b.division}</td>
      <td>${b.round}</td><td>${s1} vs ${s2}</td></tr>`;
  }).join("");
  const meta = schedule.ends
    ? `Ends ~${schedule.ends} · ${schedule.match_count} matches`
    : "No schedule generated yet.";
  card.innerHTML = `<h2>Match schedule <span class="muted">${meta}</span></h2>
    <table class="sched-table"><thead><tr><th>Time</th><th>Court</th>
    <th>Division</th><th>Round</th><th>Match</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
  return card;
}

function render() {
  const divs = snapshot.divisions || [];
  divTabs(divs);
  const content = document.getElementById("content");
  content.innerHTML = "";

  if (view === "schedule") {
    content.appendChild(scheduleCard());
    return;
  }
  if (!divs.length) {
    content.innerHTML = '<div class="pub-card"><p class="muted">Brackets will appear here once the organizer generates them.</p></div>';
    return;
  }
  const dview = divs.find(d => d.division.id === selected);
  const card = document.createElement("div");
  card.className = "pub-card";
  const section = view === "overview" ? "all" : view;   // "bracket" | "standings"
  card.innerHTML = `<h2>${dview.division.label}</h2>`;
  const body = document.createElement("div");
  renderBracket(body, dview, { editable: false, section });
  card.appendChild(body);
  content.appendChild(card);

  // Overview also shows this event's slice of the schedule underneath.
  if (view === "overview" && schedule.blocks.some(b => b.division === dview.division.label)) {
    const sc = scheduleCard();
    content.appendChild(sc);
  }
}

poll();
// Live server: every 5s. Published snapshot: check for a redeploy every minute.
setInterval(poll, snapshotOnly ? 60000 : 5000);
