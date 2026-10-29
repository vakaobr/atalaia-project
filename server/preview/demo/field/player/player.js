// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
// The live demo's "player's view": what one checked-in demo player's phone shows, read-only, refreshed every
// two seconds from /player/data.json (the proxy reads it with that player's own token and sends back only what
// the phone's screen would show). The player is a made-up callsign; the plan is the demo field's.
'use strict';

const TEXTS = {
  pt: {
    banner: 'Demonstração: vista de uma pessoa inventada que joga. Só de leitura.', title: 'Vista de quem joga',
    back: '← Demonstração', waiting: 'À espera do próximo jogo…',
    me: 'Eu', game: 'Jogo', plan: 'Plano do campo', events: 'Últimos acontecimentos',
    team: 'Equipa', squad: 'Esquadra', role: 'Função', status: 'Entrada', replicas: 'Cronógrafo',
    teams: { red: 'vermelha', blue: 'azul' }, roles: { player: 'participante', squad_leader: 'chefia de esquadra',
      vip: 'VIP', marshal: 'arbitragem', spectator: 'público', gm: 'organização' },
    statuses: { checked_in: 'registada', expected: 'esperada', pending: 'à espera de confirmação',
      confirmed: 'confirmada', removed: 'retirada' },
    chrono: { pending: 'por medir', passed: 'dentro do limite', refused: 'acima do limite', withdrawn: 'retirada',
      none: 'sem réplica declarada' },
    states: { ready: 'a preparar', running: 'a decorrer', paused: 'em pausa', ended: 'terminado' },
    planNote: 'As bolas grandes são as caixas, na cor de quem as tem; os pontos são a minha equipa (o meu com ' +
              'contorno). O jogo só mostra as posições enquanto decorre.',
    planTitle: 'Plano do campo com as caixas e a minha equipa',
    floor: 'Piso', where: (r) => `A minha posição: ${r}`,
    levelNote: 'Escolha o piso nos botões. Quadrados: quem é localizado por balizas BLE; círculos: por GPS com o ' +
               'piso escolhido; vazado: piso desconhecido (\u201cNão sei\u201d). Os pontos pequenos são as balizas.',
    unsure: (n) => `${n} da equipa não sabe em que piso está: aparece vazado em todos os pisos.`,
    captured: (b, t) => `a equipa ${t} capturou a caixa ${b}`, start: 'o jogo começou',
    end: (w) => (w ? `o jogo terminou, ganhou a equipa ${w}` : 'o jogo terminou')
  },
  en: {
    banner: 'Demo: the view of a made-up player. Read-only.', title: 'Player’s view',
    back: '← Demo', waiting: 'Waiting for the next game…',
    me: 'Me', game: 'Game', plan: 'Field plan', events: 'Latest events',
    team: 'Team', squad: 'Squad', role: 'Role', status: 'Check-in', replicas: 'Chronograph',
    teams: { red: 'red', blue: 'blue' }, roles: { player: 'player', squad_leader: 'squad leader', vip: 'VIP',
      marshal: 'marshal', spectator: 'spectator', gm: 'organiser' },
    statuses: { checked_in: 'checked in', expected: 'expected', pending: 'waiting for confirmation',
      confirmed: 'confirmed', removed: 'removed' },
    chrono: { pending: 'not measured yet', passed: 'within the limit', refused: 'over the limit', withdrawn: 'withdrawn',
      none: 'no replica declared' },
    states: { ready: 'getting ready', running: 'playing', paused: 'paused', ended: 'finished' },
    planNote: 'The big circles are the boxes, in the colour of whoever holds them; the dots are my team (mine ' +
              'outlined). Positions are shown only while the game runs.',
    planTitle: 'Field plan with the boxes and my team',
    floor: 'Floor', where: (r) => `My position: ${r}`,
    levelNote: 'Pick the floor with the buttons. Squares: located by BLE beacons; circles: by GPS with the floor ' +
               'chosen; hollow: floor not known (\u201cNot sure\u201d). The small dots are the beacons.',
    unsure: (n) => `${n} on the team not sure of their floor: drawn hollow on every floor.`,
    captured: (b, t) => `team ${t} captured box ${b}`, start: 'the game started',
    end: (w) => (w ? `the game ended, team ${w} won` : 'the game ended')
  },
  de: {
    banner: 'Demo: die Sicht einer erfundenen Spielerin. Nur lesen.', title: 'Sicht der Spielenden',
    back: '← Demo', waiting: 'Warte auf das nächste Spiel…',
    me: 'Ich', game: 'Spiel', plan: 'Geländeplan', events: 'Letzte Ereignisse',
    team: 'Team', squad: 'Gruppe', role: 'Rolle', status: 'Check-in', replicas: 'Chronograph',
    teams: { red: 'Rot', blue: 'Blau' }, roles: { player: 'Spieler:in', squad_leader: 'Gruppenführung',
      vip: 'VIP', marshal: 'Schiedsperson', spectator: 'Zuschauende', gm: 'Spielleitung' },
    statuses: { checked_in: 'eingecheckt', expected: 'erwartet', pending: 'wartet auf Bestätigung',
      confirmed: 'bestätigt', removed: 'entfernt' },
    chrono: { pending: 'noch nicht gemessen', passed: 'innerhalb der Grenze', refused: '\u00fcber der Grenze',
      withdrawn: 'zur\u00fcckgezogen', none: 'keine Replika angemeldet' },
    states: { ready: 'in Vorbereitung', running: 'läuft', paused: 'pausiert', ended: 'beendet' },
    planNote: 'Die großen Kreise sind die Boxen in der Farbe des haltenden Teams; die Punkte sind mein Team ' +
              '(ich mit Umrandung). Positionen gibt es nur, solange das Spiel läuft.',
    planTitle: 'Geländeplan mit den Boxen und meinem Team',
    floor: 'Etage', where: (r) => `Meine Position: ${r}`,
    levelNote: 'Etage mit den Tasten wählen. Quadrate: per BLE-Beacon geortet; Kreise: per GPS mit gewählter ' +
               'Etage; hohl: Etage unbekannt (\u201eNicht sicher\u201c). Die kleinen Punkte sind die Beacons.',
    unsure: (n) => `${n} im Team nicht sicher, auf welcher Etage: auf jeder Etage hohl gezeichnet.`,
    captured: (b, t) => `Team ${t} hat Box ${b} eingenommen`, start: 'das Spiel hat begonnen',
    end: (w) => (w ? `das Spiel ist zu Ende, Team ${w} hat gewonnen` : 'das Spiel ist zu Ende')
  },
  'zh-tw': {
    banner: '示範：虛構玩家的視角，僅供檢視。', title: '玩家視角', back: '← 示範', waiting: '等待下一場遊戲…',
    me: '我', game: '遊戲', plan: '場地平面圖', events: '最新事件',
    team: '隊伍', squad: '小隊', role: '角色', status: '報到', replicas: '測速',
    teams: { red: '紅隊', blue: '藍隊' }, roles: { player: '玩家', squad_leader: '小隊長', vip: 'VIP', marshal: '裁判',
      spectator: '觀眾', gm: '主辦方' },
    statuses: { checked_in: '已報到', expected: '預期', pending: '等待確認', confirmed: '已確認', removed: '已移除' },
    chrono: { pending: '尚未測量', passed: '在限值內', refused: '超出限值', withdrawn: '已撤回', none: '未申報複製品' },
    states: { ready: '準備中', running: '進行中', paused: '暫停', ended: '已結束' },
    planNote: '大圓圈是盒子，顏色為佔有它的隊伍；小圓點是我的隊伍（我有外框）。位置只在遊戲進行時顯示。',
    planTitle: '顯示盒子與我的隊伍的場地平面圖',
    floor: '樓層', where: (r) => `我的位置：${r}`,
    levelNote: '用按鈕選擇樓層。方塊：以 BLE 信標定位；圓圈：以 GPS 搭配所選樓層；空心：樓層未知（「不確定」）。小點為信標。',
    unsure: (n) => `隊伍中有 ${n} 位不確定所在樓層：在每個樓層都以空心顯示。`,
    captured: (b, t) => `${t}佔領了盒子 ${b}`, start: '遊戲開始',
    end: (w) => (w ? `遊戲結束，${w}獲勝` : '遊戲結束')
  }
};
const LANGS = { pt: 'Português', en: 'English', de: 'Deutsch', 'zh-tw': '繁體中文' };
const COLOURS = { red: '#d6453b', blue: '#3d74d6' };
const NS = 'http://www.w3.org/2000/svg';

