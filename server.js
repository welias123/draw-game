const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const path = require('path');

const app = express();
const server = http.createServer(app);
const io = new Server(server);

app.use(express.static(path.join(__dirname, 'public')));

const WORDS = [
  'Hund','Katze','Maus','Vogel','Fisch','Pferd','Kuh','Schwein','Schaf',
  'Auto','Bus','Zug','Fahrrad','Flugzeug','Schiff','Rakete','Hubschrauber',
  'Haus','Schloss','Brücke','Turm','Leuchtturm','Iglu','Zelt',
  'Baum','Blume','Pilz','Kaktus','Rose','Sonnenblume',
  'Sonne','Mond','Stern','Wolke','Regenbogen','Blitz','Schnee','Tornado','Vulkan',
  'Pizza','Burger','Sushi','Eis','Kuchen','Banane','Apfel','Wassermelone','Erdbeere',
  'Gitarre','Klavier','Trommel','Mikrofon','Kopfhörer','Geige',
  'Computer','Telefon','Fernseher','Kamera','Roboter','Uhr',
  'Fußball','Basketball','Tennis','Golf','Bowling','Schach','Würfel',
  'Drachen','Einhorn','Pirat','Ninja','Ritter','Astronaut','Zauberer','Mumie','Zombie',
  'Hai','Oktopus','Pinguin','Elefant','Giraffe','Krokodil','Affe','Löwe',
  'Schmetterling','Spinne','Biene','Frosch','Schnecke',
  'Ballon','Geschenk','Kerze','Regenschirm','Hut','Brille','Krone',
  'Berg','Insel','Wasserfall','Höhle','Wüste',
  'Clown','Achterbahn','Trampolin','Schaukel','Karussell',
  'Schere','Schlüssel','Anker','Diamant','Magnet','Lupe'
];

const rooms = new Map();

function randCode() {
  return Math.random().toString(36).slice(2, 8).toUpperCase();
}

function pickWords(n = 3) {
  const arr = [...WORDS];
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr.slice(0, n);
}

function pub(p) {
  return { id: p.id, name: p.name, score: p.score };
}

function snap(room) {
  return {
    code: room.code, host: room.host, state: room.state,
    round: room.round, maxRounds: room.maxRounds,
    currentDrawer: room.currentDrawer,
    wordLength: room.currentWord ? room.currentWord.length : 0,
    players: room.players.map(pub)
  };
}

