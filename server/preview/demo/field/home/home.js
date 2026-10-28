// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
// The live demo's home page ("Try the demo"): what it is, the four ways to look at it, the read token to use.
'use strict';

const TEXTS = {
  pt: {
    banner: 'Demonstração: um campo simulado, com dados inventados. Só de leitura.',
    title: 'Experimente a demonstração',
    lead: 'Um campo simulado joga um jogo atrás do outro, sem ninguém: caixas virtuais, participantes com alcunhas ' +
          'inventadas, registos de entrada, cronógrafo e pontuações. Veja como a aplicação funciona de ponta a ' +
          'ponta. Só se pode ver: não é possível mudar nada, e nada aqui é real.',
    now_none: 'À espera do próximo jogo.', now_label: 'Agora', state: { ready: 'a preparar', running: 'a decorrer',
      paused: 'em pausa', ended: 'terminado' },
    console_t: 'Consola do GM', console_d: 'A consola de quem dirige o jogo, em modo de leitura: caixas, plano do ' +
      'campo, eventos e pontuações a atualizar sozinhos. Se pedir um código, use', console_a: 'Abrir a consola',
    board_t: 'Marcador', board_d: 'O ecrã grande do campo: a pontuação das equipas e o relógio do jogo.',
    board_a: 'Abrir o marcador',
    player_t: 'Vista de quem joga', player_d: 'O que se vê no telemóvel ao jogar: a equipa, o jogo, a pontuação e a ' +
      'posição da equipa no plano.', player_a: 'Abrir a vista de quem joga',
    site_t: 'Páginas públicas do campo', site_d: 'A página do campo e o marcador públicos, no servidor do campo, ' +
      'com o mesmo jogo.', site_a: 'Página do campo', site_b: 'Marcador público',
    note1: 'O jogo repete-se: quando um acaba, começa outro, e entre dois há uns instantes de pausa. De tempos a ' +
           'tempos a demonstração reinicia-se sozinha.',
    note2: 'Tudo é inventado: o campo, as alcunhas, as pontuações. A demonstração não pede nem guarda dados de ' +
           'quem a visita.',
    feedback: 'Diga-nos o que achou'
  },
  en: {
    banner: 'Demo: a simulated field with invented data. Read-only.',
    title: 'Try the demo',
    lead: 'A simulated field plays one game after another, with nobody there: virtual boxes, players with made-up ' +
          'callsigns, check-ins, chronograph readings and scores. See how the application works from end to end. ' +
          'You can only look: nothing can be changed, and nothing here is real.',
    now_none: 'Waiting for the next game.', now_label: 'Now', state: { ready: 'getting ready', running: 'playing',
      paused: 'paused', ended: 'finished' },
    console_t: 'GM console', console_d: 'The console of whoever runs the game, read-only: boxes, the field plan, ' +
      'events and scores updating by themselves. If it asks for a token, use', console_a: 'Open the console',
    board_t: 'Scoreboard', board_d: 'The big screen at the field: the teams’ scores and the game clock.',
    board_a: 'Open the scoreboard',
    player_t: 'Player’s view', player_d: 'What a player sees on their phone: the team, the game, the score and ' +
      'the squad’s position on the plan.', player_a: 'Open the player’s view',
    site_t: 'The field’s public pages', site_d: 'The field’s public page and scoreboard on the site server, ' +
      'showing the same game.', site_a: 'Field page', site_b: 'Public scoreboard',
    note1: 'The game repeats: when one ends another begins, with a short pause between. Now and then the demo ' +
           'restarts itself.',
    note2: 'Everything is invented: the field, the callsigns, the scores. The demo neither asks for nor keeps ' +
           'anything about the people who visit it.',
    feedback: 'Tell us what you think'
  },
  de: {
    banner: 'Demo: ein simuliertes Spielfeld mit erfundenen Daten. Nur lesen.',
    title: 'Demo ausprobieren',
    lead: 'Ein simuliertes Spielfeld spielt ein Spiel nach dem anderen, ganz ohne Menschen: virtuelle Boxen, ' +
          'Spielende mit erfundenen Rufnamen, Check-ins, Chrono-Messungen und Punktestände. So sieht man, wie ' +
          'die Anwendung von Anfang bis Ende arbeitet. Man kann nur zusehen: Nichts lässt sich ändern, und ' +
          'nichts hier ist echt.',
    now_none: 'Wartet auf das nächste Spiel.', now_label: 'Jetzt', state: { ready: 'in Vorbereitung',
      running: 'läuft', paused: 'pausiert', ended: 'beendet' },
    console_t: 'GM-Konsole', console_d: 'Die Konsole der Spielleitung, nur lesend: Boxen, Geländeplan, Ereignisse ' +
      'und Punktestände, die sich von selbst aktualisieren. Wenn ein Token verlangt wird, dieses benutzen:',
    console_a: 'Konsole öffnen',
    board_t: 'Anzeigetafel', board_d: 'Der große Bildschirm am Spielfeld: Punkte der Teams und Spieluhr.',
    board_a: 'Anzeigetafel öffnen',
    player_t: 'Sicht der Spielenden', player_d: 'Was man als Spielende:r auf dem Handy sieht: das Team, das Spiel, ' +
      'den Punktestand und die Position des Teams auf dem Plan.', player_a: 'Sicht der Spielenden öffnen',
    site_t: 'Öffentliche Seiten des Spielfelds', site_d: 'Die öffentliche Seite und Anzeigetafel des ' +
      'Spielfelds auf dem Standortserver, mit demselben Spiel.', site_a: 'Spielfeldseite',
    site_b: 'Öffentliche Anzeigetafel',
    note1: 'Das Spiel wiederholt sich: Wenn eines endet, beginnt ein neues, mit kurzer Pause dazwischen. ' +
           'Ab und zu startet sich die Demo selbst neu.',
    note2: 'Alles ist erfunden: das Spielfeld, die Rufnamen, die Punkte. Die Demo verlangt und speichert nichts ' +
           'über Besuchende.',
    feedback: 'Sagen Sie uns Ihre Meinung'
  },
  'zh-tw': {
    banner: '示範：模擬的場地，資料皆為虛構，僅供檢視。',
    title: '試用示範',
    lead: '一個模擬的場地會一場接著一場自動進行遊戲，無需任何人在場：虛擬的盒子、使用虛構代號的玩家、報到、' +
          '測速與比分。讓您看到整個應用程式如何從頭到尾運作。這裡只能觀看，無法更動任何內容，且一切都不是真的。',
    now_none: '等待下一場遊戲。', now_label: '目前', state: { ready: '準備中', running: '進行中', paused: '暫停',
      ended: '已結束' },
    console_t: 'GM 主控台', console_d: '遊戲主持人使用的主控台（唯讀）：盒子、場地平面圖、事件與比分會自動更新。' +
      '若要求輸入權杖，請使用', console_a: '開啟主控台',
    board_t: '計分板', board_d: '場地上的大螢幕：各隊比分與遊戲時鐘。', board_a: '開啟計分板',
    player_t: '玩家視角', player_d: '玩家在手機上看到的內容：隊伍、遊戲、比分，以及隊伍在平面圖上的位置。',
    player_a: '開啟玩家視角',
    site_t: '場地公開頁面', site_d: '場地伺服器上的公開頁面與計分板，顯示同一場遊戲。', site_a: '場地頁面',
    site_b: '公開計分板',
    note1: '遊戲會重複進行：一場結束後接著開始下一場，中間稍作停頓。示範偶爾會自行重新啟動。',
    note2: '一切皆為虛構：場地、代號與比分。本示範不會索取或保存任何訪客的資料。',
    feedback: '告訴我們您的想法'
  }
};
const LANGS = { pt: 'Português', en: 'English', de: 'Deutsch', 'zh-tw': '繁體中文' };

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
let config = { read_token: 'atalaia-demo', site_url: '', site_slug: 'demo-ao-vivo' };
let state = null;

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') e.className = v; else e.setAttribute(k, v);
  }
  for (const kid of kids) e.append(kid);
  return e;
}