function pickLang() {
  const asked = new URLSearchParams(location.search).get('lang');
  if (asked && TEXTS[asked.toLowerCase()]) return asked.toLowerCase();
  try {
    const saved = localStorage.getItem('demo-lang');
    if (saved && TEXTS[saved]) return saved;
  } catch (e) { /* storage may be off */ }
  return 'pt';
}

let lang = pickLang();
let data = null;
let chosen = null;   // the floor the visitor picked (null: follow the player's own)
let planSrc = '';
let fetchedAt = 0;

const $ = (id) => document.getElementById(id);

function clockText(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

function svg(tag, attrs) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

function toPlan(geo, lat, lon) {
  const c = geo && geo.georef && geo.georef.corners;
  if (!c) return null;
  const x = (lon - c.top_left.lon) / (c.top_right.lon - c.top_left.lon);
  const y = (c.top_left.lat - lat) / (c.top_left.lat - c.bottom_left.lat);
  return [x * 720, y * 540];
}

function chronoText(t, replicas) {
  if (!replicas.length) return t.chrono.none;
  return replicas.map((r) => t.chrono[r.state] || r.state).join(', ');
}

function teamName(t, team) { return t.teams[team] || team || ''; }

function levelsOn() {
  return !!(data && data.levels && data.levels.enabled && data.levels.count > 1);
}

function ownLevel() {
  const me = (data.positions || []).find((p) => p.player_id === data.you);
  return me && Number.isInteger(me.level) ? me.level : null;
}

// The floor shown: the visitor's pick, else the player's own, else 0 (as a phone does, PM-7).
function viewLevel() {
  if (!levelsOn()) return 0;
  const n = data.levels.count;
  if (chosen !== null && chosen >= n) chosen = null;
  const v = chosen !== null ? chosen : ownLevel();
  return v !== null && v < n ? v : 0;
}

function renderStatic() {
  const t = TEXTS[lang];
  document.documentElement.lang = lang === 'zh-tw' ? 'zh-TW' : lang;
  document.title = 'Atalaia · ' + t.title;
  $('banner').textContent = t.banner;
  $('title').textContent = t.title;
  $('back').textContent = t.back;
  $('back').href = `/?lang=${lang}`;
  $('waiting').textContent = t.waiting;
  $('h-me').textContent = t.me;
  $('h-game').textContent = t.game;
  $('h-plan').textContent = t.plan;
  $('h-events').textContent = t.events;
  $('plan-note').textContent = levelsOn() ? t.planNote + ' ' + t.levelNote : t.planNote;
  $('plan-title').textContent = t.planTitle;
  const langs = $('langs');
  langs.replaceChildren(...Object.entries(LANGS).map(([code, name]) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = name;
    b.lang = code === 'zh-tw' ? 'zh-TW' : code;
    if (code === lang) b.setAttribute('aria-current', 'true');
    b.addEventListener('click', () => {
      lang = code;
      try { localStorage.setItem('demo-lang', code); } catch (e) { /* ignore */ }
      renderStatic();
      renderData();
    });
    return b;
  }));
}

