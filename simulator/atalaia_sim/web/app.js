// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The simulator's web view. It polls /api/state and sends actions to
// /api/action. Everything a script produced is shown with textContent,
// never as HTML.
"use strict";

const POLL_MS = 200;
const MAX_ROWS = 500;
const TEAM_COLORS = {
  red: "#e5484d", blue: "#3e63dd", green: "#30a46c", yellow: "#e2b203",
  orange: "#f76b15", purple: "#8e4ec6", pink: "#d6409f", white: "#c9ccd1",
  black: "#4a4f57", grey: "#8b8d98", gray: "#8b8d98", cyan: "#00a2c7",
};
const PALETTE = ["#e5484d", "#3e63dd", "#30a46c", "#e2b203", "#8e4ec6", "#f76b15", "#00a2c7", "#d6409f"];

const $ = (id) => document.getElementById(id);
let state = null;
let generation = null;
let since = 0;
let cards = new Map();
let lastAudio = new Map();

function teamColor(name) {
  if (state && !(name in TEAM_COLORS)) {
    const i = state.teams.indexOf(name);
    if (i >= 0) return PALETTE[i % PALETTE.length];
  }
  return TEAM_COLORS[name] || "var(--muted)";
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k in node) node[k] = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c);
  return node;
}

function formatTime(ms) {
  const tenths = Math.floor(ms / 100);
  const s = Math.floor(tenths / 10);
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  const ss = String(s % 60).padStart(2, "0");
  const mm = h ? String(m % 60).padStart(2, "0") : String(m);
  return `${h ? h + ":" : ""}${mm}:${ss}.${tenths % 10}`;
}

function compact(value) {
  return JSON.stringify(value);
}

// ---- talking to the server ----

let noticeTimer = null;
function notice(message) {
  const box = $("notice");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { box.hidden = true; }, 4000);
}

// Actions go out one at a time, in order: a quick tap must not let a
// release overtake its hold.
let queue = Promise.resolve();
function act(action, args = {}) {
  queue = queue.then(() => send(action, args));
  return queue;
}

async function send(action, args) {
  try {
    const res = await fetch("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...args }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      notice(body.error || `${action} failed (${res.status})`);
    }
  } catch (err) {
    notice(`The simulator is not reachable: ${err.message}`);
  }
  poll(true);
}

// One request for state at a time, so no event is shown twice.
let polling = false;
async function poll(once = false) {
  if (polling) {
    if (!once) setTimeout(poll, POLL_MS);
    return;
  }
  polling = true;
  try {
    const res = await fetch(`/api/state?since=${since}`, { cache: "no-store" });
    if (res.ok) render(await res.json());
  } catch (err) {
    $("game-state").textContent = "disconnected";
    $("game-state").className = "chip bad";
  } finally {
    polling = false;
    if (!once) setTimeout(poll, POLL_MS);
  }
}

// ---- rendering ----

function render(next) {
  if (next.generation !== generation) {
    generation = next.generation;
    since = 0;
    $("events").replaceChildren();
    $("nodes").replaceChildren();
    cards = new Map();
    lastAudio = new Map();
    if (next.events_from !== 0) return; // fetch again from the start
  }
  state = next;
  renderBar();
  renderProblems();
  renderScores();
  for (const node of state.nodes) renderNode(node);
  renderEvents();
}

function renderBar() {
  const { mode, clock, game } = state;
  document.title = `${mode.name} · Atalaia simulator`;
  $("mode").textContent = `${mode.name} ${mode.version}`;
  $("clock").textContent = formatTime(state.time_ms);

  const speed = $("speed");
  if (speed.options.length !== clock.speeds.length) {
    speed.replaceChildren(...clock.speeds.map((s) => el("option", { value: s, textContent: `${s}×` })));
  }
  if (document.activeElement !== speed) speed.value = clock.speed;

  const on = game.started && !game.ended;
  $("run").textContent = clock.running ? "Stop" : "Run";
  $("run").disabled = !on || game.paused;
  for (const b of document.querySelectorAll("[data-step]")) b.disabled = !on || game.paused;
  $("start").disabled = game.started;
  $("pause").disabled = !on;
  $("pause").textContent = game.paused ? "Resume" : "Pause";
  $("end").disabled = !on;

  const chip = $("game-state");
  const [label, cls] = !game.started ? ["not started", "chip"]
    : game.ended ? ["ended", "chip bad"]
    : game.paused ? ["paused", "chip warn"]
    : clock.running ? ["running", "chip on"] : ["clock stopped", "chip warn"];
  chip.textContent = label;
  chip.className = cls;
}

