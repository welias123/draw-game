const socket = io();

// ─── State ────────────────────────────────────────────
let myId = null, myName = '', roomCode = '';
let isHost = false, isDrawer = false, hasGuessed = false;

// ─── Canvas ───────────────────────────────────────────
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
let drawing = false;
let currentColor = '#000000';
let currentSize = 4;
let currentTool = 'pen';
let remote = { on: false, color: '#000', size: 4 };

const PALETTE = [
  '#000000','#3d3d3d','#737373','#b0b0b0','#ffffff',
  '#c0392b','#e74c3c','#e67e22','#f1c40f','#2ecc71',
  '#27ae60','#1abc9c','#3498db','#2980b9','#9b59b6',
  '#8e44ad','#f39c12','#d35400','#795548','#607d8b'
];

function initCanvas() {
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
}

function getPos(e) {
  const r = canvas.getBoundingClientRect();
  const sx = canvas.width / r.width;
  const sy = canvas.height / r.height;
  const src = e.touches ? e.touches[0] : e;
  return { x: (src.clientX - r.left) * sx, y: (src.clientY - r.top) * sy };
}

function startStroke(x, y) {
  const color = currentTool === 'eraser' ? '#ffffff' : currentColor;
  const size  = currentTool === 'eraser' ? currentSize * 3 : currentSize;
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = size;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.moveTo(x, y);
  ctx.lineTo(x, y);
  ctx.stroke();
  return { color, size };
}

canvas.addEventListener('mousedown', e => {
  if (!isDrawer) return;
  const { x, y } = getPos(e);
  if (currentTool === 'fill') {
    floodFill(ctx, Math.round(x), Math.round(y), currentColor);
    socket.emit('draw', { code: roomCode, stroke: { type: 'fill', x: Math.round(x), y: Math.round(y), color: currentColor } });
    return;
  }
  drawing = true;
  const { color, size } = startStroke(x, y);
  socket.emit('draw', { code: roomCode, stroke: { type: 'start', x, y, color, size } });
});

canvas.addEventListener('mousemove', e => {
  if (!drawing || !isDrawer || currentTool === 'fill') return;
  const { x, y } = getPos(e);
  const color = currentTool === 'eraser' ? '#ffffff' : currentColor;
  const size  = currentTool === 'eraser' ? currentSize * 3 : currentSize;
  ctx.strokeStyle = color;
  ctx.lineWidth = size;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.lineTo(x, y);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x, y);
  socket.emit('draw', { code: roomCode, stroke: { type: 'move', x, y } });
});

canvas.addEventListener('mouseup', endStroke);
canvas.addEventListener('mouseleave', endStroke);

canvas.addEventListener('touchstart', e => { e.preventDefault(); if (!isDrawer) return; const { x, y } = getPos(e); if (currentTool === 'fill') { floodFill(ctx, Math.round(x), Math.round(y), currentColor); socket.emit('draw', { code: roomCode, stroke: { type: 'fill', x: Math.round(x), y: Math.round(y), color: currentColor } }); return; } drawing = true; const { color, size } = startStroke(x, y); socket.emit('draw', { code: roomCode, stroke: { type: 'start', x, y, color, size } }); }, { passive: false });
canvas.addEventListener('touchmove', e => { e.preventDefault(); if (!drawing || !isDrawer || currentTool === 'fill') return; const { x, y } = getPos(e); const color = currentTool === 'eraser' ? '#ffffff' : currentColor; const size = currentTool === 'eraser' ? currentSize * 3 : currentSize; ctx.strokeStyle = color; ctx.lineWidth = size; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.lineTo(x, y); ctx.stroke(); ctx.beginPath(); ctx.moveTo(x, y); socket.emit('draw', { code: roomCode, stroke: { type: 'move', x, y } }); }, { passive: false });
canvas.addEventListener('touchend', endStroke);

function endStroke() {
  if (!drawing) return;
  drawing = false;
  socket.emit('draw', { code: roomCode, stroke: { type: 'end' } });
}

function applyStroke(stroke) {
  switch (stroke.type) {
    case 'start':
      remote = { on: true, color: stroke.color, size: stroke.size };
      ctx.beginPath();
      ctx.strokeStyle = stroke.color;
      ctx.lineWidth = stroke.size;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.moveTo(stroke.x, stroke.y);
      ctx.lineTo(stroke.x, stroke.y);
      ctx.stroke();
      break;
    case 'move':
      if (!remote.on) break;
      ctx.strokeStyle = remote.color;
      ctx.lineWidth = remote.size;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.lineTo(stroke.x, stroke.y);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(stroke.x, stroke.y);
      break;
    case 'end':
      remote.on = false;
      break;
    case 'fill':
      floodFill(ctx, stroke.x, stroke.y, stroke.color);
      break;
  }
}

