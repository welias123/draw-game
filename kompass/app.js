/* Kompass Tagesplaner: Aufgaben, Fokus-Timer, Gewohnheiten, Notizen.
   Alles wird lokal im Browser gespeichert (localStorage). */
(() => {
  'use strict';

  const STORE_KEY = 'kompass.v1';
  const VIEWS = ['heute', 'aufgaben', 'fokus', 'gewohnheiten', 'notizen', 'einstellungen'];
  const PRIO_ORDER = { hoch: 0, mittel: 1, niedrig: 2 };
  const PRIO_LABEL = { hoch: 'Hoch', mittel: 'Mittel', niedrig: 'Niedrig' };
  const MODE_LABEL = { focus: 'Fokus', short: 'Kurze Pause', long: 'Lange Pause' };
  const WIN_ID = Math.random().toString(36).slice(2);
  const LATE_MS = 60 * 1000;

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const CHECK_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
  const TRASH_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>';

  /* ── Datum ─────────────────────────────────────────────── */
  const pad = (n) => String(n).padStart(2, '0');
  const ymd = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const parseYmd = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
  const addDays = (s, n) => { const d = parseYmd(s); d.setDate(d.getDate() + n); return ymd(d); };
  const dayDiff = (a, b) => {
    const [ay, am, ad] = a.split('-').map(Number);
    const [by, bm, bd] = b.split('-').map(Number);
    return Math.round((Date.UTC(by, bm - 1, bd) - Date.UTC(ay, am - 1, ad)) / 86400000);
  };
  const isoWeek = (date) => {
    const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    const day = d.getUTCDay() || 7;
    d.setUTCDate(d.getUTCDate() + 4 - day);
    const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    return Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
  };
  const fmtLong = new Intl.DateTimeFormat('de-DE', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  const fmtShort = new Intl.DateTimeFormat('de-DE', { weekday: 'short', day: 'numeric', month: 'short' });
  const fmtWeekday = new Intl.DateTimeFormat('de-DE', { weekday: 'long' });
  const fmtWd2 = new Intl.DateTimeFormat('de-DE', { weekday: 'short' });
  const fmtStamp = new Intl.DateTimeFormat('de-DE', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  const wd2 = (s) => fmtWd2.format(parseYmd(s)).replace('.', '');

  function dueInfo(due, today) {
    if (!due) return null;
    const diff = dayDiff(today, due);
    if (diff < 0) {
      const n = -diff;
      return { cls: 'due-overdue', text: n === 1 ? 'seit gestern fällig' : `seit ${n} Tagen fällig` };
    }
    if (diff === 0) return { cls: 'due-today', text: 'heute' };
    if (diff === 1) return { cls: '', text: 'morgen' };
    if (diff < 7) return { cls: '', text: fmtWeekday.format(parseYmd(due)) };
    return { cls: '', text: fmtShort.format(parseYmd(due)) };
  }

  /* ── Speicher ──────────────────────────────────────────── */
  const memoryStore = {};
  const store = {
    get(key) { try { return localStorage.getItem(key); } catch { return memoryStore[key] ?? null; } },
    set(key, val) { try { localStorage.setItem(key, val); } catch { memoryStore[key] = val; } },
  };

  function defaults() {
    return {
      version: 1,
      tasks: [],
      habits: [],
      notes: [],
      focus: {
        sessions: {},   // endsAt -> { d: 'YYYY-MM-DD', m: Minuten, t: taskId }
        demo: {},       // Beispiel-Minuten pro Tag
        settings: { focus: 25, short: 5, long: 15, rounds: 4, sound: true, auto: false },
        timer: { mode: 'focus', running: false, endsAt: 0, remaining: 25 * 60000, total: 25 * 60000, round: 1, taskId: '', owner: '' },
      },
      prefs: { theme: 'system', filter: 'offen', noteId: '', scratch: '', seeded: false },
    };
  }

  function normalize(raw) {
    const d = defaults();
    if (!raw || typeof raw !== 'object') return d;
    const arr = (v) => (Array.isArray(v) ? v.filter((x) => x && typeof x === 'object' && x.id) : []);
    const f = raw.focus && typeof raw.focus === 'object' ? raw.focus : {};
    return {
      version: 1,
      tasks: arr(raw.tasks),
      habits: arr(raw.habits).map((h) => ({ ...h, days: h.days && typeof h.days === 'object' ? h.days : {} })),
      notes: arr(raw.notes),
      focus: {
        sessions: f.sessions && typeof f.sessions === 'object' ? f.sessions : {},
        demo: f.demo && typeof f.demo === 'object' ? f.demo : {},
        settings: { ...d.focus.settings, ...(f.settings || {}) },
        timer: { ...d.focus.timer, ...(f.timer || {}) },
      },
      prefs: { ...d.prefs, ...(raw.prefs || {}) },
    };
  }

  function loadState() {
    const txt = store.get(STORE_KEY);
    if (!txt) return null;
    try { return normalize(JSON.parse(txt)); } catch { return null; }
  }

  let state = loadState();
  if (!state) { state = defaults(); seedExamples(state); }

  let saveTimer = 0;
  function save(now = false) {
    clearTimeout(saveTimer);
    const write = () => store.set(STORE_KEY, JSON.stringify(state));
    if (now) write(); else saveTimer = setTimeout(write, 150);
  }

  function seedExamples(s) {
    const t = ymd();
    const now = Date.now();
    const task = (title, due, prio, extra = {}) => ({ id: uid(), title, due, prio, done: false, created: now, doneAt: 0, ex: true, ...extra });
    s.tasks = [
      task('Arzttermin vereinbaren', addDays(t, -1), 'mittel'),
      task('Präsentation fertig machen', t, 'hoch'),
      task('Wäsche waschen', t, 'niedrig'),
      task('Mathe: Übungsblatt 3 abgeben', addDays(t, 1), 'hoch'),
      task('Geschenk für Lenas Geburtstag besorgen', addDays(t, 4), 'mittel'),
      task('Neues Rezept ausprobieren', '', 'niedrig'),
      task('Kompass ausprobieren', t, 'mittel', { done: true, doneAt: now }),
    ];
    const days = (...offsets) => Object.fromEntries(offsets.map((o) => [addDays(t, o), 1]));
    s.habits = [
      { id: uid(), name: '10 Minuten lesen', days: days(-1, -2, -4, -5), created: now, ex: true },
      { id: uid(), name: '2 Liter Wasser trinken', days: days(0, -1, -2, -3, -5, -6), created: now, ex: true },
      { id: uid(), name: 'Kurzer Spaziergang', days: days(-2, -3), created: now, ex: true },
    ];
    s.notes = [
      {
        id: uid(), title: 'Willkommen bei Kompass', created: now, updated: now, ex: true,
        body: 'Kompass hilft dir, den Tag im Griff zu behalten.\n\n'
          + 'Heute: Überblick über alles, was ansteht, plus ein Notizzettel für schnelle Gedanken.\n'
          + 'Aufgaben: mit Fälligkeitsdatum und Wichtigkeit. Doppelklick auf eine Aufgabe, um sie umzubenennen.\n'
          + 'Fokus: 25 Minuten konzentriert arbeiten, dann 5 Minuten Pause. Nach 4 Runden gibt es eine lange Pause.\n'
          + 'Gewohnheiten: jeden Tag abhaken und die Serie wachsen lassen.\n'
          + 'Notizen: speichern automatisch beim Tippen.\n\n'
          + 'Deine Daten bleiben nur in diesem Browser. Unter Einstellungen kannst du eine Sicherung herunterladen.',
      },
      { id: uid(), title: 'Einkaufsliste', created: now - 3600e3, updated: now - 3600e3, ex: true, body: '- Milch\n- Haferflocken\n- Äpfel\n- Vollkornbrot\n- Nudeln\n- Tomaten' },
      { id: uid(), title: 'Ideen fürs Wochenende', created: now - 86400e3, updated: now - 86400e3, ex: true, body: 'Fahrradtour zum See\nFilmabend mit Popcorn\nFlohmarkt am Samstag ab 9 Uhr' },
    ];
    s.focus.demo = { [addDays(t, -6)]: 50, [addDays(t, -5)]: 25, [addDays(t, -4)]: 75, [addDays(t, -2)]: 100, [addDays(t, -1)]: 50 };
    s.prefs.noteId = s.notes[0].id;
    s.prefs.scratch = 'Beispiel: Oma anrufen, Nummer 030 1234567';
    s.prefs.seeded = true;
  }

  const hasExamples = () =>
    state.tasks.some((x) => x.ex) || state.habits.some((x) => x.ex) || state.notes.some((x) => x.ex) || Object.keys(state.focus.demo).length > 0;

  function clearExamples() {
    state.tasks = state.tasks.filter((x) => !x.ex);
    state.habits = state.habits.filter((x) => !x.ex);
    state.notes = state.notes.filter((x) => !x.ex);
    state.focus.demo = {};
    if (state.prefs.scratch.startsWith('Beispiel:')) state.prefs.scratch = '';
    if (!state.notes.some((n) => n.id === state.prefs.noteId)) state.prefs.noteId = state.notes[0]?.id || '';
    save(true);
    renderAll();
    toast('Beispiele entfernt. Jetzt gehört Kompass dir.');
  }

  /* ── Toast ─────────────────────────────────────────────── */
  let toastTimer = 0;
  function toast(msg, undo) {
    const el = $('#toast');
    el.innerHTML = `<span>${esc(msg)}</span>${undo ? '<button type="button">Rückgängig</button>' : ''}`;
    el.hidden = false;
    if (undo) $('button', el).onclick = () => { undo(); el.hidden = true; };
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, undo ? 6000 : 3200);
  }

  /* ── Navigation ────────────────────────────────────────── */
  let currentView = 'heute';
  function showView(name) {
    if (!VIEWS.includes(name)) name = 'heute';
    currentView = name;
    $$('.view').forEach((v) => { v.hidden = v.dataset.view !== name; });
    $$('.tab').forEach((t) => {
      if (t.dataset.view === name) t.setAttribute('aria-current', 'page');
      else t.removeAttribute('aria-current');
    });
    if (name === 'notizen') renderNotes();
    window.scrollTo(0, 0);
  }
  const route = () => showView((location.hash || '#heute').slice(1));
  window.addEventListener('hashchange', route);
  const go = (name) => {
    if (location.hash !== '#' + name) location.hash = name; else showView(name);
  };

  /* ── Theme ─────────────────────────────────────────────── */
  const hostTheme = document.documentElement.getAttribute('data-theme');
  function applyTheme() {
    const root = document.documentElement;
    const choice = state.prefs.theme;
    if (choice === 'light' || choice === 'dark') root.setAttribute('data-theme', choice);
    else if (hostTheme) root.setAttribute('data-theme', hostTheme);
    else root.removeAttribute('data-theme');
    $$('[data-theme-choice]').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.themeChoice === choice)));
    const meta = $('meta[name="theme-color"]');
    if (meta) meta.content = getComputedStyle(root).getPropertyValue('--surface').trim() || '#2447B3';
  }

  /* ── Aufgaben ──────────────────────────────────────────── */
  const taskSort = (a, b) =>
    (PRIO_ORDER[a.prio] ?? 1) - (PRIO_ORDER[b.prio] ?? 1)
    || (a.due || '9999').localeCompare(b.due || '9999')
    || a.created - b.created;

  function addTask(title, due, prio) {
    title = title.trim();
    if (!title) return;
    state.tasks.push({ id: uid(), title, due: due || '', prio: prio || 'mittel', done: false, created: Date.now(), doneAt: 0 });
    save();
    renderAll();
  }

  function toggleTask(id) {
    const t = state.tasks.find((x) => x.id === id);
    if (!t) return;
    t.done = !t.done;
    t.doneAt = t.done ? Date.now() : 0;
    save();
    renderAll();
  }

  function deleteTask(id) {
    const i = state.tasks.findIndex((x) => x.id === id);
    if (i < 0) return;
    const [removed] = state.tasks.splice(i, 1);
    if (state.focus.timer.taskId === id) state.focus.timer.taskId = '';
    save();
    renderAll();
    toast(`„${removed.title}“ gelöscht.`, () => { state.tasks.splice(i, 0, removed); save(); renderAll(); });
  }

  function focusMinutesForTask(id) {
    let m = 0;
    for (const s of Object.values(state.focus.sessions)) if (s.t === id) m += s.m;
    return m;
  }

  function taskItem(t, today, { compact = false } = {}) {
    const due = dueInfo(t.done ? '' : t.due, today);
    const fm = focusMinutesForTask(t.id);
    const chips = [
      due ? `<span class="chip ${due.cls}">${esc(due.text)}</span>` : '',
      !compact || t.prio === 'hoch' ? `<span class="chip prio-${esc(t.prio)}">${PRIO_LABEL[t.prio] || 'Mittel'}</span>` : '',
      fm ? `<span class="chip">${fm} min Fokus</span>` : '',
      t.ex ? '<span class="chip example">Beispiel</span>' : '',
    ].join('');
    return `<li class="task${t.done ? ' is-done' : ''}" data-id="${esc(t.id)}">
      <button type="button" class="tick" role="checkbox" aria-checked="${t.done}" data-action="task-toggle" aria-label="${t.done ? 'Wieder öffnen' : 'Erledigt'}: ${esc(t.title)}">${CHECK_SVG}</button>
      <div class="task-body">
        <span class="task-title" data-action="task-edit" title="Doppelklick zum Umbenennen">${esc(t.title)}</span>
        ${chips ? `<span class="task-meta">${chips}</span>` : ''}
      </div>
      <button type="button" class="icon-btn" data-action="task-delete" aria-label="Löschen: ${esc(t.title)}" title="Löschen">${TRASH_SVG}</button>
    </li>`;
  }

  function renderTasks() {
    const today = ymd();
    const open = state.tasks.filter((t) => !t.done);
    const done = state.tasks.filter((t) => t.done).sort((a, b) => b.doneAt - a.doneAt);
    const overdue = open.filter((t) => t.due && t.due < today).length;
    $('#taskSummary').textContent = `${open.length} offen · ${done.length} erledigt${overdue ? ` · ${overdue} überfällig` : ''}`;

    const filter = state.prefs.filter;
    $$('[data-filter]').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.filter === filter)));
    $('#clearDoneBtn').hidden = done.length === 0;

    const groups = [];
    if (filter !== 'erledigt') {
      const tomorrow = addDays(today, 1);
      const g = { overdue: [], today: [], tomorrow: [], later: [], none: [] };
      for (const t of open) {
        if (!t.due) g.none.push(t);
        else if (t.due < today) g.overdue.push(t);
        else if (t.due === today) g.today.push(t);
        else if (t.due === tomorrow) g.tomorrow.push(t);
        else g.later.push(t);
      }
      g.later.sort((a, b) => a.due.localeCompare(b.due) || taskSort(a, b));
      groups.push(
        { key: 'overdue', label: 'Überfällig', items: g.overdue.sort(taskSort), action: g.overdue.length ? '<button type="button" class="btn btn-ghost btn-small" data-action="overdue-today">Alle auf heute verschieben</button>' : '' },
        { key: 'today', label: 'Heute', items: g.today.sort(taskSort) },
        { key: 'tomorrow', label: 'Morgen', items: g.tomorrow.sort(taskSort) },
        { key: 'later', label: 'Demnächst', items: g.later },
        { key: 'none', label: 'Ohne Datum', items: g.none.sort(taskSort) },
      );
    }
    if (filter !== 'offen') groups.push({ key: 'done', label: 'Erledigt', items: done });

    const html = groups
      .filter((g) => g.items.length)
      .map((g) => `<section class="task-group is-${g.key}">
          <h3><span class="label">${g.label}</span><span class="n">${g.items.length}</span>${g.action || ''}</h3>
          <ul class="task-list">${g.items.map((t) => taskItem(t, today)).join('')}</ul>
        </section>`)
      .join('');
    $('#taskGroups').innerHTML = html || `<p class="empty">${filter === 'erledigt' ? 'Noch nichts erledigt. Das kommt noch.' : 'Alles erledigt. Zeit für eine Pause.'}</p>`;

    const badge = $('#tabCountTasks');
    const dueNow = open.filter((t) => t.due && t.due <= today).length;
    badge.textContent = dueNow;
    badge.hidden = dueNow === 0;
  }

  /* ── Heute ─────────────────────────────────────────────── */
  function greeting() {
    const h = new Date().getHours();
    if (h < 5) return 'Gute Nacht';
    if (h < 11) return 'Guten Morgen';
    if (h < 14) return 'Mahlzeit';
    if (h < 18) return 'Guten Tag';
    return 'Guten Abend';
  }

  function focusDay(d) {
    let m = state.focus.demo[d] || 0;
    let n = Math.round((state.focus.demo[d] || 0) / 25);
    for (const s of Object.values(state.focus.sessions)) if (s.d === d) { m += s.m; n += 1; }
    return { m, n };
  }

  function habitStreak(h, today) {
    let d = h.days[today] ? today : addDays(today, -1);
    let n = 0;
    while (h.days[d]) { n++; d = addDays(d, -1); }
    return n;
  }

  function renderToday() {
    const now = new Date();
    const today = ymd(now);
    $('#greeting').textContent = greeting() + '!';
    $('#todayMeta').textContent = `${fmtLong.format(now)} · KW ${isoWeek(now)}`;
    $('#exampleBanner').hidden = !hasExamples();

    const list = state.tasks.filter((t) => t.due && t.due <= today && (!t.done || t.due === today || (t.doneAt && ymd(new Date(t.doneAt)) === today)));
    // Überfälliges zuerst, dann nach Wichtigkeit
    const openFirst = list.filter((t) => !t.done).sort((a, b) => (b.due < today) - (a.due < today) || taskSort(a, b));
    const doneToday = list.filter((t) => t.done);
    const shown = [...openFirst, ...doneToday];
    $('#todayTasks').innerHTML = shown.length
      ? shown.map((t) => taskItem(t, today, { compact: true })).join('')
      : '<li class="list-empty">Für heute ist nichts geplant. Oben kannst du etwas eintragen.</li>';
    $('#todayTaskMeta').textContent = shown.length ? `${doneToday.length} von ${shown.length} erledigt` : '';

    // Fokus: 7-Tage-Balken
    const f = focusDay(today);
    $('#focusTodayMin').textContent = f.m;
    $('#focusTodaySessions').textContent = f.n === 1 ? '1 Einheit' : `${f.n} Einheiten`;
    const days = Array.from({ length: 7 }, (_, i) => addDays(today, i - 6));
    const vals = days.map((d) => focusDay(d).m);
    const max = Math.max(60, ...vals);
    $('#weekChart').innerHTML = days.map((d, i) => `<div class="week-bar${d === today ? ' is-today' : ''}">
        <span class="val">${vals[i] || ''}</span>
        <span class="bar" style="height:${Math.max(3, Math.round((vals[i] / max) * 78))}px"></span>
        <span class="day">${wd2(d)}</span>
      </div>`).join('');
    $('#weekChart').setAttribute('aria-label', 'Fokus-Minuten der letzten 7 Tage: ' + days.map((d, i) => `${wd2(d)} ${vals[i]}`).join(', '));
    const tm = state.focus.timer;
    $('#focusCta').textContent = tm.running ? 'Zum laufenden Timer' : 'Fokus starten';

    // Gewohnheiten heute
    const habits = state.habits;
    const doneCount = habits.filter((h) => h.days[today]).length;
    $('#todayHabitMeta').textContent = habits.length ? `${doneCount} von ${habits.length}` : '';
    $('#todayHabits').innerHTML = habits.length
      ? habits.map((h) => {
          const on = !!h.days[today];
          const st = habitStreak(h, today);
          return `<li data-id="${esc(h.id)}">
            <button type="button" class="tick round" role="checkbox" aria-checked="${on}" data-action="habit-toggle" data-day="${today}" aria-label="${esc(h.name)} heute">${CHECK_SVG}</button>
            <span class="name">${esc(h.name)}</span>
            <span class="streak">${st ? `${st} ${st === 1 ? 'Tag' : 'Tage'} Serie` : ''}</span>
          </li>`;
        }).join('')
      : '<li class="list-empty">Noch keine Gewohnheiten angelegt.</li>';

    const scratch = $('#scratch');
    if (document.activeElement !== scratch) scratch.value = state.prefs.scratch;
  }

  /* ── Gewohnheiten ──────────────────────────────────────── */
  function renderHabits() {
    const today = ymd();
    const days = Array.from({ length: 7 }, (_, i) => addDays(today, i - 6));
    $('#habitHead').innerHTML = '<th class="h-name">Gewohnheit</th>'
      + days.map((d) => {
          const dt = parseYmd(d);
          return `<th class="${d === today ? 'is-today' : ''}">${wd2(d)}<span class="d">${dt.getDate()}.${dt.getMonth() + 1}.</span></th>`;
        }).join('')
      + '<th>Serie</th><th><span class="sr-only">Löschen</span></th>';
    $('#habitBody').innerHTML = state.habits.map((h) => {
      const st = habitStreak(h, today);
      return `<tr data-id="${esc(h.id)}">
        <td class="h-name">${esc(h.name)}${h.ex ? ' <span class="chip example">Beispiel</span>' : ''}</td>
        ${days.map((d) => `<td><button type="button" class="tick round" role="checkbox" aria-checked="${!!h.days[d]}" data-action="habit-toggle" data-day="${d}" aria-label="${esc(h.name)}, ${fmtShort.format(parseYmd(d))}">${CHECK_SVG}</button></td>`).join('')}
        <td class="h-streak">${st} ${st === 1 ? 'Tag' : 'Tage'}</td>
        <td><button type="button" class="icon-btn" data-action="habit-delete" aria-label="Löschen: ${esc(h.name)}" title="Löschen">${TRASH_SVG}</button></td>
      </tr>`;
    }).join('');
    $('#habitTable').hidden = state.habits.length === 0;
    $('.habit-table-wrap').hidden = state.habits.length === 0;
    $('#habitEmpty').hidden = state.habits.length > 0;
  }

  function toggleHabit(id, day) {
    const h = state.habits.find((x) => x.id === id);
    if (!h) return;
    if (h.days[day]) delete h.days[day]; else h.days[day] = 1;
    save();
    renderAll();
  }

  function deleteHabit(id) {
    const i = state.habits.findIndex((x) => x.id === id);
    if (i < 0) return;
    const [removed] = state.habits.splice(i, 1);
    save();
    renderAll();
    toast(`„${removed.name}“ gelöscht.`, () => { state.habits.splice(i, 0, removed); save(); renderAll(); });
  }

  /* ── Notizen ───────────────────────────────────────────── */
  let noteQuery = '';
  const noteSort = (a, b) => b.updated - a.updated;
  const currentNote = () => state.notes.find((n) => n.id === state.prefs.noteId);

  function renderNotes() {
    const q = noteQuery.trim().toLowerCase();
    const notes = [...state.notes].sort(noteSort).filter((n) => !q || (n.title + '\n' + n.body).toLowerCase().includes(q));
    $('#noteSummary').textContent = state.notes.length === 1 ? '1 Notiz' : `${state.notes.length} Notizen`;
    $('#notesList').innerHTML = notes.length
      ? notes.map((n) => `<li><button type="button" class="note-item" data-action="note-open" data-id="${esc(n.id)}" aria-current="${n.id === state.prefs.noteId}">
          <span class="t">${esc(n.title || 'Ohne Titel')}</span>
          <span class="s">${esc(n.body.split('\n').find((l) => l.trim()) || 'Leer')}</span>
          <span class="m">${fmtStamp.format(new Date(n.updated))}${n.ex ? ' · Beispiel' : ''}</span>
        </button></li>`).join('')
      : `<li class="list-empty">${q ? 'Nichts gefunden.' : 'Noch keine Notizen.'}</li>`;

    const n = currentNote();
    $('#noteEditor').hidden = !n;
    $('#noteEmpty').hidden = !!n;
    if (n) {
      const ti = $('#noteTitle'), bo = $('#noteBody');
      if (ti.dataset.id !== n.id || document.activeElement !== ti) ti.value = n.title;
      if (bo.dataset.id !== n.id || document.activeElement !== bo) bo.value = n.body;
      ti.dataset.id = bo.dataset.id = n.id;
      $('#noteSaved').textContent = 'Gespeichert ' + fmtStamp.format(new Date(n.updated));
    }
  }

  function newNote() {
    const n = { id: uid(), title: '', body: '', created: Date.now(), updated: Date.now() };
    state.notes.push(n);
    state.prefs.noteId = n.id;
    noteQuery = '';
    $('#noteSearch').value = '';
    save();
    if (currentView !== 'notizen') go('notizen');
    renderNotes();
    $('#noteTitle').focus();
  }

  function deleteNote() {
    const i = state.notes.findIndex((n) => n.id === state.prefs.noteId);
    if (i < 0) return;
    const [removed] = state.notes.splice(i, 1);
    state.prefs.noteId = [...state.notes].sort(noteSort)[0]?.id || '';
    save();
    renderNotes();
    toast(`„${removed.title || 'Ohne Titel'}“ gelöscht.`, () => {
      state.notes.splice(i, 0, removed);
      state.prefs.noteId = removed.id;
      save();
      renderNotes();
    });
  }

  /* ── Fokus-Timer ───────────────────────────────────────── */
  const T = () => state.focus.timer;
  const S = () => state.focus.settings;
  const modeMs = (mode) => Math.max(1, Number(S()[mode]) || 1) * 60000;
  const RING_LEN = 2 * Math.PI * 96;

  function timerRemaining() {
    const t = T();
    return t.running ? Math.max(0, t.endsAt - Date.now()) : t.remaining;
  }

  function setMode(mode) {
    const t = T();
    t.mode = mode;
    t.running = false;
    t.total = t.remaining = modeMs(mode);
    save();
    renderFocus();
  }

  function timerToggle() {
    const t = T();
    unlockAudio();
    if (t.running) {
      t.remaining = Math.max(0, t.endsAt - Date.now());
      t.running = false;
    } else {
      if (t.remaining <= 0) t.remaining = t.total = modeMs(t.mode);
      t.endsAt = Date.now() + t.remaining;
      t.running = true;
      t.owner = WIN_ID;
    }
    save(true);
    renderFocus();
  }

  function timerReset() {
    const t = T();
    t.running = false;
    t.total = t.remaining = modeMs(t.mode);
    save(true);
    renderFocus();
  }

  function nextSegment(t) {
    const rounds = Math.max(2, Number(S().rounds) || 4);
    if (t.mode === 'focus') {
      t.mode = t.round >= rounds ? 'long' : 'short';
    } else {
      t.round = t.mode === 'long' ? 1 : Math.min(rounds, t.round + 1);
      t.mode = 'focus';
    }
    t.total = t.remaining = modeMs(t.mode);
  }

  function timerSkip() {
    const t = T();
    t.running = false;
    nextSegment(t);
    save(true);
    renderFocus();
  }

  function completeSegment() {
    const t = T();
    const endedAt = t.endsAt;
    const late = Date.now() - endedAt > LATE_MS;
    const wasMode = t.mode;
    if (wasMode === 'focus') {
      state.focus.sessions[String(endedAt)] = { d: ymd(new Date(endedAt)), m: Math.round(t.total / 60000), t: t.taskId || '' };
    }
    const alertHere = !late && (t.owner === WIN_ID || !t.owner);
    nextSegment(t);
    if (S().auto && !late) {
      // Deterministisch weiterzählen, damit mehrere Fenster denselben Stand haben
      t.endsAt = endedAt + t.total;
      t.running = true;
    } else {
      t.running = false;
    }
    save(true);
    renderAll();
    if (alertHere) {
      const msg = wasMode === 'focus'
        ? `Fokus geschafft. Jetzt ${MODE_LABEL[t.mode]} (${S()[t.mode]} min).`
        : 'Pause vorbei. Weiter geht’s!';
      if (S().sound) chime();
      notify(wasMode === 'focus' ? 'Fokus-Einheit geschafft' : 'Pause vorbei', msg);
      toast(msg);
    }
  }

  let lastShown = '';
  let lastDay = ymd();
  function tick() {
    const t = T();
    if (t.running && Date.now() >= t.endsAt) {
      // Das Fenster, das gestartet hat, schließt sofort ab; andere Fenster mit kurzer Verzögerung
      const grace = t.owner && t.owner !== WIN_ID ? 2500 : 0;
      if (Date.now() >= t.endsAt + grace) completeSegment();
    }
    const rem = timerRemaining();
    const secs = Math.ceil(rem / 1000);
    const txt = `${pad(Math.floor(secs / 60))}:${pad(secs % 60)}`;
    const key = txt + t.running + t.mode;
    if (key !== lastShown) {
      lastShown = key;
      $('#timerDigits').textContent = txt;
      const frac = t.total ? Math.min(1, Math.max(0, 1 - rem / t.total)) : 0;
      $('#ringFill').style.strokeDashoffset = String(RING_LEN * (1 - frac));
      const live = $('#tabLiveTimer');
      live.hidden = !t.running;
      live.textContent = txt;
      document.title = t.running ? `${txt} · ${MODE_LABEL[t.mode]} | Kompass` : 'Kompass Tagesplaner';
    }
    const d = ymd();
    if (d !== lastDay) { lastDay = d; renderAll(); }
  }

  function renderFocus() {
    const t = T();
    const s = S();
    const rounds = Math.max(2, Number(s.rounds) || 4);
    $$('[data-mode]').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.mode === t.mode)));
    const card = $('.timer-card');
    card.classList.toggle('mode-short', t.mode === 'short');
    card.classList.toggle('mode-long', t.mode === 'long');
    $('#timerLabel').textContent = t.mode === 'focus' ? `Fokus · Runde ${t.round} von ${rounds}` : MODE_LABEL[t.mode];
    $('#timerToggle').textContent = t.running ? 'Pause' : (t.remaining < t.total ? 'Weiter' : 'Start');
    $('#roundDots').innerHTML = Array.from({ length: rounds }, (_, i) => `<span class="${i < t.round - (t.mode === 'focus' ? 1 : 0) ? 'done' : ''}"></span>`).join('');
    $('#ringFill').style.strokeDasharray = String(RING_LEN);

    const open = state.tasks.filter((x) => !x.done).sort(taskSort);
    if (t.taskId && !open.some((x) => x.id === t.taskId)) t.taskId = '';
    $('#focusTask').innerHTML = '<option value="">Ohne bestimmte Aufgabe</option>'
      + open.map((x) => `<option value="${esc(x.id)}"${x.id === t.taskId ? ' selected' : ''}>${esc(x.title)}</option>`).join('');

    const today = ymd();
    const f = focusDay(today);
    $('#statMin').textContent = f.m;
    $('#statSessions').textContent = f.n;
    let week = 0;
    for (let i = 0; i < 7; i++) week += focusDay(addDays(today, -i)).m;
    $('#statWeek').textContent = week;

    for (const [id, key] of [['setFocus', 'focus'], ['setShort', 'short'], ['setLong', 'long'], ['setRounds', 'rounds']]) {
      const el = document.getElementById(id);
      if (document.activeElement !== el) el.value = s[key];
    }
    $('#setSound').checked = !!s.sound;
    $('#setAuto').checked = !!s.auto;
    lastShown = '';
    tick();
  }

  /* Ton: kleiner Dreiklang über WebAudio, ohne Audiodatei */
  let audioCtx = null;
  function unlockAudio() {
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === 'suspended') audioCtx.resume();
    } catch { audioCtx = null; }
  }
  function chime() {
    unlockAudio();
    if (!audioCtx) return;
    const start = audioCtx.currentTime + 0.05;
    [659.25, 830.61, 987.77, 1318.5].forEach((freq, i) => {
      const o = audioCtx.createOscillator();
      const g = audioCtx.createGain();
      o.type = 'sine';
      o.frequency.value = freq;
      const t0 = start + i * 0.16;
      g.gain.setValueAtTime(0.0001, t0);
      g.gain.exponentialRampToValueAtTime(0.25, t0 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.9);
      o.connect(g).connect(audioCtx.destination);
      o.start(t0);
      o.stop(t0 + 1);
    });
  }

  function notify(title, body) {
    try {
      if (!('Notification' in window) || Notification.permission !== 'granted') return;
      if (document.visibilityState === 'visible' && document.hasFocus()) return;
      new Notification(title, { body, icon: 'icons/icon-192.png', tag: 'kompass-timer' });
    } catch { /* Benachrichtigungen nicht verfügbar */ }
  }

  function renderNotifyState() {
    const el = $('#notifyState');
    const btn = $('#notifyBtn');
    if (!('Notification' in window)) {
      el.textContent = 'Dieser Browser unterstützt hier keine Benachrichtigungen.';
      btn.hidden = true;
      return;
    }
    const p = Notification.permission;
    btn.hidden = p === 'granted';
    el.textContent = p === 'granted' ? 'Benachrichtigungen sind an.' : p === 'denied' ? 'Blockiert. Du kannst sie in den Website-Einstellungen von Brave wieder erlauben.' : '';
  }

  /* ── Installation als App (PWA) ────────────────────────── */
  let installEvent = null;
  const standalone = () => window.matchMedia('(display-mode: standalone)').matches || window.matchMedia('(display-mode: window-controls-overlay)').matches || navigator.standalone === true;
  function renderInstall() {
    const can = !!installEvent && !standalone();
    $('#installBtn').hidden = !can;
    $('#installBtn2').hidden = !can;
    if (standalone()) $('#installText').textContent = 'Du nutzt Kompass gerade als App. Das Symbol findest du auf dem Desktop bzw. im Startmenü.';
  }
  window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); installEvent = e; renderInstall(); });
  window.addEventListener('appinstalled', () => { installEvent = null; renderInstall(); toast('Kompass ist jetzt als App installiert.'); });
  async function doInstall() {
    if (!installEvent) return;
    installEvent.prompt();
    try { await installEvent.userChoice; } catch { /* abgebrochen */ }
    installEvent = null;
    renderInstall();
  }

  /* ── Sicherung ─────────────────────────────────────────── */
  const backupText = () => JSON.stringify({ app: 'kompass', version: 1, exportedAt: new Date().toISOString(), data: state }, null, 2);
  const dataMsg = (m) => { $('#dataMsg').textContent = m; };

  function exportFile() {
    try {
      const blob = new Blob([backupText()], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `kompass-sicherung-${ymd()}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      dataMsg('Sicherung wird heruntergeladen. Falls nichts passiert: „Sicherung kopieren“ nutzen.');
    } catch {
      dataMsg('Download nicht möglich. Nutze „Sicherung kopieren“.');
    }
  }

  function exportCopy() {
    const text = backupText();
    const fallback = () => {
      const ta = $('#importText');
      ta.value = text;
      ta.focus();
      ta.select();
      dataMsg('Kopieren nicht erlaubt. Die Sicherung steht markiert im Feld unten, kopiere sie mit Strg+C.');
    };
    try {
      navigator.clipboard.writeText(text).then(() => dataMsg('Sicherung in die Zwischenablage kopiert.'), fallback);
    } catch { fallback(); }
  }

  function importText(text) {
    let raw;
    try { raw = JSON.parse(text); } catch { dataMsg('Das ist keine gültige Sicherung (kein JSON).'); return; }
    const data = raw && raw.data ? raw.data : raw;
    if (!data || !Array.isArray(data.tasks) || !Array.isArray(data.notes)) {
      dataMsg('Das sieht nicht nach einer Kompass-Sicherung aus.');
      return;
    }
    state = normalize(data);
    state.focus.timer.running = false;
    save(true);
    renderAll();
    applyTheme();
    dataMsg(`Sicherung geladen: ${state.tasks.length} Aufgaben, ${state.habits.length} Gewohnheiten, ${state.notes.length} Notizen.`);
  }

  function wipe() {
    state = defaults();
    state.prefs.seeded = true;
    save(true);
    applyTheme();
    renderAll();
    toast('Alles gelöscht. Frischer Start.');
  }

  /* Zweistufige Bestätigung (confirm() ist in manchen Ansichten gesperrt) */
  function armed(btn, run) {
    if (btn.classList.contains('is-armed')) {
      btn.classList.remove('is-armed');
      btn.textContent = btn.dataset.label;
      run();
      return;
    }
    btn.dataset.label = btn.textContent;
    btn.textContent = btn.dataset.confirm || 'Sicher?';
    btn.classList.add('is-armed');
    setTimeout(() => {
      if (btn.classList.contains('is-armed')) { btn.classList.remove('is-armed'); btn.textContent = btn.dataset.label; }
    }, 4000);
  }

  /* ── Umbenennen einer Aufgabe ──────────────────────────── */
  function startEdit(el) {
    const li = el.closest('.task');
    const t = state.tasks.find((x) => x.id === li.dataset.id);
    if (!t || el.isContentEditable) return;
    el.contentEditable = 'true';
    el.focus();
    const range = document.createRange();
    range.selectNodeContents(el);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    const finish = (commit) => {
      el.removeEventListener('keydown', onKey);
      el.removeEventListener('blur', onBlur);
      el.contentEditable = 'false';
      const v = el.textContent.replace(/\s+/g, ' ').trim();
      if (commit && v && v !== t.title) { t.title = v.slice(0, 140); save(); }
      renderAll();
    };
    const onKey = (e) => {
      if (e.key === 'Enter') { e.preventDefault(); finish(true); }
      if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    };
    const onBlur = () => finish(true);
    el.addEventListener('keydown', onKey);
    el.addEventListener('blur', onBlur);
  }

  /* ── Alles zeichnen ────────────────────────────────────── */
  function renderAll() {
    renderToday();
    renderTasks();
    renderHabits();
    renderFocus();
    renderNotes();
    renderInstall();
    renderNotifyState();
  }

  /* ── Ereignisse ────────────────────────────────────────── */
  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-action]');
    if (!el) return;
    const action = el.dataset.action;
    const rowId = el.closest('[data-id]')?.dataset.id;
    switch (action) {
      case 'task-toggle': toggleTask(rowId); break;
      case 'task-delete': deleteTask(rowId); break;
      case 'overdue-today': {
        const today = ymd();
        state.tasks.forEach((t) => { if (!t.done && t.due && t.due < today) t.due = today; });
        save(); renderAll(); toast('Überfällige Aufgaben stehen jetzt auf heute.');
        break;
      }
      case 'clear-done': {
        const removed = state.tasks.filter((t) => t.done);
        state.tasks = state.tasks.filter((t) => !t.done);
        save(); renderAll();
        toast(`${removed.length} erledigte Aufgaben gelöscht.`, () => { state.tasks.push(...removed); save(); renderAll(); });
        break;
      }
      case 'habit-toggle': toggleHabit(rowId, el.dataset.day); break;
      case 'habit-delete': deleteHabit(rowId); break;
      case 'note-new': newNote(); break;
      case 'note-open': state.prefs.noteId = el.dataset.id; save(); renderNotes(); break;
      case 'note-delete': deleteNote(); break;
      case 'timer-toggle': timerToggle(); break;
      case 'timer-reset': timerReset(); break;
      case 'timer-skip': timerSkip(); break;
      case 'clear-examples': clearExamples(); break;
      case 'wipe': armed(el, wipe); break;
      case 'export-file': exportFile(); break;
      case 'export-copy': exportCopy(); break;
      case 'import-text': importText($('#importText').value); break;
      case 'notify-permission':
        try { Notification.requestPermission().then(renderNotifyState, renderNotifyState); } catch { renderNotifyState(); }
        break;
    }
  });

  document.addEventListener('dblclick', (e) => {
    const el = e.target.closest('[data-action="task-edit"]');
    if (el) startEdit(el);
  });

  $$('[data-filter]').forEach((b) => b.addEventListener('click', () => { state.prefs.filter = b.dataset.filter; save(); renderTasks(); }));
  $$('[data-mode]').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.mode)));
  $$('[data-theme-choice]').forEach((b) => b.addEventListener('click', () => { state.prefs.theme = b.dataset.themeChoice; save(); applyTheme(); }));
  $('#installBtn').addEventListener('click', doInstall);
  $('#installBtn2').addEventListener('click', doInstall);

  $('#quickAddForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const inp = $('#quickAddInput');
    if (!inp.value.trim()) return;
    addTask(inp.value, ymd(), 'mittel');
    inp.value = '';
    toast('Für heute eingetragen.');
  });

  $('#taskForm').addEventListener('submit', (e) => {
    e.preventDefault();
    addTask($('#taskTitle').value, $('#taskDue').value, $('#taskPrio').value);
    $('#taskTitle').value = '';
    $('#taskTitle').focus();
  });

  $('#habitForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const name = $('#habitName').value.trim();
    if (!name) return;
    state.habits.push({ id: uid(), name, days: {}, created: Date.now() });
    $('#habitName').value = '';
    save();
    renderAll();
  });

  let scratchTimer = 0;
  $('#scratch').addEventListener('input', (e) => {
    state.prefs.scratch = e.target.value;
    save();
    $('#scratchSaved').textContent = 'speichert …';
    clearTimeout(scratchTimer);
    scratchTimer = setTimeout(() => { $('#scratchSaved').textContent = 'gespeichert'; }, 500);
  });

  $('#noteSearch').addEventListener('input', (e) => { noteQuery = e.target.value; renderNotes(); });
  const onNoteInput = () => {
    const n = currentNote();
    if (!n) return;
    n.title = $('#noteTitle').value;
    n.body = $('#noteBody').value;
    n.updated = Date.now();
    delete n.ex;
    save();
    renderNotes();
  };
  $('#noteTitle').addEventListener('input', onNoteInput);
  $('#noteBody').addEventListener('input', onNoteInput);
  $('#noteTitle').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); $('#noteBody').focus(); } });

  $('#focusTask').addEventListener('change', (e) => { T().taskId = e.target.value; save(); });

  $('#timerSettings').addEventListener('input', () => {
    const s = S();
    const num = (id, min, max) => {
      const v = Math.round(Number(document.getElementById(id).value));
      return Number.isFinite(v) && v >= min ? Math.min(max, v) : null;
    };
    const vals = { focus: num('setFocus', 1, 120), short: num('setShort', 1, 60), long: num('setLong', 1, 60), rounds: num('setRounds', 2, 8) };
    for (const [k, v] of Object.entries(vals)) if (v !== null) s[k] = v;
    s.sound = $('#setSound').checked;
    s.auto = $('#setAuto').checked;
    const t = T();
    // Unberührten Timer an die neue Dauer anpassen
    if (!t.running && t.remaining === t.total) t.total = t.remaining = modeMs(t.mode);
    if (t.round > s.rounds) t.round = s.rounds;
    save();
    renderFocus();
  });
  $('#timerSettings').addEventListener('submit', (e) => e.preventDefault());

  $('#importFile').addEventListener('change', (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const r = new FileReader();
    r.onload = () => importText(String(r.result));
    r.onerror = () => dataMsg('Datei konnte nicht gelesen werden.');
    r.readAsText(file);
    e.target.value = '';
  });

  document.addEventListener('keydown', (e) => {
    const typing = e.target.closest('input, textarea, select, [contenteditable="true"]');
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (/^[1-6]$/.test(e.key)) { go(VIEWS[Number(e.key) - 1]); e.preventDefault(); return; }
    if (e.key === 'n' || e.key === 'N') {
      e.preventDefault();
      if (currentView === 'heute') $('#quickAddInput').focus();
      else { go('aufgaben'); setTimeout(() => $('#taskTitle').focus(), 0); }
      return;
    }
    if (e.key === ' ' && currentView === 'fokus' && !e.target.closest('button')) { e.preventDefault(); timerToggle(); }
  });

  // Mehrere Fenster (z. B. Tab und App) bleiben synchron
  window.addEventListener('storage', (e) => {
    if (e.key !== STORE_KEY || !e.newValue) return;
    try { state = normalize(JSON.parse(e.newValue)); } catch { return; }
    applyTheme();
    renderAll();
  });

  const flush = () => {
    if (T().owner === WIN_ID) T().owner = '';
    save(true);
  };
  window.addEventListener('pagehide', flush);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') save(true); });

  /* ── Start ─────────────────────────────────────────────── */
  applyTheme();
  renderAll();
  route();
  setInterval(tick, 250);

  if ('serviceWorker' in navigator && /^https?:$/.test(location.protocol)) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('sw.js').catch(() => { /* ohne Offline-Modus weiter */ });
    });
  }
})();
