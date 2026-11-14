// Shared bracket renderer for the admin tool and public display.
// Knockout rounds are laid out on real tree coordinates (each match centered
// between its two feeders) with SVG elbow connectors, so everything lines up.
// Non-tree parts (round-robin pools, losers bracket) render as labelled columns.

const SVGNS = "http://www.w3.org/2000/svg";
const BOX_W = 210, BOX_H = 54, COL_GAP = 64, V_GAP = 16, TOP_PAD = 26;

function gameBoxes(match, side) {
  // BWF-style: one score box per game (up to max_games). Winner of each game
  // is highlighted. Round-robin/pool matches show a single box.
  const maxG = match.max_games || 3;
  const idx = match.side1 && match.side1.key === side.key ? 0 : 1;
  let html = "";
  for (let g = 0; g < maxG; g++) {
    const played = match.games && match.games[g];
    const val = played ? match.games[g][idx] : "";
    const wonGame = played && match.games[g][idx] > match.games[g][1 - idx];
    html += `<span class="gbox${wonGame ? " gwin" : ""}">${val}</span>`;
  }
  return `<span class="games">${html}</span>`;
}

function gameInputs(match, idx) {
  // Editable score boxes: type directly; auto-saves when the match is decided.
  // Once the match is done, the winner's game boxes are highlighted (blue).
  const maxG = match.max_games || 3;
  let html = "";
  for (let g = 0; g < maxG; g++) {
    const played = match.games && match.games[g];
    const v = played ? match.games[g][idx] : "";
    const wonGame = match.winner && played && match.games[g][idx] > match.games[g][1 - idx];
    html += `<input class="gin${wonGame ? " gwin" : ""}" type="number" min="0" ` +
            `inputmode="numeric" data-g="${g}" data-side="${idx}" value="${v}">`;
  }
  return `<span class="games">${html}</span>`;
}

// Real, decided sides only. A "slot" side is a group qualifier/wildcard
// placeholder ("Winner Pool A"), so a match between placeholders must not be
// scorable -- otherwise a fake result (and a fake champion) gets recorded.
const PLAYABLE_SIDE_KINDS = ["player", "pair", "team"];

function scoreable(match) {
  return !!(match.side1 && match.side2 && !match.is_bye
    && PLAYABLE_SIDE_KINDS.includes(match.side1.kind)
    && PLAYABLE_SIDE_KINDS.includes(match.side2.kind));
}

function sideEl(match, side, idx, editing) {
  const div = document.createElement("div");
  div.className = "side";
  if (side == null) {
    div.classList.add(match.is_bye ? "bye" : "tbd");
    div.innerHTML = `<span class="nm">${match.is_bye ? "Bye" : "TBD"}</span>`;
    return div;
  }
  if (match.winner && match.winner === side.key) div.classList.add("win");
  const seed = side.seed ? `<span class="seed">[${side.seed}]</span>` : "";
  div.innerHTML = `<span class="nm" title="${side.label}">${side.label}</span>` +
                  seed + (editing ? gameInputs(match, idx) : gameBoxes(match, side));
  return div;
}

function matchEl(match, opts) {
  const el = document.createElement("div");
  el.className = "match";
  if (match.winner) el.classList.add("done");
  else if (match.ready) el.classList.add("ready");
  const editing = !!(opts.editable && scoreable(match));
  el.appendChild(sideEl(match, match.side1, 0, editing));
  el.appendChild(sideEl(match, match.side2, 1, editing));
  if (editing) {
    el.classList.add("scoring");
    el.addEventListener("change", () => maybeSaveInline(match, el, opts.onResult));
    if (match.winner && opts.onClear) {
      const x = document.createElement("button");
      x.className = "clear-x";
      x.title = "Clear this match's score";
      x.textContent = "×";
      x.addEventListener("click", (e) => { e.stopPropagation(); opts.onClear(match.id); });
      el.appendChild(x);
    }
  }
  return el;
}