function renderProblems() {
  const box = $("problems");
  box.hidden = state.problems.length === 0;
  const list = $("problem-list");
  if (list.childElementCount !== state.problems.length) {
    list.replaceChildren(...state.problems.map((p) => el("li", { textContent: p })));
  }
}

function renderScores() {
  $("scores").replaceChildren(...state.teams.map((team) => el("li", {},
    el("span", { class: "swatch", style: `background:${teamColor(team)}` }),
    el("span", { textContent: team }),
    el("span", { class: "points", textContent: String(state.scores[team]) }),
  )));
  const params = Object.entries(state.params).map(([k, v]) => `${k} ${compact(v)}`).join(" · ");
  $("params").textContent = params ? `Parameters: ${params}` : "";
}

function makeCard(node) {
  const card = $("node-template").content.firstElementChild.cloneNode(true);
  card.querySelector(".name").textContent = node.name;
  card.querySelector(".role").textContent = node.role;
  const teams = card.querySelector(".teams");
  for (const team of state.teams) {
    const hold = el("button", { type: "button", class: "hold", textContent: `${team}: hold` });
    hold.style.setProperty("--team", teamColor(team));
    hold.dataset.team = team;
    const tap = el("button", { type: "button", class: "tap", textContent: "tap",
                               title: `Sends team_input.press for ${team}. Modes that only react to holds ignore it.` });
    hold.addEventListener("pointerdown", (e) => {
      if (hold.disabled || e.button !== 0) return;
      hold.setPointerCapture(e.pointerId);
      act("hold", { node: node.name, team });
    });
    const release = () => act("release", { node: node.name });
    hold.addEventListener("pointerup", release);
    hold.addEventListener("pointercancel", release);
    hold.addEventListener("keydown", (e) => {
      if ((e.key === " " || e.key === "Enter") && !e.repeat) {
        e.preventDefault();
        act("hold", { node: node.name, team });
      }
    });
    hold.addEventListener("keyup", (e) => {
      if (e.key === " " || e.key === "Enter") release();
    });
    tap.addEventListener("click", () => act("press", { node: node.name, team }));
    teams.append(el("div", { class: "team" }, hold, tap));
  }
  $("nodes").append(card);
  cards.set(node.name, card);
  return card;
}