function render() {
  const t = TEXTS[lang];
  document.documentElement.lang = lang === 'zh-tw' ? 'zh-TW' : lang;
  document.title = 'Atalaia · ' + t.title;
  document.getElementById('banner').textContent = t.banner;
  document.getElementById('title').textContent = t.title;
  document.getElementById('lead').textContent = t.lead;
  const langs = document.getElementById('langs');
  langs.replaceChildren(...Object.entries(LANGS).map(([code, name]) => {
    const b = el('button', { type: 'button', lang: code === 'zh-tw' ? 'zh-TW' : code }, name);
    if (code === lang) b.setAttribute('aria-current', 'true');
    b.addEventListener('click', () => {
      lang = code;
      try { localStorage.setItem('demo-lang', code); } catch (e) { /* ignore */ }
      render();
    });
    return b;
  }));
  const now = document.getElementById('now');
  now.textContent = state ? `${t.now_label}: ${state.name} (${t.state[state.state] || state.state})` : t.now_none;
  const token = encodeURIComponent(config.read_token);
  const q = '&lang=' + (lang === 'zh-tw' ? 'zh-tw' : lang);
  const cards = [
    card(t.console_t, [t.console_d + ' ', el('code', {}, config.read_token), '.'],
         [link(`/console/#token=${token}${q}`, t.console_a)]),
    card(t.board_t, [t.board_d], [link(`/scoreboard#token=${token}${q}`, t.board_a)]),
    card(t.player_t, [t.player_d], [link(`/player/?lang=${lang}`, t.player_a)]),
  ];
  if (config.site_url) {
    const base = `${config.site_url}/f/${encodeURIComponent(config.site_slug)}`;
    const sl = lang === 'zh-tw' ? 'zh-tw' : lang;
    cards.push(card(t.site_t, [t.site_d], [link(`${base}?lang=${sl}`, t.site_a),
                                           link(`${base}/scoreboard?lang=${sl}`, t.site_b)]));
  }
  document.getElementById('cards').replaceChildren(...cards);
  const notes = [el('p', {}, t.note1), el('p', {}, t.note2)];
  if (config.site_url) notes.push(el('p', {}, el('a', { href: `${config.site_url}/feedback?lang=${lang}` }, t.feedback)));
  document.getElementById('notes').replaceChildren(...notes);
}

function link(href, text) {
  return el('a', { class: 'button', href }, text);
}

function card(title, body, actions) {
  return el('div', { class: 'card' }, el('h2', {}, title), el('p', {}, ...body), el('div', { class: 'actions' }, ...actions));
}

async function refresh() {
  try {
    const r = await fetch('/demo/state.json', { cache: 'no-store' });
    state = r.ok ? await r.json() : null;
  } catch (e) { state = null; }
  render();
}

(async () => {
  try {
    const r = await fetch('/demo/config.json', { cache: 'no-store' });
    if (r.ok) config = await r.json();
  } catch (e) { /* the defaults */ }
  await refresh();
  setInterval(refresh, 10000);
})();