function maybeSaveInline(match, el, onResult) {
  const maxG = match.max_games || 3;
  const needed = Math.floor(maxG / 2) + 1;   // games needed to win the match
  const games = [];
  for (let g = 0; g < maxG; g++) {
    const a = el.querySelector(`.gin[data-g="${g}"][data-side="0"]`).value;
    const b = el.querySelector(`.gin[data-g="${g}"][data-side="1"]`).value;
    if (a === "" && b === "") continue;
    if (a === "" || b === "") return;          // half-entered game: wait
    games.push([parseInt(a, 10), parseInt(b, 10)]);
  }
  if (!games.length) return;
  let w0 = 0, w1 = 0;
  games.forEach(([a, b]) => { if (a > b) w0++; else if (b > a) w1++; });
  if (Math.max(w0, w1) < needed || w0 === w1) return;   // not decided yet
  onResult(match.id, games);
}

// --- layout helpers ---------------------------------------------------------
function groupRoundsByPart(rounds) {
  const segs = [];
  rounds.forEach(r => {
    const part = r.part || "main";
    if (segs.length && segs[segs.length - 1].part === part) segs[segs.length - 1].rounds.push(r);
    else segs.push({ part, rounds: [r] });
  });
  return segs;
}

function isBinaryTree(rounds) {
  for (let i = 1; i < rounds.length; i++) {
    if (rounds[i].matches.length * 2 !== rounds[i - 1].matches.length) return false;
  }
  return true;
}

function connector(svg, d) {
  const p = document.createElementNS(SVGNS, "path");
  p.setAttribute("d", d);
  p.setAttribute("fill", "none");
  p.setAttribute("stroke", "#c3d0e0");
  p.setAttribute("stroke-width", "2");
  svg.appendChild(p);
}

function renderTree(rounds, opts) {
  const unit = BOX_H + V_GAP;
  const n0 = rounds[0].matches.length;
  const totalH = TOP_PAD + n0 * unit;
  const totalW = rounds.length * (BOX_W + COL_GAP);
  const wrap = document.createElement("div");
  wrap.className = "bracket-tree";
  wrap.style.height = totalH + "px";
  wrap.style.width = totalW + "px";

  const svg = document.createElementNS(SVGNS, "svg");
  svg.setAttribute("width", totalW);
  svg.setAttribute("height", totalH);
  wrap.appendChild(svg);

  const centers = [];
  rounds.forEach((rnd, r) => {
    const cys = [];
    const x = r * (BOX_W + COL_GAP);
    const title = document.createElement("div");
    title.className = "round-title";
    title.textContent = rnd.name;
    title.style.cssText = `position:absolute;left:${x}px;top:0;width:${BOX_W}px`;
    wrap.appendChild(title);

    rnd.matches.forEach((m, i) => {
      const cy = r === 0
        ? TOP_PAD + i * unit + BOX_H / 2
        : (centers[r - 1][2 * i] + centers[r - 1][2 * i + 1]) / 2;
      cys.push(cy);
      const el = matchEl(m, opts);
      el.style.cssText = `position:absolute;left:${x}px;top:${cy - BOX_H / 2}px;width:${BOX_W}px`;
      wrap.appendChild(el);
      if (r > 0) {
        const parentLeft = x;
        [2 * i, 2 * i + 1].forEach(ci => {
          const childCy = centers[r - 1][ci];
          const childRight = (r - 1) * (BOX_W + COL_GAP) + BOX_W;
          const midX = (childRight + parentLeft) / 2;
          connector(svg, `M${childRight},${childCy} H${midX} V${cy} H${parentLeft}`);
        });
      }
    });
    centers.push(cys);
  });

  const scroll = document.createElement("div");
  scroll.className = "bracket-wrap";
  scroll.appendChild(wrap);
  return scroll;
}

function renderColumns(rounds, opts) {
  const scroll = document.createElement("div");
  scroll.className = "bracket-wrap";
  const b = document.createElement("div");
  b.className = "bracket";
  rounds.forEach(rnd => {
    const col = document.createElement("div");
    col.className = "round";
    const t = document.createElement("div");
    t.className = "round-title";
    t.textContent = rnd.name;
    col.appendChild(t);
    rnd.matches.forEach(m => col.appendChild(matchEl(m, opts)));
    b.appendChild(col);
  });
  scroll.appendChild(b);
  return scroll;
}