function renderNode(node) {
  const card = cards.get(node.name) || makeCard(node);
  const { game } = state;
  card.classList.toggle("ended", node.status !== "running");

  const status = card.querySelector(".status");
  status.textContent = node.status;
  status.className = "status chip " + (node.status === "running" ? "on" : node.status === "halted" ? "bad" : "");
  status.title = node.error || "";

  const template = card.querySelector(".template");
  const dl = card.querySelector(".screen-data");
  if (node.screen) {
    const [name, data] = node.screen.args;
    template.textContent = name;
    template.className = "template";
    const rows = [];
    for (const [k, v] of Object.entries(data || {})) {
      rows.push(el("dt", { textContent: k }), el("dd", { textContent: typeof v === "string" ? v : compact(v) }));
    }
    dl.replaceChildren(...rows);
  } else {
    template.textContent = "no screen shown yet";
    template.className = "template empty";
    dl.replaceChildren();
  }

  card.querySelector(".outputs").replaceChildren(...node.outputs.map((o) => {
    const team = o.args.find((a) => typeof a === "string" && state.teams.includes(a));
    return el("li", {},
      el("span", { class: "swatch", style: team ? `background:${teamColor(team)}` : "" }),
      el("span", { textContent: `${o.target}:${o.method}(${o.args.map(compact).join(", ")})` }),
    );
  }));

  const audio = card.querySelector(".audio");
  if (node.audio) {
    const key = `${node.audio.t}:${compact(node.audio.args)}`;
    const fresh = lastAudio.get(node.name) !== key && lastAudio.has(node.name);
    lastAudio.set(node.name, key);
    audio.textContent = `♪ ${node.audio.method} ${node.audio.args.map(compact).join(" ")} at ${formatTime(node.audio.t)}`;
    if (fresh) {
      audio.classList.add("fresh");
      setTimeout(() => audio.classList.remove("fresh"), 1500);
    }
  } else {
    lastAudio.set(node.name, "");
    audio.textContent = "no sound yet";
  }

  const playable = game.started && !game.ended && !game.paused && node.status === "running";
  for (const button of card.querySelectorAll(".hold, .tap")) button.disabled = !playable;
  for (const hold of card.querySelectorAll(".hold")) {
    const held = node.hold && node.hold.team === hold.dataset.team;
    hold.classList.toggle("held", Boolean(held));
    hold.textContent = held ? `${hold.dataset.team}: ${(node.hold.ms / 1000).toFixed(1)} s` : `${hold.dataset.team}: hold`;
  }

  const input = card.querySelector(".input");
  const last = node.input;
  if (last) {
    const data = Object.entries(last.data).map(([k, v]) => `${k} ${typeof v === "string" ? v : compact(v)}`).join(", ");
    const verdict = last.accepted ? "" : " (refused: the node is not taking inputs)";
    input.textContent = `Last input: ${last.type} (${data}) at ${formatTime(last.t)}${verdict}`;
  } else {
    input.textContent = "No input yet";
  }

  card.querySelector(".node-scores").textContent =
    state.teams.map((t) => `${t} ${node.scores[t]}`).join(" · ");
  card.querySelector(".mem").textContent = `${(node.mem / 1024).toFixed(1)} KB`;
  const pre = card.querySelector(".logs pre");
  const text = node.logs.join("\n") || "(empty)";
  if (pre.textContent !== text) pre.textContent = text;
}

function renderEvents() {
  const body = $("events");
  const fresh = state.events_from > 0;
  for (const e of state.events) {
    const team = el("span", { class: "dot", title: e.team || "no team",
                              style: e.team ? `background:${teamColor(e.team)}` : "" });
    const prio = e.prio === "normal" ? "" : el("span", { class: `prio ${e.prio}`, textContent: e.prio });
    const row = el("tr", { class: fresh ? "new" : "" },
      el("td", { class: "t", textContent: formatTime(e.t) }),
      el("td", { textContent: e.node }),
      el("td", { class: "type" }, team, e.type, prio),
      el("td", { class: "data", textContent: Object.keys(e.data).length ? compact(e.data) : "" }),
      el("td", { class: "bytes", textContent: e.bytes == null ? "—" : String(e.bytes) }),
    );
    body.prepend(row);
  }
  while (body.childElementCount > MAX_ROWS) body.lastElementChild.remove();
  since = state.events_from + state.events.length;
  $("event-count").textContent = `(${state.events_total})`;
}

// ---- controls ----

$("run").addEventListener("click", () => act("clock", { running: !state.clock.running }));
$("speed").addEventListener("change", (e) => act("clock", { speed: Number(e.target.value) }));
for (const b of document.querySelectorAll("[data-step]")) {
  b.addEventListener("click", () => act("step", { seconds: Number(b.dataset.step) }));
}
$("start").addEventListener("click", () => act("start"));
$("pause").addEventListener("click", () => act(state.game.paused ? "resume" : "pause"));
$("end").addEventListener("click", () => act("end"));
$("reset").addEventListener("click", () => {
  if (!state.game.started || confirm("Start over? The current game and its log are lost.")) act("reset");
});

poll();