function floodFill(ctx, sx, sy, fillColor) {
  const { width, height } = ctx.canvas;
  if (sx < 0 || sx >= width || sy < 0 || sy >= height) return;
  const img = ctx.getImageData(0, 0, width, height);
  const d = img.data;
  const si = (sy * width + sx) * 4;
  const [tr, tg, tb, ta] = [d[si], d[si+1], d[si+2], d[si+3]];

  const tmp = document.createElement('canvas');
  tmp.width = tmp.height = 1;
  const tc = tmp.getContext('2d');
  tc.fillStyle = fillColor;
  tc.fillRect(0, 0, 1, 1);
  const [fr, fg, fb] = tc.getImageData(0, 0, 1, 1).data;
  if (tr === fr && tg === fg && tb === fb) return;

  const tol = 30;
  function match(i) {
    return Math.abs(d[i]-tr) <= tol && Math.abs(d[i+1]-tg) <= tol &&
           Math.abs(d[i+2]-tb) <= tol && Math.abs(d[i+3]-ta) <= tol;
  }

  const visited = new Uint8Array(width * height);
  const queue = [sx + sy * width];
  visited[sx + sy * width] = 1;

  while (queue.length) {
    const pos = queue.pop();
    const x = pos % width, y = (pos - x) / width;
    const i = pos * 4;
    d[i] = fr; d[i+1] = fg; d[i+2] = fb; d[i+3] = 255;
    for (const n of [pos-1, pos+1, pos-width, pos+width]) {
      if (n < 0 || n >= width * height || visited[n]) continue;
      if (Math.abs((n % width) - x) > 1) continue;
      if (match(n * 4)) { visited[n] = 1; queue.push(n); }
    }
  }
  ctx.putImageData(img, 0, 0);
}

// ─── Screen Management ────────────────────────────────
function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

function hideAllOverlays() {
  ['wordSelectOverlay','turnEndOverlay','gameEndOverlay'].forEach(id => {
    document.getElementById(id).classList.add('hidden');
  });
}

// ─── Lobby UI ─────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab + 'Tab').classList.add('active');
  });
});

document.getElementById('roundSlider').addEventListener('input', e => {
  document.getElementById('roundVal').textContent = e.target.value;
});

function getNameInput() {
  const n = document.getElementById('nameInput').value.trim();
  if (!n) { showLobbyError('Bitte gib einen Namen ein.'); return null; }
  return n;
}
function showLobbyError(msg) {
  document.getElementById('lobbyError').textContent = msg;
  setTimeout(() => document.getElementById('lobbyError').textContent = '', 3000);
}

document.getElementById('createBtn').addEventListener('click', () => {
  const name = getNameInput();
  if (!name) return;
  myName = name;
  socket.emit('createRoom', { name, rounds: +document.getElementById('roundSlider').value });
});

document.getElementById('joinBtn').addEventListener('click', () => {
  const name = getNameInput();
  if (!name) return;
  const code = document.getElementById('codeInput').value.trim();
  if (!code) { showLobbyError('Bitte gib einen Raum-Code ein.'); return; }
  myName = name;
  socket.emit('joinRoom', { name, code });
});

document.getElementById('codeInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('joinBtn').click();
});
document.getElementById('nameInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    const active = document.querySelector('.tab-btn.active').dataset.tab;
    document.getElementById(active === 'create' ? 'createBtn' : 'joinBtn').click();
  }
});

// ─── Waiting Room UI ──────────────────────────────────
function renderWaitingRoom(room) {
  roomCode = room.code;
  isHost = room.host === myId;
  document.getElementById('waitCode').textContent = room.code;
  const list = document.getElementById('waitingPlayers');
  list.innerHTML = '';
  room.players.forEach(p => {
    const li = document.createElement('li');
    li.className = 'waiting-player';
    li.innerHTML = `
      <div class="player-avatar" style="background:${avatarColor(p.name)}">${p.name[0].toUpperCase()}</div>
      <span class="player-name">${esc(p.name)}</span>
      ${room.host === p.id ? '<span class="host-badge">Host</span>' : ''}
    `;
    list.appendChild(li);
  });
  const hint = document.getElementById('waitHint');
  const startBtn = document.getElementById('startBtn');
  if (isHost) {
    startBtn.classList.remove('hidden');
    hint.textContent = room.players.length < 2 ? 'Mindestens 2 Spieler nötig' : `${room.players.length} Spieler bereit`;
    startBtn.disabled = room.players.length < 2;
  } else {
    startBtn.classList.add('hidden');
    hint.textContent = 'Warte auf den Host…';
  }
}