// Pool stage of a multi-pool draw: one column per POOL (its rounds stacked in
// order), not one column per round. Pools play side by side, so laying them out
// as a single strip of rounds made them look like a queue.
function renderPoolColumns(rounds, opts) {
  const pools = [];
  rounds.forEach(rnd => {
    const label = rnd.name.includes("·")
      ? rnd.name.split("·")[0].trim() : rnd.name;
    let g = pools.find(p => p.label === label);
    if (!g) pools.push(g = { label, rounds: [] });
    g.rounds.push(rnd);
  });
  const scroll = document.createElement("div");
  scroll.className = "bracket-wrap";
  const b = document.createElement("div");
  b.className = "bracket";
  pools.forEach(p => {
    const col = document.createElement("div");
    col.className = "round pool-col";
    const t = document.createElement("div");
    t.className = "round-title";
    t.textContent = p.label;
    col.appendChild(t);
    p.rounds.forEach(rnd => {
      const cap = document.createElement("div");
      cap.className = "round-cap";
      cap.textContent = rnd.name.replace(p.label, "").replace(/^[·\s]+/, "") || rnd.name;
      col.appendChild(cap);
      rnd.matches.forEach(m => col.appendChild(matchEl(m, opts)));
    });
    b.appendChild(col);
  });
  scroll.appendChild(b);
  return scroll;
}

function poolLabels(rounds) {
  return [...new Set(rounds.map(r => r.name.includes("·")
    ? r.name.split("·")[0].trim() : r.name))];
}

const SEG_HEADING = {
  winners: "Winners Bracket", losers: "Losers Bracket",
  grand_final: "Grand Final", pool: "Pool Matches",
};

function renderBracket(container, view, opts = {}) {
  const section = opts.section || "all";  // "all" | "bracket" | "standings"
  container.innerHTML = "";
  if (!view.exists || !view.rounds.length) {
    container.innerHTML = `<p class="muted">No bracket generated yet for ${view.division.label}.</p>`;
    return;
  }
  if (view.champion && section !== "standings") {
    const c = document.createElement("div");
    c.className = "champion-line";
    c.innerHTML = `Champion: <b>${view.champion.label}</b>`;
    container.appendChild(c);
  }
  if (view.standings && view.standings.length && section !== "bracket") {
    container.appendChild(renderStandings(view.standings));
  }
  // Team draw: render tie cards (team vs team, expandable to rubbers) instead of
  // the individual SVG tree. Standings + per-player drill-down alongside.
  const isTeam = view.rounds.some(r => r.matches.some(m => m.is_tie));
  if (isTeam) {
    if (view.team_rosters && view.team_rosters.length && section !== "bracket") {
      container.appendChild(renderTeamRosters(view.team_rosters));
    }
    if (section !== "standings") renderTeamDraw(container, view, opts);
    return;
  }
  if (section === "standings") return;
  groupRoundsByPart(view.rounds).forEach(seg => {
    if (SEG_HEADING[seg.part] && !(seg.part === "main")) {
      const h = document.createElement("div");
      h.className = "seg-heading";
      h.textContent = SEG_HEADING[seg.part];
      container.appendChild(h);
    }
    const pools = seg.part === "pool" ? poolLabels(seg.rounds) : [];
    if (pools.length > 1) {
      const note = document.createElement("div");
      note.className = "seg-note";
      note.textContent = `${pools.length} pools play side by side: round 1 of every `
        + "pool at the same time, then round 2, and so on.";
      container.appendChild(note);
    }
    // Tree layout for clean knockout parts; per-pool columns for a multi-pool
    // stage; plain columns for a single league / losers bracket.
    const tree = seg.part !== "pool" && seg.part !== "losers" && isBinaryTree(seg.rounds);
    let el;
    if (tree) el = renderTree(seg.rounds, opts);
    else if (pools.length > 1) el = renderPoolColumns(seg.rounds, opts);
    else el = renderColumns(seg.rounds, opts);
    container.appendChild(el);
  });
}

// --- team draw (ties + rubbers) --------------------------------------------
function renderTeamDraw(container, view, opts) {
  view.rounds.forEach(rnd => {
    const col = document.createElement("div");
    col.className = "tie-round";
    col.innerHTML = `<h4>${rnd.name}</h4>`;
    rnd.matches.forEach(m => col.appendChild(tieCard(m, opts)));
    container.appendChild(col);
  });
}

