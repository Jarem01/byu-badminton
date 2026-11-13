// Public read-only display. Master "Overview" page shows standings + bracket
// for a division, plus tabs to focus on Bracket, Standings, or the full Schedule.
let view = "overview";
let selected = null;
let snapshot = { divisions: [] };
let schedule = { blocks: [] };

document.querySelectorAll("#viewtabs button").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll("#viewtabs button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    view = b.dataset.view;
    render();
  };
});

async function poll() {
  try {
    snapshot = await API.get("/api/public");
    schedule = await API.get("/api/schedule");
    document.getElementById("tname").textContent = snapshot.name || "Tournament";
    document.getElementById("refresh").textContent = "live · updating";
    render();
  } catch {
    document.getElementById("refresh").textContent = "reconnecting…";
  }
}

function divTabs(divs) {
  const tabs = document.getElementById("divtabs");
  tabs.innerHTML = "";
  if (view === "schedule") {                        // schedule spans all divisions
    document.getElementById("pub-print-title").textContent = snapshot.name || "Tournament";
    return;
  }
  if (!selected || !divs.find(d => d.division.id === selected)) {
    selected = divs.length ? divs[0].division.id : null;
  }
  const current = divs.find(d => d.division.id === selected);   // print header
  document.getElementById("pub-print-title").textContent =
    (snapshot.name || "Tournament") + (current ? " — " + current.division.label : "");
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
setInterval(poll, 5000);