io.on('connection', socket => {

  socket.on('createRoom', ({ name, rounds }) => {
    const code = randCode();
    rooms.set(code, {
      code, host: socket.id, state: 'waiting',
      players: [{ id: socket.id, name: String(name).trim().slice(0, 16), score: 0 }],
      round: 0, maxRounds: Math.min(Math.max(+rounds || 3, 1), 10),
      drawerIdx: -1, currentDrawer: null, currentWord: null,
      wordChoices: [], guessed: new Set(), timer: null, selectTimer: null
    });
    socket.join(code);
    socket.emit('joined', snap(rooms.get(code)));
  });

  socket.on('joinRoom', ({ name, code }) => {
    code = String(code).toUpperCase().trim();
    const room = rooms.get(code);
    if (!room) return socket.emit('err', 'Raum nicht gefunden.');
    if (room.state !== 'waiting') return socket.emit('err', 'Spiel läuft bereits.');
    if (room.players.length >= 10) return socket.emit('err', 'Raum ist voll (max. 10).');
    room.players.push({ id: socket.id, name: String(name).trim().slice(0, 16), score: 0 });
    socket.join(code);
    socket.emit('joined', snap(room));
    socket.to(code).emit('roomUpdate', snap(room));
  });

  socket.on('startGame', ({ code }) => {
    const room = rooms.get(code);
    if (!room || room.host !== socket.id || room.state !== 'waiting') return;
    if (room.players.length < 2) return socket.emit('err', 'Mindestens 2 Spieler nötig.');
    room.players.forEach(p => p.score = 0);
    room.round = 1;
    room.drawerIdx = -1;
    nextTurn(room);
  });

  socket.on('selectWord', ({ code, word }) => {
    const room = rooms.get(code);
    if (!room || room.currentDrawer !== socket.id || !room.wordChoices.includes(word)) return;
    clearTimeout(room.selectTimer);
    beginDrawing(room, word);
  });

  socket.on('draw', ({ code, stroke }) => {
    const room = rooms.get(code);
    if (!room || room.currentDrawer !== socket.id || room.state !== 'drawing') return;
    socket.to(code).emit('draw', stroke);
  });

  socket.on('clearCanvas', ({ code }) => {
    const room = rooms.get(code);
    if (!room || room.currentDrawer !== socket.id) return;
    io.to(code).emit('clearCanvas');
  });

  socket.on('guess', ({ code, text }) => {
    const room = rooms.get(code);
    if (!room || room.state !== 'drawing') return;
    if (socket.id === room.currentDrawer) return;
    if (room.guessed.has(socket.id)) return;
    const player = room.players.find(p => p.id === socket.id);
    if (!player) return;

    if (text.trim().toLowerCase() === room.currentWord.toLowerCase()) {
      room.guessed.add(socket.id);
      const bonus = Math.max(50, 500 - (room.guessed.size - 1) * 80);
      player.score += bonus;
      const drawer = room.players.find(p => p.id === room.currentDrawer);
      if (drawer) drawer.score += 30;
      io.to(code).emit('correct', { id: socket.id, name: player.name, players: room.players.map(pub) });
      if (room.guessed.size >= room.players.filter(p => p.id !== room.currentDrawer).length) {
        clearInterval(room.timer);
        endTurn(room);
      }
    } else {
      io.to(code).emit('chat', { name: player.name, text: text.trim().slice(0, 80), system: false });
    }
  });

  socket.on('chat', ({ code, text }) => {
    const room = rooms.get(code);
    if (!room || !String(text).trim()) return;
    const player = room.players.find(p => p.id === socket.id);
    if (!player) return;
    if (room.state === 'drawing' && socket.id !== room.currentDrawer && !room.guessed.has(socket.id)) return;
    io.to(code).emit('chat', { name: player.name, text: String(text).trim().slice(0, 80), system: false });
  });

  socket.on('disconnect', () => {
    for (const [code, room] of rooms) {
      const idx = room.players.findIndex(p => p.id === socket.id);
      if (idx === -1) continue;
      const [gone] = room.players.splice(idx, 1);
      io.to(code).emit('chat', { name: gone.name, text: 'hat das Spiel verlassen.', system: true });
      if (room.players.length === 0) {
        clearInterval(room.timer); clearTimeout(room.selectTimer);
        rooms.delete(code); break;
      }
      if (room.host === socket.id) {
        room.host = room.players[0].id;
        io.to(code).emit('newHost', { id: room.host });
      }
      if (room.currentDrawer === socket.id && (room.state === 'drawing' || room.state === 'selecting')) {
        clearInterval(room.timer); clearTimeout(room.selectTimer);
        endTurn(room);
      } else {
        io.to(code).emit('roomUpdate', snap(room));
      }
      break;
    }
  });

  function nextTurn(room) {
    room.drawerIdx++;
    if (room.drawerIdx >= room.players.length) {
      room.drawerIdx = 0;
      room.round++;
    }
    if (room.round > room.maxRounds) { endGame(room); return; }

    room.state = 'selecting';
    room.currentDrawer = room.players[room.drawerIdx].id;
    room.currentWord = null;
    room.guessed = new Set();
    room.wordChoices = pickWords(3);

    io.to(room.code).emit('newTurn', { ...snap(room), drawerName: room.players[room.drawerIdx].name });
    io.to(room.code).emit('clearCanvas');

    const dsock = io.sockets.sockets.get(room.currentDrawer);
    if (dsock) dsock.emit('chooseWord', { words: room.wordChoices });

    room.selectTimer = setTimeout(() => {
      if (room.state === 'selecting') beginDrawing(room, room.wordChoices[0]);
    }, 15000);
  }

  function beginDrawing(room, word) {
    room.currentWord = word;
    room.state = 'drawing';
    const dsock = io.sockets.sockets.get(room.currentDrawer);
    if (dsock) dsock.emit('wordChosen', { word, isDrawer: true });
    const hint = Array.from(word).map(c => c === ' ' ? '/' : '_').join(' ');
    io.to(room.code).except(room.currentDrawer).emit('wordChosen', { hint, wordLength: word.length, isDrawer: false });
    io.to(room.code).emit('gameState', snap(room));

    let t = 80;
    io.to(room.code).emit('tick', t);
    room.timer = setInterval(() => {
      t--;
      io.to(room.code).emit('tick', t);
      if (t <= 0) { clearInterval(room.timer); endTurn(room); }
    }, 1000);
  }

  function endTurn(room) {
    room.state = 'turnEnd';
    io.to(room.code).emit('turnEnd', { word: room.currentWord || '???', players: room.players.map(pub) });
    setTimeout(() => nextTurn(room), 5000);
  }

  function endGame(room) {
    room.state = 'gameEnd';
    const sorted = [...room.players].sort((a, b) => b.score - a.score);
    io.to(room.code).emit('gameEnd', { players: sorted.map(pub) });
    setTimeout(() => {
      room.state = 'waiting'; room.round = 0; room.drawerIdx = -1;
      room.players.forEach(p => p.score = 0);
      io.to(room.code).emit('gameReset', snap(room));
    }, 30000);
  }
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => console.log(`DrawGame läuft auf http://localhost:${PORT}`));