function tieCard(m, opts) {
  // Two columns: Team 1 (side1) on the left, Team 2 (side2) on the right, each
  // rubber a row aligned under its team, color-coded.
  const card = document.createElement("div");
  card.className = "tie-card";
  const t1 = m.side1, t2 = m.side2, win = m.winner;
  const c1 = (t1 && t1.color) || "var(--navy)";
  const c2 = (t2 && t2.color) || "var(--muted)";
  const n1 = (t1 && t1.label) || "TBD", n2 = (t2 && t2.label) || "TBD";
  const w1 = win && t1 && t1.key === win, w2 = win && t2 && t2.key === win;
  const tally = m.tally ? `${m.tally[0]}–${m.tally[1]}` : "vs";
  let grid = "";
  (m.rubbers || []).forEach(r => grid += rubberGridRow(r, c1, c2, opts));
  // Entries left without an opponent (one team fields more pairs in an event).
  const gaps = (m.gaps || []).map(g => {
    const rest = g.unmatched === 1 ? "1 entry has no opponent"
                                   : `${g.unmatched} entries have no opponent`;
    return `${g.event}: ${g.a} vs ${g.b} — ${rest}`;
  }).join("<br>");
  card.innerHTML =
    `<div class="tie-head">
       <span class="tside" style="color:${c1}">${w1 ? "▶ " : ""}${n1}</span>
       <span class="tie-tally">${tally}</span>
       <span class="tside" style="color:${c2}">${n2}${w2 ? " ◀" : ""}</span></div>` +
    (grid ? `<div class="tie-grid" style="--c1:${c1};--c2:${c2}">
       <div class="tg-h"></div><div class="tg-h" style="color:${c1}">${n1}</div>
       <div class="tg-h" style="color:${c2}">${n2}</div>${grid}</div>` : "") +
    (gaps ? `<div class="tie-gap">${gaps}</div>` : "");
  if (opts.editable) {
    card.addEventListener("change", (ev) => {
      const inp = ev.target;
      if (!inp.classList || !inp.classList.contains("gin")) return;
      const rid = inp.dataset.r;
      const r = (m.rubbers || []).find(x => x.id === rid);
      if (!r) return;
      const maxG = r.max_games || 3, needed = Math.floor(maxG / 2) + 1;
      const games = [];
      for (let g = 0; g < maxG; g++) {
        const a = card.querySelector(`.gin[data-r="${rid}"][data-g="${g}"][data-side="0"]`).value;
        const b = card.querySelector(`.gin[data-r="${rid}"][data-g="${g}"][data-side="1"]`).value;
        if (a === "" && b === "") continue;
        if (a === "" || b === "") return;
        games.push([parseInt(a, 10), parseInt(b, 10)]);
      }
      let w0 = 0, wa = 0;
      games.forEach(([a, b]) => { if (a > b) w0++; else if (b > a) wa++; });
      if (games.length && Math.max(w0, wa) >= needed && w0 !== wa && opts.onResult)
        opts.onResult(rid, games);
    });
  }
  return card;
}

function _rubberBoxes(r, idx, editing) {
  if (editing) {
    const maxG = r.max_games || 3;
    let h = "";
    for (let g = 0; g < maxG; g++) {
      const v = r.games && r.games[g] ? r.games[g][idx] : "";
      h += `<input class="gin" type="number" min="0" data-r="${r.id}" ` +
           `data-g="${g}" data-side="${idx}" value="${v}">`;
    }
    return h;
  }
  return (r.games || []).map(g => {
    const won = g[idx] > g[1 - idx];
    return `<span class="gbox${won ? " gwin" : ""}">${g[idx]}</span>`;
  }).join("");
}

function rubberGridRow(r, c1, c2, opts) {
  const editing = !!(opts.editable && r.side1 && r.side2 && !r.walkover);
  const cell = (side, idx) => {
    const label = (side && side.label) || "—";
    const won = r.winner && side && side.key === r.winner ? " win" : "";
    return `<div class="tg-cell${won}"><span class="nm">${label}</span>` +
      `<span class="games">${_rubberBoxes(r, idx, editing)}</span></div>`;
  };
  const wo = r.walkover ? ' · W/O' : "";
  return `<div class="tg-rl">${r.label}${wo}</div>${cell(r.side1, 0)}${cell(r.side2, 1)}`;
}