document.getElementById('copyBtn').addEventListener('click', () => {
  const url = `${location.origin}/?join=${roomCode}`;
  navigator.clipboard.writeText(url).then(() => {
    document.getElementById('copyBtn').textContent = '✅ Kopiert!';
    setTimeout(() => document.getElementById('copyBtn').textContent = '📋 Link kopieren', 2000);
  });
});

document.getElementById('startBtn').addEventListener('click', () => {
  socket.emit('startGame', { code: roomCode });
});

document.getElementById('playAgainBtn').addEventListener('click', () => {
  socket.emit('playAgain', { code: roomCode });
});

// ─── Auto-join from URL ───────────────────────────────
window.addEventListener('load', () => {
  const params = new URLSearchParams(location.search);
  const joinCode = params.get('join');
  if (joinCode) {
    document.getElementById('codeInput').value = joinCode.toUpperCase();
    document.querySelector('[data-tab="join"]').click();
  }
});

// ─── Game UI ──────────────────────────────────────────
function renderPlayers(players, drawer, guessed) {
  const list = document.getElementById('playersList');
  list.innerHTML = '';
  players.forEach(p => {
    const isDrawing = p.id === drawer;
    const didGuess = guessed && guessed.has(p.id);
    const div = document.createElement('div');
    div.className = `player-item${isDrawing ? ' drawing' : ''}${didGuess ? ' guessed' : ''}`;
    div.innerHTML = `
      <div class="player-avatar sm" style="background:${avatarColor(p.name)}">${p.name[0].toUpperCase()}</div>
      <div class="player-info">
        <div class="pname">${esc(p.name)}</div>
        <div class="pscore">${p.score} Pkt</div>
      </div>
      <span class="player-icon">${isDrawing ? '✏️' : didGuess ? '✅' : ''}</span>
    `;
    list.appendChild(div);
  });
}

let guessedSet = new Set();

function addChat(name, text, type) {
  const log = document.getElementById('chatLog');
  const div = document.createElement('div');
  div.className = `chat-msg ${type || ''}`;
  const color = avatarColor(name);
  if (type === 'correct') {
    div.innerHTML = `<span style="color:${color}">✓</span> <strong style="color:${color}">${esc(name)}</strong> hat es erraten!`;
  } else if (type === 'system') {
    div.textContent = `${name} ${text}`;
  } else {
    div.innerHTML = `<span class="chat-name" style="color:${color}">${esc(name)}:</span> ${esc(text)}`;
  }
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function updateTimer(t) {
  const el = document.getElementById('timerDisplay');
  el.textContent = t;
  el.classList.toggle('urgent', t <= 15);
}

// ─── Tools Panel ─────────────────────────────────────
const colorGrid = document.getElementById('colorGrid');
PALETTE.forEach(c => {
  const sw = document.createElement('div');
  sw.className = 'color-swatch' + (c === '#000000' ? ' active' : '');
  sw.style.background = c;
  sw.addEventListener('click', () => {
    document.querySelectorAll('.color-swatch').forEach(s => s.classList.remove('active'));
    sw.classList.add('active');
    currentColor = c;
    document.getElementById('customColor').value = c;
  });
  colorGrid.appendChild(sw);
});

document.getElementById('customColor').addEventListener('input', e => {
  currentColor = e.target.value;
  document.querySelectorAll('.color-swatch').forEach(s => s.classList.remove('active'));
});

document.querySelectorAll('.size-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.size-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentSize = +btn.dataset.size;
  });
});

document.querySelectorAll('.tool-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentTool = btn.dataset.tool;
    canvas.classList.toggle('no-draw', currentTool === 'fill');
  });
});

document.getElementById('clearBtn').addEventListener('click', () => {
  if (!isDrawer) return;
  socket.emit('clearCanvas', { code: roomCode });
});

// ─── Chat / Guess ─────────────────────────────────────
document.getElementById('chatForm').addEventListener('submit', e => {
  e.preventDefault();
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  if (isDrawer || hasGuessed) {
    socket.emit('chat', { code: roomCode, text });
  } else {
    socket.emit('guess', { code: roomCode, text });
  }
});

// ─── Socket Events ────────────────────────────────────
socket.on('connect', () => { myId = socket.id; });

socket.on('err', msg => {
  showLobbyError(msg);
  document.getElementById('waitError').textContent = msg;
  setTimeout(() => document.getElementById('waitError').textContent = '', 3000);
});

socket.on('joined', room => {
  renderWaitingRoom(room);
  showScreen('waitingScreen');
});

socket.on('roomUpdate', room => {
  renderWaitingRoom(room);
});

socket.on('newHost', ({ id }) => {
  isHost = id === myId;
});

socket.on('playerJoined', room => {
  renderWaitingRoom(room);
});