function renderData() {
  const t = TEXTS[lang];
  $('waiting').hidden = !!data;
  $('view').hidden = !data;
  if (!data) return;
  const me = data.me, game = data.game;
  $('chip').style.background = COLOURS[me.team] || 'transparent';
  $('callsign').textContent = me.display_name;
  const rows = [[t.team, teamName(t, me.team)], [t.squad, me.squad ? String(me.squad) : '–'],
                [t.role, t.roles[me.role] || me.role], [t.status, t.statuses[me.status] || me.status],
                [t.replicas, chronoText(t, me.replicas || [])]];
  $('me-list').replaceChildren(...rows.flatMap(([k, v]) => {
    const dt = document.createElement('dt'); dt.textContent = k;
    const dd = document.createElement('dd'); dd.textContent = v;
    return [dt, dd];
  }));
  $('game-name').textContent = game.name;
  const badge = $('game-state');
  badge.textContent = t.states[game.state] || game.state;
  badge.className = 'badge ' + game.state;
  const scores = (data.score && data.score.teams) || {};
  $('scores').replaceChildren(...(game.teams || []).map((team) => {
    const d = document.createElement('div');
    d.className = `score ${team}${team === me.team ? ' you' : ''}`;
    const b = document.createElement('b'); b.textContent = String(scores[team] ?? 0);
    d.append(b, teamName(t, team));
    return d;
  }));
  renderClock();
  // the plan: boxes, then people
  const nodes = new Map((data.nodes || []).map((n) => [String(n.node_id), n]));
  const on = levelsOn();
  const view = viewLevel();
  if (!on) chosen = null;
  $('plan-note').textContent = on ? t.planNote + ' ' + t.levelNote : t.planNote;
  const chips = $('levels');
  chips.hidden = !on;
  chips.setAttribute('aria-label', t.floor);
  chips.replaceChildren(...(on ? data.levels.names.map((name, i) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = name || String(i);
    b.setAttribute('aria-pressed', String(i === view));
    b.addEventListener('click', () => { chosen = i; renderData(); });
    return b;
  }) : []));
  const stamp = ((data.levels && data.levels.stamps) || [])[view];
  const src = `/player/field.png?level=${view}&v=${encodeURIComponent(stamp || '')}`;
  if (src !== planSrc) { planSrc = src; $('plan-img').setAttribute('href', src); }
  const beacons = $('plan-beacons');
  beacons.replaceChildren(...(on ? (data.beacons || []).filter((b) => b.level === view && b.x !== null).map((b) =>
    svg('circle', { cx: b.x * 720, cy: b.y * 540, r: 4, fill: '#ffffff', stroke: '#444444', 'stroke-width': 1.5 })) : []));
  const boxes = $('plan-boxes');
  boxes.replaceChildren();
  for (const [id, pos] of Object.entries(data.boxes || {})) {
    if (on && (pos.level || 0) !== view) continue;
    const n = nodes.get(id) || {};
    boxes.append(svg('circle', { cx: pos.x * 720, cy: pos.y * 540, r: 22, fill: COLOURS[n.owner] || '#d9d9d9',
                                 stroke: '#101010', 'stroke-width': 3, 'fill-opacity': 0.9 }));
    const label = svg('text', { x: pos.x * 720, y: pos.y * 540 + 5, 'text-anchor': 'middle', 'font-size': 13,
                                'font-weight': 700, fill: '#101010' });
    label.textContent = (n.name || id).slice(0, 2).toUpperCase();
    boxes.append(label);
  }
  const people = $('plan-people');
  people.replaceChildren();
  let unsure = 0;
  for (const p of data.positions || []) {
    // a beacon gives the place on the plan itself; a GPS fix goes through the georeference
    const at = typeof p.x === 'number' && typeof p.y === 'number' ? [p.x * 720, p.y * 540]
      : (typeof p.lat === 'number' ? toPlan(data.georef, p.lat, p.lon) : null);
    if (!at) continue;
    const hollow = on && !Number.isInteger(p.level);   // a floor not known (PM-6): hollow, on the floor shown
    if (on && !hollow && p.level !== view) continue;
    if (hollow) unsure += 1;
    const mine = p.player_id === data.you;
    const r = mine ? 9 : 6;
    // the controller gives a position's team as its number in the game's list (1, 2), a name only in older data
    const colour = COLOURS[typeof p.team === 'number' ? (game.teams || [])[p.team - 1] : p.team] || '#ffffff';
    const common = { fill: hollow ? 'none' : colour, stroke: hollow ? colour : (mine ? '#ffffff' : '#101010'),
                     'stroke-width': hollow ? 3 : (mine ? 3 : 1.5) };
    people.append(p.source === 'ble'
      ? svg('rect', { x: at[0] - r, y: at[1] - r, width: 2 * r, height: 2 * r, rx: 2, ...common })
      : svg('circle', { cx: at[0], cy: at[1], r, ...common }));
  }
  const unsureNote = $('unsure-note');
  unsureNote.hidden = !unsure;
  unsureNote.textContent = unsure ? t.unsure(unsure) : '';
  const here = (data.positions || []).find((p) => p.player_id === data.you);
  const where = $('where');
  where.hidden = !(here && here.room);
  where.textContent = here && here.room
    ? t.where(here.room + (on && Number.isInteger(here.level) ? ', ' + data.levels.names[here.level] : '')) : '';
  // the events
  const names = new Map([...nodes.entries()].map(([id, n]) => [id, n.name]));
  const shown = ['zone.captured', 'game.start', 'game.end'];
  const items = (data.log || []).filter((e) => shown.includes(e.type)).reverse().slice(0, 8).map((e) => {
    const li = document.createElement('li');
    const time = document.createElement('time'); time.textContent = clockText(e.t);
    const text = document.createElement('span');
    if (e.type === 'zone.captured') text.textContent = t.captured(names.get(String(e.node)) || e.node, teamName(t, e.team));
    else if (e.type === 'game.start') text.textContent = t.start;
    else if (e.type === 'game.end') text.textContent = t.end(teamName(t, e.data && e.data.winner));
    li.append(time, text);
    return li;
  });
  $('events').replaceChildren(...items);
}

function renderClock() {
  if (!data) return;
  const g = data.game;
  let ms = 0;
  if (g.state === 'running' && typeof g.game_time_ms === 'number') ms = g.game_time_ms + (Date.now() - fetchedAt);
  else if (typeof g.game_time_ms === 'number') ms = g.game_time_ms;
  else if (g.started_at && g.ended_at) ms = (g.ended_at - g.started_at) * 1000;
  $('clock').textContent = clockText(ms);
}

async function refresh() {
  try {
    const r = await fetch('/player/data.json', { cache: 'no-store' });
    data = r.ok ? await r.json() : null;
    fetchedAt = Date.now();
  } catch (e) { data = null; }
  renderData();
}

renderStatic();
refresh();
setInterval(refresh, 2000);
setInterval(renderClock, 500);