function renderTeamRosters(rosters) {
  const wrap = document.createElement("div");
  wrap.className = "standings-wrap";
  rosters.forEach(t => {
    const box = document.createElement("div");
    box.className = "standings";
    const rows = t.players.map(p =>
      `<tr><td>${p.name}</td><td>${p.wins}-${p.losses}</td></tr>`).join("");
    const clr = t.color ? `style="background:${t.color}"` : "";
    box.innerHTML = `<div class="standings-title" ${clr}>${t.name} — players</div>` +
      `<table><thead><tr><th>Player</th><th>Rubbers W-L</th></tr></thead><tbody>${rows}</tbody></table>`;
    wrap.appendChild(box);
  });
  return wrap;
}

function renderTeamStandings(standings) {
  const wrap = document.createElement("div");
  wrap.className = "standings-wrap";
  const sign = v => (v > 0 ? "+" : "") + v;
  const league = standings.some(p => p.rank_by === "league_points");
  standings.forEach(pool => {
    const box = document.createElement("div");
    box.className = "standings";
    const rows = pool.rows.map(r => `
      <tr><td>${r.rank}</td>
        <td><span class="team-dot" style="background:${r.color || "var(--muted)"}"></span>${r.label}</td>
        <td>${r.wins}-${r.losses}${r.draws ? "-" + r.draws : ""}</td>
        <td>${r.rubbers_for}-${r.rubbers_against}</td>
        <td>${sign(r.rubber_diff)}</td>
        <td>${sign(r.point_diff)}</td>
        ${league ? `<td><b>${r.league_points}</b></td>` : ""}</tr>`).join("");
    const rankLabel = { tie_wins: "ties won", league_points: "league points",
                        rubbers: "rubbers won" }[pool.rank_by] || "ties won";
    box.innerHTML = `<div class="standings-title">${pool.pool === "A" ? "Standings" : "Pool " + pool.pool}` +
      `${pool.complete ? "" : " (in progress)"} <span style="font-weight:400;font-size:11px">· by ${rankLabel}</span></div>
      <table><thead><tr><th>#</th><th>Team</th>
        <th title="ties won-lost${league ? "-drawn" : ""}">Ties</th>
        <th title="rubbers won-lost">Rubbers</th>
        <th title="rubber differential">+/-</th>
        <th title="point differential">Pts&plusmn;</th>
        ${league ? "<th title=\"league points\">Pts</th>" : ""}</tr></thead>
      <tbody>${rows}</tbody></table>`;
    wrap.appendChild(box);
  });
  return wrap;
}

function renderStandings(standings) {
  // Team-league standings have different columns (ties / rubbers / league pts).
  if (standings.some(p => p.rows.some(r => r.rubbers_for !== undefined)))
    return renderTeamStandings(standings);
  const wrap = document.createElement("div");
  wrap.className = "standings-wrap";
  // Row class from live qualification status. Older views without `qualify`
  // fall back to the plain top-of-pool `advances` flag.
  const rowClass = r => r.qualify === "auto" ? "adv"
    : r.qualify === "wildcard" ? "wild"
    : (r.qualify === undefined && r.advances) ? "adv" : "";
  const hasWild = standings.some(p => p.rows.some(r => r.qualify === "wildcard"));
  const allDone = standings.every(p => p.complete);
  standings.forEach(pool => {
    const box = document.createElement("div");
    box.className = "standings";
    const sign = v => (v > 0 ? "+" : "") + v;
    const rows = pool.rows.map(r => `
      <tr class="${rowClass(r)}">
        <td>${r.rank}</td><td>${r.label}</td>
        <td>${r.wins}-${r.losses}</td>
        <td>${sign(r.game_diff)}</td>
        <td>${r.points_for}</td><td>${r.points_against}</td>
        <td>${sign(r.point_diff)}</td></tr>`).join("");
    box.innerHTML = `<div class="standings-title">Pool ${pool.pool}` +
      `${pool.complete ? "" : " (in progress)"}</div>
      <table><thead><tr><th>#</th><th>Entry</th><th>W-L</th><th title="game difference">Games</th>
      <th title="points won">PF</th><th title="points allowed">PA</th>
      <th title="point difference">Diff</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
    wrap.appendChild(box);
  });
  if (hasWild) {
    const legend = document.createElement("div");
    legend.className = "standings-legend";
    legend.innerHTML =
      `<span class="key adv"></span> Qualifies (top of pool)` +
      `<span class="key wild"></span> Wildcard` +
      (allDone ? "" : ` <em>&mdash; wildcards are projected and shift as scores are reported`
        + `; final once every pool is complete.</em>`);
    wrap.appendChild(legend);
  }
  return wrap;
}