socket.on('newTurn', data => {
  isDrawer = data.currentDrawer === myId;
  hasGuessed = false;
  guessedSet = new Set();
  hideAllOverlays();
  document.getElementById('roundBadge').textContent = `Runde ${data.round}/${data.maxRounds}`;
  document.getElementById('wordDisplay').textContent = isDrawer ? '…wähle ein Wort' : `${data.drawerName} zeichnet`;
  document.getElementById('toolsPanel').classList.toggle('hidden', !isDrawer);
  canvas.classList.toggle('drawing-active', isDrawer);
  document.getElementById('chatInput').disabled = false;
  document.getElementById('chatInput').placeholder = isDrawer ? 'Chat…' : 'Antwort eingeben…';
  canvas.classList.toggle('no-draw', !isDrawer);
  renderPlayers(data.players, data.currentDrawer, guessedSet);
  document.getElementById('chatLog').innerHTML = '';
  document.getElementById('timerDisplay').textContent = '—';
  showScreen('gameScreen');
});

socket.on('chooseWord', ({ words }) => {
  const overlay = document.getElementById('wordSelectOverlay');
  const cards = document.getElementById('wordCards');
  cards.innerHTML = '';
  words.forEach(w => {
    const btn = document.createElement('button');
    btn.className = 'word-card';
    btn.textContent = w;
    btn.addEventListener('click', () => {
      overlay.classList.add('hidden');
      socket.emit('selectWord', { code: roomCode, word: w });
    });
    cards.appendChild(btn);
  });
  overlay.classList.remove('hidden');
});

socket.on('wordChosen', ({ word, hint, isDrawer: iAm }) => {
  document.getElementById('wordSelectOverlay').classList.add('hidden');
  if (iAm) {
    document.getElementById('wordDisplay').textContent = word;
  } else {
    document.getElementById('wordDisplay').textContent = hint;
    document.getElementById('wordDisplay').style.letterSpacing = '8px';
  }
});

socket.on('gameState', data => {
  renderPlayers(data.players, data.currentDrawer, guessedSet);
});

socket.on('draw', stroke => applyStroke(stroke));

socket.on('clearCanvas', () => {
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
});

socket.on('tick', t => updateTimer(t));

socket.on('correct', ({ id, name, players }) => {
  guessedSet.add(id);
  if (id === myId) {
    hasGuessed = true;
    document.getElementById('chatInput').placeholder = 'Du hast erraten! Jetzt chatten…';
  }
  addChat(name, '', 'correct');
  renderPlayers(players, null, guessedSet);
});

socket.on('chat', ({ name, text, system }) => {
  addChat(name, text, system ? 'system' : '');
});

socket.on('playerLeft', ({ name, players }) => {
  renderPlayers(players, null, guessedSet);
  addChat(name, 'hat das Spiel verlassen.', 'system');
});

socket.on('turnEnd', ({ word, players }) => {
  document.getElementById('revealWord').textContent = word;
  const scoreList = document.getElementById('turnScores');
  scoreList.innerHTML = '';
  [...players].sort((a,b) => b.score - a.score).forEach(p => {
    const row = document.createElement('div');
    row.className = 'score-row';
    row.innerHTML = `<span>${esc(p.name)}</span><span class="pts">${p.score} Pkt</span>`;
    scoreList.appendChild(row);
  });
  document.getElementById('turnEndOverlay').classList.remove('hidden');
  document.getElementById('toolsPanel').classList.add('hidden');
  document.getElementById('timerDisplay').textContent = '—';
});

socket.on('gameEnd', ({ players }) => {
  document.getElementById('turnEndOverlay').classList.add('hidden');
  const podium = document.getElementById('podium');
  podium.innerHTML = '';
  const medals = ['🥇','🥈','🥉'];
  players.forEach((p, i) => {
    const row = document.createElement('div');
    row.className = 'podium-row';
    row.innerHTML = `
      <span class="podium-rank">${medals[i] || (i+1)+'.'}</span>
      <span class="podium-name">${esc(p.name)}</span>
      <span class="podium-score">${p.score} Pkt</span>
    `;
    podium.appendChild(row);
  });
  document.getElementById('gameEndOverlay').classList.remove('hidden');
});

socket.on('gameReset', room => {
  hideAllOverlays();
  initCanvas();
  renderWaitingRoom(room);
  showScreen('waitingScreen');
});

// ─── Helpers ──────────────────────────────────────────
function esc(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function avatarColor(name) {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) & 0x7fffffff;
  const hues = [150,170,190,210,230,250,270,290,310,40,60,80,100,120];
  return `hsl(${hues[h % hues.length]}, 72%, 54%)`;
}

// Initialize
initCanvas();
