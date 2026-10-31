/* shiftlead client: /events patches cards by id; Focus drives xterm.js over /term/<id>.
   No framework, no build step (design §4.5). Browser mechanics per design §4.5 "Browser mechanics". */
(function () {
  const AO = (window.AO = {});
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const store = {
    get(k, d) { try { const v = localStorage.getItem("ao." + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("ao." + k, JSON.stringify(v)); } catch (e) {} },
  };

  // ---- theme (token swap; system default, manual toggle remembered) ----
  function applyTheme() {
    // the same read as `base.html`'s `<head>` makes before the first paint (TD-737): a stored value that
    // is not a theme is the system's, and a system that cannot be read is dark — else the two disagree
    let t = store.get("theme", null);
    if (t !== "dark" && t !== "light") {
      try { t = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; } catch (e) { t = "dark"; }
    }
    document.documentElement.dataset.theme = t;
  }
  applyTheme();

  // ---- the terminal's look (design goal 12, §4.6, TD-038) ----
  // One place, because it was three: the pane's font and size are here, not repeated at the call
  // site. The palette is VS Code's Dark Modern terminal, so the same Claude Code output is the same
  // colour in Focus as in the editor's terminal beside it — which is the point of goal 2, driving
  // the session in place. Goal 12 keeps the pane dark whatever the page theme is, so these are
  // literals rather than tokens: `--term` follows the theme and this must not.
  AO.TERM_OPTS = { cursorBlink: true, fontFamily: '"JetBrains Mono", "Cascadia Code", Menlo, Consolas, monospace', fontSize: 13, lineHeight: 1.2, letterSpacing: 0 };
  AO.TERM_THEME = {
    background: "#0b0e12",  // the app's own dark, not VS Code's #1f1f1f: the pane sits in this chrome
    foreground: "#cccccc", cursor: "#aeafad", cursorAccent: "#0b0e12", selectionBackground: "#264f78",
    black: "#000000", red: "#cd3131", green: "#0dbc79", yellow: "#e5e510",
    blue: "#2472c8", magenta: "#bc3fbc", cyan: "#11a8cd", white: "#e5e5e5",
    brightBlack: "#666666", brightRed: "#f14c4c", brightGreen: "#23d18b", brightYellow: "#f5f543",
    brightBlue: "#3b8eea", brightMagenta: "#d670d6", brightCyan: "#29b8db", brightWhite: "#e5e5e5",
  };

  // The WebGL renderer (TD-038 (c)): crisper and lighter than the DOM renderer's element per cell,
  // and what VS Code's terminal uses. Without WebGL, or when the GPU takes the context back, the
  // DOM renderer simply stays or returns, so this can only ever improve the pane.
  AO.termRenderer = function (term) {
    if (typeof WebglAddon === "undefined") return;
    try {
      const gl = new WebglAddon.WebglAddon();
      gl.onContextLoss(() => gl.dispose());
      term.loadAddon(gl);
    } catch (e) { /* no WebGL here: the DOM renderer draws the pane */ }
  };
  // xterm.js measures a cell once, at open; the bundled face (app.css) may still be on its way, and
  // a cell measured on the fallback font leaves every glyph misplaced once it lands. So when the
  // face was not ready at open, measure again when it is. Two sets, because xterm.js ignores an
  // option set to the value it already has.
  AO.termFont = function (term, fit) {
    const spec = `${AO.TERM_OPTS.fontSize}px ${AO.termFace || '"JetBrains Mono"'}`;
    if (!document.fonts || document.fonts.check(spec)) return;
    document.fonts.load(spec).then(() => {
      term.options.fontFamily = "monospace";
      term.options.fontFamily = AO.TERM_OPTS.fontFamily;
      fit.fit();
    }).catch(() => { /* the fallback stack stays: still a monospace pane */ });
  };
  // The person's face and size (goal 12, §5 `person.terminal`, the Settings page; TD-148): the page
  // is drawn with them on `<body>`, and a Save on the Settings page tells this browser's other tabs
  // at once, so every open terminal takes them without a reload. `monospace` always ends the stack;
  // ligatures stay off (xterm.js draws none without its addon, which is never loaded).
  AO.terms = [];
  AO.termFamily = (face) => (face ? `"${String(face).replace(/["\\]/g, "")}", monospace` : '"JetBrains Mono", "Cascadia Code", Menlo, Consolas, monospace');
  AO.setTermLook = function (look) {
    const size = Number(look && look.size), face = look && look.face ? String(look.face) : "";
    AO.TERM_OPTS.fontSize = size >= 8 && size <= 32 ? size : 13;
    AO.TERM_OPTS.fontFamily = AO.termFamily(face);
    AO.termFace = face ? `"${face.replace(/["\\]/g, "")}"` : "";
    AO.terms.forEach(({ term, fit }) => {
      term.options.fontSize = AO.TERM_OPTS.fontSize;
      term.options.fontFamily = AO.TERM_OPTS.fontFamily;
      try { fit.fit(); } catch (e) { /* a pane not laid out yet fits on its next resize */ }
      AO.termFont(term, fit);
    });
  };
  if (document.body && document.body.dataset) AO.setTermLook({ size: document.body.dataset.termSize, face: document.body.dataset.termFace });
  AO.termChan = (() => { try { return new BroadcastChannel("ao-term"); } catch (e) { return null; } })();
  if (AO.termChan) AO.termChan.onmessage = (e) => AO.setTermLook(e.data || {});
  if (AO.termChan && AO.termChan.unref) AO.termChan.unref();  // node's probes (tests) only: a browser has no unref

  // ---- toasts: the one error surface (design §4.5) ----
  // `wait` makes **a toast that waits** (§4.5 screen 6 *A control answers the press*, TD-340): no
  // clock until `settle(text, ok, href)` rewrites it with the answer and starts one. `sticky` makes one
  // that stays until it is pressed (a blocked open's, TD-810: the page is the only place it shows).
  // `ms`, when given, replaces the clock's length (a copy's note stays 7 s and keeps its colour, TD-1267).
  // Returns the toast.
  AO.toast = function (text, ok, href, wait, sticky, ms) {
    const el = document.createElement("div");
    const draw = (t, good, link) => {
      el.className = "toast" + (good ? " ok" : "");
      el.textContent = t;
      // a toast that names a thing links to its page (*handed to techlead-ao-1 · m-…*, TD-219 slice 4)
      if (link) { const a = document.createElement("a"); a.href = link; a.textContent = " open"; el.appendChild(a); }
      if (sticky) { el.style.cursor = "pointer"; el.onclick = () => el.remove(); }
      else setTimeout(() => el.remove(), ms || (link ? 10000 : good ? 3000 : 7000));  // a link needs the time to be pressed
    };
    el.settle = (t, good, link) => { draw(t, good, link); return el; };
    const box = $("#toasts");
    if (wait) { el.className = "toast wait"; el.textContent = text; } else draw(text, ok, href);
    if (box) box.appendChild(el);
    return el;
  };

  // **A selection is one screen, and a copy is its rows** (§4.6, TD-1263, TD-1267): the pane says so at the two
  // moments the limit bites, as a note on the toast the copy or the release already draws. A drag's pointer is
  // past an edge once it is a screen row's height or more above the screen's top or below its bottom.
  AO.pastEdge = function (clientY, rect, cell) {
    if (clientY <= rect.top - cell) return "top";
    if (clientY >= rect.bottom + cell) return "bottom";
    return null;
  };
  // …the drag's mark, `{drag, edge}`, over the page's mouse events: a press on the terminal resets it and starts a
  // drag unless it is a Shift press (or not the primary button); a crossing while the drag is held sets the edge,
  // the last crossed winning, and a return keeps it; a release fires the edge once, only if the drag moved the
  // selection, and clears it
  AO.edgeMark = function (mark, ev) {
    const m = mark || { drag: false, edge: null };
    if (ev.type === "down") return { mark: { drag: !ev.shift, edge: null }, fire: null };
    if (ev.type === "move") return { mark: m.drag && ev.edge ? { drag: true, edge: ev.edge } : m, fire: null };
    if (ev.type === "up") return { mark: { drag: false, edge: null }, fire: m.drag && ev.moved ? m.edge : null };
    return { mark: m, fire: null };
  };
  // …the note's words, or "": the edge's first; else the first copy of several rows on the page's load, only
  // where the header draws **Transcript**
  AO.copyNote = function ({ edge, multi, flagFree, transcript }) {
    if (edge) return transcript ? "the selection stops at the screen's edge; Transcript has the whole conversation"
      : "the selection stops at the screen's edge: copy a screen at a time";
    return multi && flagFree && transcript ? "as the screen's rows; Transcript has wrapped lines whole" : "";
  };
  // …a copy of `text` through `write` (the clipboard's), its toast after a dash with the note. The first-copy
  // flag (`state.firstFree`) is taken as the write is called, so two quick copies draw one note, and given back
  // if the write is refused, whose toast carries the edge's note alone. Returns the write's promise.
  AO.copyWith = function ({ text, edge, transcript, state, write, toast }) {
    const note = AO.copyNote({ edge, multi: text.includes("\n"), flagFree: state.firstFree, transcript });
    const first = !!note && !edge;
    if (first) state.firstFree = false;
    const say = (t, ok, n) => (n ? toast(`${t} — ${n}`, ok, undefined, undefined, undefined, 7000) : toast(t, ok));
    // a write that throws (no clipboard outside a secure context) is a refusal too
    return Promise.resolve().then(() => write(text)).then(() => say("copied", true, note), () => {
      if (first) state.firstFree = true;
      say("clipboard blocked (needs https or localhost)", false, edge ? note : "");
    });
  };

  // The Focus pane's **copy on select** (§4.5a, TD-174): written to the person's settings, which
  // every browser reads; a refusal puts the box back and says why.
  AO.setCopyOnSelect = async function (box) {
    const want = !!box.checked;
    try {
      const r = await fetch("/api/settings/person", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ terminal: { copy_on_select: want } }),
      });
      if (!r.ok) { let t = r.statusText; try { t = (await r.json()).detail || t; } catch (e) {} throw new Error(t); }
      AO.toast(want ? "copy on select: on" : "copy on select: off", true);
    } catch (e) {
      box.checked = !want;
      AO.toast(`copy on select not saved: ${e.message}`);
    }
  };

  // ---- actions: every data-act button posts to /api/sessions/<id>/<act> ----
  async function act(id, action, body) {
    // the top bar's person inbox is no session: its Reply and delete have their own routes (§4.5a)
    const r = await fetch(id === "person" ? `/api/person/${action}` : `/api/sessions/${id}/${action}`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body || {}),
    });
    if (!r.ok) {
      let t = r.statusText; try { t = (await r.json()).detail || t; } catch (e) {}
      const err = new Error(t); err.status = r.status; throw err;  // a 503 is a verdict unknown (TD-806)
    }
    return r.json();
  }
  AO.act = act;

  // The Focus composer's **Attach** (§4.5a, TD-002): a pasted image carries the browser's own name
  // for it, `image.png`, every time, so it is named for the moment instead — `paste-20261007-171204.png`.
  AO.attachName = function (f, now) {
    if (f.name && f.name !== "image.png") return f.name;
    const p = (n) => String(n).padStart(2, "0");
    const ext = ((f.type || "").split("/")[1] || "png").replace(/[^a-z0-9]/gi, "") || "png";
    return `paste-${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}-${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}.${ext}`;
  };
  // `text` into a textarea at its caret (over its selection), a space either side where the
  // neighbour is not one, the caret left after it.
  AO.insertAtCaret = function (box, text) {
    const v = box.value, a = box.selectionStart ?? v.length, b = box.selectionEnd ?? a;
    const before = v.slice(0, a), after = v.slice(b);
    const ins = (before && !/\s$/.test(before) ? " " : "") + text + (/^\s/.test(after) ? "" : " ");
    box.value = before + ins + after;
    box.selectionStart = box.selectionEnd = before.length + ins.length;
  };

  // The Focus composer's attach wiring (§4.5a *Focus composer*, TD-002), its elements and its upload
  // handed in, so the rules run as themselves under node (TD-370): the picker, a drop on any of
  // `targets` and a paste into `compose` each attach their files one upload at a time, the path each
  // answers inserted at the caret; nothing while `composer` is closed, and a paste carrying
  // `text/plain` is the text's. `upload(f, ctl)` is handed `ctl.progress(pct, last)`, which past a file's
  // first piece makes the label *Attaching <name> · n%* and shows `cancel`, the ✕, until `last`, and
  // `ctl.cancelled()`, true once the ✕ was pressed for this file; an upload that answers no path was
  // cancelled and inserts nothing (TD-478). Answers `attach(files, put)`, the promise of the queue:
  // with `put`, the terminal's paste of a file (TD-479), each path goes to `put` and not to the caret,
  // and the composer need not be open. The folded composer (§4.5a **the bar**, TD-500): `unfold()` opens
  // it before a path goes to its caret, and `mirror`, the bar's own Attach and ✕, says the upload there too.
  // `token()`, where given, is read when a batch is queued and handed to each of its files as `ctl.token`,
  // so an upload can tell the batch's moment from now (the Message dialog closed since, TD-531).
  AO.wireAttach = function ({ button, input, composer, compose, targets, upload, fail, cancel, unfold, mirror, token }) {
    const buttons = [button, ...(mirror ? [mirror.button] : [])];
    const cancels = [cancel, ...(mirror ? [mirror.cancel] : [])].filter(Boolean);
    const labels = buttons.map((b) => b.lastChild), word = labels[0].textContent;
    const say = (t) => labels.forEach((l) => { l.textContent = t; });
    const shut = () => composer.classList.contains("hidden");
    let attaching = Promise.resolve();  // one upload at a time: a drop during a picker's run waits its turn
    let stopNow = () => {};
    const cancelOff = (off) => cancels.forEach((c) => c.classList.toggle("hidden", off));
    for (const c of cancels) c.addEventListener("click", () => { stopNow(); cancelOff(true); });
    async function each(list, put, tok) {
      buttons.forEach((b) => { b.disabled = true; });
      for (const f of list) {
        say(`Attaching ${f.name}…`);
        let stopped = false;
        stopNow = () => { stopped = true; };
        const ctl = {
          // the ✕ goes once only the last piece is left: that one links the file into place, past cancelling
          progress: (pct, last) => { say(`Attaching ${f.name} · ${pct}%`); cancelOff(stopped || !!last); },
          cancelled: () => stopped,
          token: tok,
        };
        try {
          const path = await upload(f, ctl);
          if (path) put ? put(path) : AO.insertAtCaret(compose, path);
        } catch (e) { fail(`Attach failed: ${e.message}`); }
        stopNow = () => {};
        cancelOff(true);
      }
      say(word); buttons.forEach((b) => { b.disabled = !!(b.dataset && b.dataset.refused); });  // a refusal outlives the run
      if (!put) { compose.dispatchEvent(new Event("input")); compose.focus(); }
    }
    function attach(files, put) {
      const list = Array.from(files || []);
      if (!list.length || (!put && shut())) return attaching;
      if (!put && unfold) unfold();
      const tok = token ? token() : undefined;
      attaching = attaching.then(() => each(list, put, tok)).catch((e) => fail(`Attach failed: ${e.message}`));
      return attaching;
    }
    buttons.forEach((b) => b.addEventListener("click", () => input.click()));
    input.addEventListener("change", () => { attach(input.files).finally(() => { input.value = ""; }); });
    for (const el of targets) {
      el.addEventListener("dragover", (e) => { if (!shut() && e.dataTransfer && [...e.dataTransfer.types].includes("Files")) e.preventDefault(); });
      el.addEventListener("drop", (e) => { if (!shut() && e.dataTransfer && e.dataTransfer.files.length) { e.preventDefault(); attach(e.dataTransfer.files); } });
    }
    compose.addEventListener("paste", (e) => {
      const cd = e.clipboardData;
      if (shut() || !cd || !cd.files.length || [...cd.types].includes("text/plain")) return;
      e.preventDefault(); attach(cd.files);
    });
    return attach;
  };

  // §4.5a *Focus composer* **the bar** (TD-491, built by TD-500): what the folded bar reads — the reason
  // nothing can be sent where there is one, else the draft's first words, else the invitation — the
  // page's own (`data-invite`), which on a record with no agent reads *Type a command…* (TD-666).
  AO.barText = function (draft, reason, invite) {
    if (reason) return reason;
    const words = (draft || "").trim().split(/\s+/).filter(Boolean);
    if (!words.length) return invite || "✎ Compose a prompt… (c · or paste / drop a file)";
    const first = words.slice(0, 8).join(" ");
    return `✎ draft · ${first.length > 60 ? first.slice(0, 59) + "…" : first}${words.length > 8 && first.length <= 60 ? "…" : ""}`;
  };
  // The folded Focus's terminal height: from its top to the bar (and the page's foot under it), never
  // under the 360px floor. `top` is the terminal's top in the document, `below` what stands under it.
  AO.termFill = (viewport, top, below) => Math.max(360, Math.floor(viewport - top - below));
  // The grid tmux is told (TD-794): one `{resize}` per gesture, the last grid once the box has been still
  // for `wait` ms, and none when it is the grid tmux already has. A drag of the panel's edge or a put away
  // fires the observer once a frame, and each resize makes the tool repaint over lines tmux keeps.
  // `send` answers whether the grid went (the socket open); `mark` records a grid sent another way.
  // The timers are wrapped: a browser's `setTimeout` called as a method of another object throws.
  AO.resizeSender = function (send, wait = 150, timers = { set: (f, ms) => setTimeout(f, ms), clear: (id) => clearTimeout(id) }) {
    let timer = null, last = "";
    const fn = (cols, rows) => {
      timers.clear(timer);
      timer = timers.set(() => {
        timer = null;
        if (`${cols}x${rows}` !== last && send([cols, rows])) last = `${cols}x${rows}`;
      }, wait);
    };
    fn.mark = (cols, rows) => { timers.clear(timer); timer = null; last = `${cols}x${rows}`; };
    return fn;
  };
  // The bar's wiring, its elements handed in so it runs under node (TD-500). Opening unfolds the overlay
  // and focuses the box; folding hides it, keeps the draft, redraws the bar and gives the terminal the
  // focus. Neither touches the terminal's box: a resize would make the tool repaint (TD-474).
  AO.wireComposerBar = function ({ bar, text, send, composer, compose, sendBtn, hint, term }) {
    const folded = () => composer.classList.contains("folded");
    const redraw = () => {
      const off = !!compose.disabled;
      text.textContent = AO.barText(compose.value, off ? hint.textContent || "nothing can be sent now" : "", (text.dataset || {}).invite);
      text.classList.toggle("draft", !off && !!compose.value.trim());
      text.classList.toggle("off", off);
      send.disabled = off || !!sendBtn.disabled;  // a send that waits holds both Sends (TD-806)
      send.textContent = sendBtn.textContent;
    };
    const open = () => { composer.classList.remove("folded"); bar.classList.add("under"); compose.focus(); };
    const fold = () => { composer.classList.add("folded"); bar.classList.remove("under"); redraw(); term.focus(); };
    text.addEventListener("click", open);
    send.addEventListener("click", () => { if (compose.value.trim()) sendBtn.click(); else open(); });
    // a paste on the bar: text into the box, opened; a file takes the Attach road, which opens it
    bar.addEventListener("paste", (e) => {
      const cd = e.clipboardData;
      if (!cd || ![...cd.types].includes("text/plain")) return;
      e.preventDefault(); open(); AO.insertAtCaret(compose, cd.getData("text/plain")); compose.dispatchEvent(new Event("input"));
    });
    compose.addEventListener("input", redraw);
    return { open, fold, folded, redraw };
  };

  // §4.10 *A send lands once* (TD-806): the key a page's send carries, minted at the press.
  // `randomUUID` is a secure context's alone, and the page may be served over plain http on a LAN.
  AO.mintKey = function () {
    const c = globalThis.crypto;
    if (c && typeof c.randomUUID === "function") return c.randomUUID();
    const b = new Uint8Array(16);
    if (c && typeof c.getRandomValues === "function") c.getRandomValues(b);
    else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
    return [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  };
  // A prompt chip's press (§4.5a *Focus composer* **prompt chips**, TD-170): its own key, and the chip
  // disabled until its send answers, so a repeat press types nothing (TD-806); Shift fills the box.
  AO.wireChip = function (b, { compose, post, sent, closed, fail }) {
    b.addEventListener("click", async (e) => {
      const text = b.dataset.text || "";
      if (e.shiftKey) { compose.value = text; compose.focus(); return; }
      if (compose.disabled) { closed(); return; }
      if (b.disabled) return;
      b.disabled = true;
      try { await post({ text, key: AO.mintKey() }); sent(); } catch (err) { fail(err); } finally { b.disabled = false; }
    });
  };
  // How long the composer waits on a send before Send is pressable again under the same key.
  AO.SEND_PAGE_SECONDS = 30;
  AO.SEND_UNCONFIRMED = "not confirmed — Send repeats it safely";
  // A send's answer that leaves its verdict unknown: the UI's 503 (the host agent did not answer), or a
  // forward's *its verdict is unknown* (`_route_act`: the link dropped, or the node did not answer in time).
  AO.sendUnknown = (e) => !!e && (e.status === 503 || /its verdict is unknown/.test(e.message || ""));
  // The composer's Send (§4.5a *Focus composer* **Send**, TD-806), its elements and its post handed in so
  // it runs under node: a press mints a key and holds `{key, text}`; until the send answers Send is
  // disabled and reads *Sending…*, the box left editable. A verdict ends the hold: on success the sent
  // text leaves the box only while the box still begins with it, the draft is rewritten from what is
  // left, and `sent(empty)` is told whether the box is now empty (the bar folds only then); a refusal
  // leaves the box as it is and goes to `fail`. An unknown verdict, or no answer in `SEND_PAGE_SECONDS`,
  // leaves the hold standing with Send pressable and the hint *not confirmed*: a press while the box
  // still begins with the held text sends that text under the same key, any other text is a new send.
  // An answer for a key no longer held changes nothing. `label(l)` and `hint(h)` are for the view's
  // redraw, which must leave *Sending…* and *not confirmed* as the hold set them.
  AO.wireComposerSend = function ({ sendBtn, compose, hint, post, draft, sent, fail, redraw, mint, later, cancel }) {
    mint = mint || AO.mintKey; later = later || setTimeout; cancel = cancel || clearTimeout;
    let hold = null;  // {key, text, open, timer}: `open` once Send is pressable again under the same key
    const label = () => sendBtn.dataset.label || "→ Send";
    const reopen = () => {
      if (!hold || hold.open) return;
      hold.open = true; cancel(hold.timer);
      hold.was = hint.textContent; hint.textContent = AO.SEND_UNCONFIRMED;
      sendBtn.disabled = false; sendBtn.textContent = label(); redraw();
    };
    const end = () => {
      if (hold) cancel(hold.timer);
      if (hold && hold.open && hint.textContent === AO.SEND_UNCONFIRMED) hint.textContent = hold.was;
      hold = null; sendBtn.disabled = false; sendBtn.textContent = label(); redraw();
    };
    async function press() {
      if (hold && !hold.open) return;
      let text = compose.value, key;
      if (hold && compose.value.startsWith(hold.text)) ({ text, key } = hold);
      else { if (!text.trim()) return; key = mint(); }
      if (hold && hold.open && hint.textContent === AO.SEND_UNCONFIRMED) hint.textContent = hold.was;
      hold = { key, text, open: false, timer: null };
      hold.timer = later(reopen, AO.SEND_PAGE_SECONDS * 1000);
      sendBtn.disabled = true; sendBtn.textContent = "Sending…"; redraw();
      try {
        await post({ text, key });
        if (!hold || hold.key !== key) return;
        end();
        if (compose.value.startsWith(text)) {
          let rest = compose.value.slice(text.length);
          if (rest.startsWith("\n")) rest = rest.slice(1);
          compose.value = rest;
          draft(rest);
        }
        redraw();
        sent(!compose.value);
      } catch (e) {
        if (!hold || hold.key !== key) return;
        if (AO.sendUnknown(e)) reopen(); else end();
        fail(e);
      }
    }
    sendBtn.addEventListener("click", press);
    return {
      press,
      holding: () => !!hold,
      label: (l) => { sendBtn.dataset.label = l; if (!hold || hold.open) sendBtn.textContent = l; },
      // the view's newer hint is kept for the hold's end, so a state that changed under it is not lost
      hint: (h) => { if (!hold || !hold.open) return h; hold.was = h; return AO.SEND_UNCONFIRMED; },
    };
  };

  // The terminal's **Paste** (§4.5a *Copy / Paste*, TD-472): the clipboard as `clip.read()` gives it.
  // An item carrying `text/plain` is the text's, handed to `text`, as before; one carrying no text and
  // a file type (a screenshot: `image/png` first) is handed to `file` as a File named for the moment,
  // for the attach road. A browser without `read()`, or one that refuses it, pastes text alone through
  // `readText()`, and says so when that finds nothing; a clipboard it cannot read at all is a toast.
  // The file type a clipboard's paste takes, of the types it carries: `image/png` first, else the first
  // that is not text; none when it carries only text. Shared by `AO.clipPaste` and `AO.pasteData`.
  AO.clipFileType = (types) => (types.includes("image/png") ? "image/png" : types.find((t) => !t.startsWith("text/")));
  AO.clipPaste = async function (clip, { text, file, toast, now }) {
    const blocked = () => toast("clipboard blocked (needs https or localhost)");
    const plain = async (says) => {
      let t;
      try { t = await clip.readText(); } catch (e) { blocked(); return; }
      if (t) text(t); else if (says) toast("this browser pastes text only");
    };
    if (!clip) { blocked(); return; }
    if (typeof clip.read !== "function") { await plain(true); return; }
    let items;
    try { items = await clip.read(); } catch (e) { await plain(false); return; }
    try {
      for (const it of items || []) {
        if (!(it.types || []).includes("text/plain")) continue;
        const t = await (await it.getType("text/plain")).text();
        if (t) { text(t); return; }
      }
      for (const it of items || []) {
        const type = AO.clipFileType(it.types || []);
        if (!type) continue;
        const blob = await it.getType(type);
        file(new File([blob], AO.attachName({ name: "", type }, now || new Date()), { type }));
        return;
      }
    } catch (e) { blocked(); }
  };

  // The terminal's paste chords — Ctrl+V, Ctrl+Shift+V, Shift+Insert — kept from xterm.js (which reads
  // Ctrl+V as ^V) and left to the browser, which raises its own `paste` event: that event carries the
  // clipboard in `clipboardData` with no prompt, where a script's `clipboard.read()` costs a *Paste*
  // button in Firefox and Safari (TD-523). The keydown is never cancelled — that would cancel the paste.
  // True when the key is a paste chord.
  AO.pasteKey = function (e) {
    if (e.type !== "keydown") return false;
    const v = e.key === "v" || e.key === "V";
    return !!((e.ctrlKey && v && (e.shiftKey || !e.altKey)) || (e.shiftKey && e.key === "Insert"));
  };
  // A browser `paste` event's data, as `AO.clipPaste` reads a clipboard: non-empty `text/plain` is the
  // text's, handed to `text`; else a file (`AO.clipFileType`'s pick) is handed to `file`. True when it
  // took one.
  AO.pasteData = function (cd, { text, file }) {
    if (!cd) return false;
    const t = [...(cd.types || [])].includes("text/plain") ? cd.getData("text/plain") : "";
    if (t) { text(t); return true; }
    const files = Array.from(cd.files || []);
    const type = AO.clipFileType(files.map((f) => f.type || ""));
    const f = type && files.find((f) => f.type === type);
    if (!f) return false;
    file(f);
    return true;
  };
  // The terminal's paste event, caught on `el` (the terminal's box) in the capture phase, before
  // xterm.js's textarea pastes it itself (TD-520's doubling): read-only first, then `AO.pasteData`.
  AO.wireTermPaste = function (el, { readOnly, text, file, toast }) {
    el.addEventListener("paste", (e) => {
      e.preventDefault(); e.stopPropagation();
      if (readOnly()) { toast("watching: paste is off — Take over to type"); return; }
      AO.pasteData(e.clipboardData, { text, file });
    }, true);
  };

  // One file up the attach road in pieces (§4.4 *Attachment drop*, TD-478): sliced by `piece` (the
  // host agent's `paths.ATTACH_PIECE_BYTES`, served on the Attach button) and sent in order through
  // `post(fields)`, which answers the route's JSON. The first piece carries `total`; the host agent
  // answers an `upload` id while more is to come, and each later piece names it and its `offset`,
  // the bytes it has. `progress(pct, last)` after each middle piece, `last` when only the final piece is
  // left; `cancelled()` is asked before each
  // later piece, and true sends `{upload, cancel}` and answers null. A refusal or a broken answer
  // cancels what is half up and throws, so no `.part` waits for the hour's sweep. Answers the path.
  AO.uploadPieces = async function (f, { name, piece, post, progress, cancelled }) {
    const total = f.size;
    let upload = "", offset = 0;
    const drop = async () => { if (upload) { try { await post({ upload, cancel: "1" }); } catch (_) { /* the sweep has it */ } } };
    for (;;) {
      if (upload && cancelled()) { await drop(); return null; }
      const end = Math.min(total, offset + piece);
      let got;
      try {
        got = await post({ ...(upload ? { upload, offset } : { total }), name, file: f.slice(offset, end) });
      } catch (e) { await drop(); throw e; }
      if (got && got.path) return got.path;
      if (!got || !got.upload || !(got.bytes > offset)) { await drop(); throw new Error("the host agent answered no path"); }
      upload = got.upload; offset = got.bytes;
      progress(Math.floor((offset * 100) / total), total - offset <= piece);
    }
  };
  // Each file in pieces of `piece` bytes to `url`, a refusal thrown in the host agent's words. With
  // `held`, the Add entry form's draft (TD-630): every piece carries `held.draft` — `""` until an answer
  // names the token, which is kept there for every later piece and file.
  const postPieces = (url, piece, held) => (f, ctl) => AO.uploadPieces(f, {
    name: AO.attachName(f, new Date()), piece: piece || 2 * 1024 * 1024,
    progress: ctl.progress, cancelled: ctl.cancelled,
    post: async ({ file, name, ...fields }) => {
      const fd = new FormData();
      if (held) fd.append("draft", held.draft);
      for (const [k, v] of Object.entries(fields)) fd.append(k, String(v));
      if (file) fd.append("file", file, name);
      const r = await fetch(url, { method: "POST", body: fd });
      if (!r.ok) { let t = r.statusText; try { t = (await r.json()).detail || t; } catch (e) {} throw new Error(t); }
      const got = await r.json();
      if (held && got && got.draft) held.draft = got.draft;
      return got;
    },
  });
  // The upload `AO.wireAttach` is handed, for session `id`: to `/api/sessions/<id>/attach`. One road
  // shared by the Focus composer and the Message and Reply dialog (§4.5a, TD-530): the file lands under
  // `id`'s `attachments/`, whichever page sent it.
  AO.attachUpload = (id, piece) => postPieces(`/api/sessions/${encodeURIComponent(id)}/attach`, piece);
  // The Add entry form's (§4.5a *Add entry form: Attach / drop / paste*, TD-633): to `/api/entry/attach`,
  // into the draft folder `held.draft` names at the home (§4.4 *The Add entry form's draft*).
  AO.draftUpload = (held, piece) => postPieces("/api/entry/attach", piece, held);

  // ---- Pop out (design §4.5 screen 2 *Pop out*, §4.5a **Pop out** / **Focus** / **title**, TD-046) ----
  // A session's Focus in its own browser window, for the OS window switcher. Client-side only:
  // nothing about a window is written to the record. The window is named for the session, so a
  // second press finds it by name and raises it instead of opening another.
  AO.popName = (id) => `ao-focus-${id}`;
  // §4.2 *Unseen* (TD-1228): the look is a Focus the person can see — never the page's load, never a
  // background tab. The returned function takes each record the page renders, and `send` (the `seen`
  // action) goes when the record is unseen and `doc` is visible, and on every switch back to it while the
  // last record rendered is unseen.
  AO.unseenLook = function (doc, send) {
    let last = null;
    const look = () => { if (last && last.unseen && doc.visibilityState === "visible") send(); };
    doc.addEventListener("visibilitychange", look);
    return (v) => { last = v || last; look(); };
  };
  // `<name> · <state>`, ` · unseen` after it while the record carries the unseen mark (TD-1228), `▲ ` in front
  // while it needs the person: the switcher's one line.
  AO.focusTitle = (v) => `${v.state === "needs-you" ? "▲ " : ""}${v.name} · ${v.state_label || v.state}${v.unseen ? " · unseen" : ""}`;
  // §4.5 *A tab's icon* (TD-1155): the tab's tile follows the state its title says, from the URLs the
  // page's icon link carries (`data-icons`, read once); none, or a class with no URL, leaves it as it is
  let focusIcons;
  AO.focusIcon = (v) => {
    const link = document.querySelector("link[rel=icon]");
    if (!link) return;
    if (focusIcons === undefined) {
      try { focusIcons = JSON.parse(link.dataset.icons || "null") || null; } catch (e) { focusIcons = null; }
    }
    const url = focusIcons && focusIcons[v.state_class];
    if (url) link.href = url;
  };
  // The window's size and position are the person's, remembered per session in this browser; the
  // default fits a 100-column terminal beside the 320px side column (13px mono is ~7.8px a column).
  AO.popFeatures = function (saved) {
    const w = saved && saved.w > 200 ? saved.w : Math.round(100 * 7.8) + 320 + 14 + 40 + 30;
    const h = saved && saved.h > 200 ? saved.h : 860;
    let f = `popup,width=${w},height=${h}`;
    if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) f += `,left=${saved.x},top=${saved.y}`;
    return f;
  };
  AO.popOut = function (id) {
    const name = AO.popName(id);
    // An empty URL finds a window of that name without reloading it; a new one comes back blank and
    // is sent to the session's chromeless Focus.
    const w = window.open("", name, AO.popFeatures(store.get(`win.${id}`, null)));
    if (!w) { AO.toast("the browser blocked the window — allow pop-ups for this page", false, null, false, true); return; }
    let blank = true;
    // a window of that name showing another origin cannot be read: it is not our Focus, so send it there
    try { blank = !w.location.pathname.startsWith("/focus/"); } catch (e) { blank = true; }
    if (blank) w.location.href = `/focus/${encodeURIComponent(id)}?window=1`;
    try { w.focus(); } catch (e) { /* the browser decides */ }
  };
  // §4.5a *Focus: Open shell here* (TD-577): the shell's Focus opens beside the page it was pressed on,
  // never over it — a tab, or a window as Pop out opens one (`asWindow`: Shift, or pressed in a popped-out
  // window). The tab is opened here, in the press, before the RPC: a browser allows one only inside the
  // click. It reads *opening a shell in <dir>…* until the create answers, then goes to the shell's Focus —
  // the shell already open there when the answer says `reused` (TD-810); a refused create leaves it open,
  // reading the refusal and *close this tab*, and throws, so the press's own error path says it too.
  AO.shellHere = async function (id, dir, asWindow) {
    const what = asWindow ? "window" : "tab";
    const w = asWindow ? window.open("", "", AO.popFeatures(null)) : window.open("", "_blank");
    if (!w) { AO.toast(`the browser blocked the ${what} — allow pop-ups for this page`, false, null, false, true); return null; }
    const line = `opening a shell in ${dir || "this session's directory"}…`;
    try { w.document.title = line; w.document.body.textContent = line; } catch (e) { /* a placeholder only */ }
    let res;
    try { res = await AO.act(id, "shell-here"); } catch (e) {
      const said = `${e.message} — close this ${what}`;
      try { w.document.title = said; w.document.body.textContent = said; } catch (e2) { /* a placeholder only */ }
      throw e;
    }
    if (!res || !res.id) { try { w.close(); } catch (e) { /* gone already */ } return res; }
    if (res.reused) AO.toast("your shell here was already open — opened it", true);
    if (asWindow) w.name = AO.popName(res.id);
    w.location.href = `/focus/${encodeURIComponent(res.id)}${asWindow ? "?window=1" : ""}`;
    return res;
  };
  // Which sessions this browser holds popped out: each popped window says so on a channel between
  // this browser's own tabs, and answers when a tab asks. Another browser, or a phone, knows nothing
  // and opens Focus as it does (§4.5 *Pop out*).
  // Opened by the pages that use it (the Org, a popped Focus), not at load: every page loads this file.
  let popChanOpen;
  function popChan() {
    if (popChanOpen !== undefined) return popChanOpen;
    popChanOpen = typeof BroadcastChannel === "function" ? new BroadcastChannel("ao-popped") : null;
    if (popChanOpen) {
      popChanOpen.onmessage = (m) => {
        const d = m.data || {};
        if (d.open) AO.popped.add(d.open);
        if (d.closed) AO.popped.delete(d.closed);
        if (d.open || d.closed) AO.markPopped();
        if (d.who && AO.poppedId) popChanOpen.postMessage({ open: AO.poppedId });
      };
    }
    return popChanOpen;
  }
  AO.popped = new Set();
  // Relabel every card Focus link whose session is popped out here: *Focus window*, and back.
  AO.markPopped = function (root) {
    $$("a[data-focus]", root).forEach((a) => {
      const on = AO.popped.has(a.dataset.focus);
      if (!a.dataset.label) a.dataset.label = a.textContent;
      a.textContent = on ? `${a.dataset.label} window` : a.dataset.label;
      a.classList.toggle("popped", on);
    });
  };
  // A plain click on *Focus window* raises the window; a modifier or a middle click stays the
  // browser's, a new tab with the full page (§4.5a **Focus**).
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("a[data-focus]");
    if (!a || !AO.popped.has(a.dataset.focus)) return;
    if (ev.button !== 0 || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) return;
    ev.preventDefault();
    AO.popOut(a.dataset.focus);
  });

  // §4.5 *Browser mechanics* *The top bar is held* (TD-1187, built by TD-1192): sticky on every page (the CSS),
  // and on a phone away while the page scrolls down, back on a scroll up. The rules, first match wins, every
  // threshold strict: held (keyboard focus in the bar, or + New ▾ open) or within the bar's height of the top
  // (4 px of slack for a jittery scroll) — shown; shown, a scroll down of more than 4 px since the bar last came or
  // went sends it away; away, a scroll up of more than 4 px brings it back. `y` is clamped by the caller, so a
  // rubber-band bounce at either end moves nothing.
  AO.barAway = function (anchorY, y, barH, away, held) {
    if (held || y <= barH + 4) return { away: false, anchorY: y };
    if (!away) return y - anchorY > 4 ? { away: true, anchorY: y } : { away: false, anchorY: Math.min(anchorY, y) };
    return anchorY - y > 4 ? { away: false, anchorY: y } : { away: true, anchorY: Math.max(anchorY, y) };
  };
  AO.barDecide = function () {};  // a page without a bar (a popped-out Focus) has nothing to decide
  // `--barh` follows the bar's height (the scroll padding and every rail's `top` read it); on a wide screen
  // `decide` returns at once, so a window narrowed into a phone's width mid-session is already wired.
  AO.holdBar = function () {
    const bar = $(".topbar");
    if (!bar || !window.matchMedia) return;
    const root = document.documentElement;
    if (window.ResizeObserver) new window.ResizeObserver(() => root.style.setProperty("--barh", `${bar.offsetHeight}px`)).observe(bar);
    const phone = window.matchMedia("(max-width: 720px)");
    let away = false, anchorY = 0;
    const clampedY = () => Math.max(0, Math.min(window.scrollY, root.scrollHeight - window.innerHeight));
    const held = () => {
      const menu = $("#newmenu");
      // keyboard focus only: a tap's focus, which a phone leaves on a tapped button, does not hold the bar
      try { if (bar.querySelector(":focus-visible")) return true; } catch (e) { /* no :focus-visible: none held */ }
      return !!(menu && menu.open);
    };
    const decide = () => {
      if (!phone.matches) return;
      const got = AO.barAway(anchorY, clampedY(), bar.offsetHeight, away, held());
      away = got.away; anchorY = got.anchorY;
      bar.classList.toggle("away", away);
    };
    phone.addEventListener("change", () => { away = false; anchorY = clampedY(); bar.classList.remove("away"); });
    window.addEventListener("scroll", decide, { passive: true });
    bar.addEventListener("focusin", decide);
    // during `focusout` the leaving element still matches :focus-visible: read the bar a frame later
    bar.addEventListener("focusout", () => requestAnimationFrame(decide));
    AO.barDecide = decide;
  };

  // A *more ▾* or *Snooze* menu is drawn fixed to the viewport, placed from its summary's rect
  // (TD-121): drawn inside the card, the card's `overflow: hidden` clipped it to a sliver of border.
  // Right-aligned under the summary; above it where the space below is short; kept on screen.
  AO.placeMenu = function (r, w, h, vw, vh) {
    const gap = 4, edge = 8;
    const top = r.bottom + gap + h > vh - edge && r.top - gap - h >= edge ? r.top - gap - h : r.bottom + gap;
    const left = Math.max(edge, Math.min(r.right - w, vw - edge - w));
    return { top: Math.round(top), left: Math.round(left) };
  };
  // `toggle` does not bubble: caught on the way down. Opening one menu folds any other; a scroll
  // anywhere (a terminal's included) or a resize moves an open one with its button.
  const placeMenu = (d) => {
    const m = $(".menu", d), s = $("summary", d);
    if (!m || !s) return;
    const p = AO.placeMenu(s.getBoundingClientRect(), m.offsetWidth, m.offsetHeight, window.innerWidth, window.innerHeight);
    m.style.top = `${p.top}px`; m.style.left = `${p.left}px`;
  };
  document.addEventListener("toggle", (ev) => {
    AO.barDecide();  // + New ▾ opened or shut: the bar is back in place before its menu is placed from it
    const d = ev.target;
    if (!d.matches || !d.matches("details.more[open]")) return;
    $$("details.more[open]").forEach((o) => { if (o !== d) o.open = false; });
    placeMenu(d);
  }, true);
  const placeOpen = () => $$("details.more[open]").forEach(placeMenu);
  // the Queue card's ⋯ (§4.5 screen 12 *Three verbs: ⋯*, §4.5a *Queue card: ⋯*; TD-914): a control of its own —
  // `Enter` opens it (its summary's own press) with focus on its first name, the arrows move among its names,
  // `Esc` closes it and puts focus back on the mark. True where the key was the ⋯'s.
  AO.qDots = function (ev) {
    const d = ev.target && ev.target.closest && ev.target.closest("details.qdots");
    if (!d) return false;
    const mark = $("summary", d), items = $$('.menu [role="menuitem"]', d), at = items.indexOf(document.activeElement);
    if (ev.key === "Escape" && d.open) { d.open = false; mark.focus(); return true; }
    if ((ev.key === "ArrowDown" || ev.key === "ArrowUp") && items.length) {
      if (!d.open) d.open = true;
      const step = ev.key === "ArrowDown" ? 1 : -1;
      items[at < 0 ? (step > 0 ? 0 : items.length - 1) : (at + step + items.length) % items.length].focus();
      return true;
    }
    return false;
  };
  document.addEventListener("keydown", (ev) => { if (AO.qDots(ev)) { ev.preventDefault(); ev.stopPropagation(); } }, true);
  document.addEventListener("toggle", (ev) => {
    const d = ev.target;
    if (!d.matches || !d.matches("details.qdots[open]") || document.activeElement !== $("summary", d)) return;
    const first = $('.menu [role="menuitem"]', d); if (first) first.focus();
  }, true);
  document.addEventListener("scroll", placeOpen, true);

  // ---- whole on hover (§4.5a **subject**, *suggested answers*; §4.5 *Page loads*, TD-890) ----
  // A line clipped with an ellipsis is whole on hover, and the page sends no `title` repeating its text:
  // the title is set here, on the first hover, and only on a line that is in fact clipped.
  AO.wholeOnHover = (el) => {
    if (!el || el.title || !(el.scrollWidth > el.clientWidth)) return;
    el.title = el.textContent.trim();
  };
  document.addEventListener("mouseover", (ev) => {
    AO.wholeOnHover(ev.target.closest?.(".mailrow .subj, .msgsubj, .btn.answer .alabel"));
  });
  window.addEventListener?.("resize", placeOpen);  // `?.`: the node probes have no real window

  // the editor button (vscode://, or the person's own `open_in:` scheme, design §5): hand the URL to
  // the protocol handler without navigating this tab away (a plain click replaced the Org with a
  // blank page when the handler declined — first-use finding).
  AO.openEditor = function (url, label, quiet) {
    const f = document.createElement("iframe"); f.style.display = "none"; f.src = url;
    document.body.appendChild(f); setTimeout(() => f.remove(), 3000);
    if (!quiet) AO.toast(`opening in ${label || "the editor"}…`, true);
  };
  // A file link is two launches (§4.6 *The press is two launches*, TD-532): the session's folder link
  // as the Session card's button sends it, then the file form, so the file lands in the worktree's
  // window — brought forward when one holds the folder, just opened when none does. The wait covers
  // the protocol handler's turn, not the window's connection (the editor queues a file for a window
  // still connecting), and stays inside the browser's five-second activation window. Both are the
  // person's (`person.file_link`, §5; TD-536), served on the record's `editor`: `first: false` is the
  // file form alone, and `wait` the seconds between, one where unset. One toast for the pair; nothing
  // is remembered between presses.
  AO.FOLDER_WAIT = 1000;
  AO.openFile = function (editor, fileUrl, open) {
    const o = open || AO.openEditor, label = (editor && editor.label) || "the editor";
    if (!(editor && editor.url) || editor.first === false) { o(fileUrl, label); return; }
    const wait = typeof editor.wait === "number" ? editor.wait * 1000 : AO.FOLDER_WAIT;
    o(editor.url, label);
    setTimeout(() => o(fileUrl, label, true), wait);
  };
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("a.editor");
    if (!a) return;
    ev.preventDefault();
    // a file's link carries its session's folder (the recent files, TD-535): the pair; any other
    // editor link — the Session card's button, a folder — the one launch
    // a path in a transcript's turn (`data-ctrl`, TD-691) opens as the pane's does: on Ctrl or Cmd alone
    if ("ctrl" in a.dataset && !(ev.ctrlKey || ev.metaKey)) return;
    if (a.dataset.folder) AO.openFile({ url: a.dataset.folder, label: a.dataset.label, wait: a.dataset.wait ? Number(a.dataset.wait) : undefined }, a.href);
    else AO.openEditor(a.href, a.dataset.label);
  });

  // design §4.5a **Message** / Focus Inbox **Reply** (§4.10): one composer for both, a <dialog>.
  // Resolves to what to mail, or null on Cancel / an empty body.
  // design §4.5a Focus side panel **Reports** (TD-143, built by TD-150): a record's `progress` as
  // the panel's four groups. A declared claim is *in review* when it has a PR — its own `pr`, or
  // `review_pr` where the record carries its branch's (slice 3) — and *in progress* otherwise; a
  // derived entry never shares a declared one's reference (§9 invariant 10: the upsert refuses it),
  // so there is nothing to fold. Anything not done or dropped is in progress. Pure, for a test.
  AO.reportGroups = function (progress) {
    const g = { progress: [], review: [], done: [], dropped: [] };
    (progress || []).forEach((p) => {
      if (p.status === "done") g.done.push(p);
      else if (p.status === "dropped") g.dropped.push(p);
      else {
        const pr = p.status === "claimed" ? p.review_pr || p.pr : null;
        if (pr) g.review.push({ ...p, review_pr: pr });
        else g.progress.push(p);
      }
    });
    return g;
  };

  // §4.10 *When it is read* (TD-168): the composer's line for a kind, from the addressee's pair
  // (`read_when` on its record's view). Pure, so a test can call it: a reply reads as a note does,
  // and a pair the record did not carry (an older host agent) draws no line at all.
  AO.whenLine = function (pair, kind, reply) {
    const t = (pair || {})[reply || kind === "note" ? "note" : "ask"] || "";
    return t ? `When it is read: ${t}.` : "";
  };

  AO.roleLine = (o) => (!o.reply && o.line ? `Message it about ${o.line}` : "");
  // the composer's *re:* quote as words (TD-296 #4): the closed subset's inline marks — `code`,
  // [text](url), **strong**, *em* — taken off as `render.inline` draws them, so a board line's head
  // reads as the row draws it and not as `**` and backticks; every other character stays
  AO.quoteText = (t) => String(t || "")
    .replace(/(`+)(.+?)\1/g, "$2")
    .replace(/(?<!!)\[([^[\]\n]+)\]\(([^()\s]+)\)/g, "$1")
    .replace(/\*\*(?=\S)(.+?)(?<=\S)\*\*/g, "$1")
    .replace(/(^|[^*\w])\*(?=[^\s*])(.*?[^\s*])\*(?![*\w])/g, "$1$2");
  // §4.5a *Message and Reply dialog: Attach / drop / paste* (TD-530, built by TD-531): the Focus
  // composer's road on `#mailbox`, wired once, for the session the open dialog addresses (`AO.mailTo`).
  // With none — a seat with nobody in it, a board's Reply — the button is hidden, the note says why, and
  // a drop or a paste attaches nothing (the dialog reads as a closed composer). Each path goes in at the
  // caret and nothing is sent until **Mail it**. A batch belongs to the dialog it was given in: once that
  // closes, its file in flight is cancelled, inserts nothing, and the files queued behind it are never
  // sent, to that addressee or the next. `els` are the dialog's parts, handed in so it runs under node.
  AO.mailTo = "";
  AO.wireMailAttach = function (els, upload) {
    const { dlg, button, input, cancel, text, note } = els;
    let opened = 0;
    const attach = AO.wireAttach({
      button, input, compose: text, targets: [dlg], cancel,
      composer: { classList: { contains: () => !AO.mailTo } },
      fail: (m) => AO.toast(m), token: () => opened,
      upload: async (f, ctl) => {
        if (ctl.token !== opened) return null;
        const path = await upload(AO.mailTo)(f, ctl);
        return ctl.token === opened ? path : null;
      },
    });
    // the ✕ of an upload still running is pressed when the dialog closes: its rest is not wanted
    dlg.addEventListener("close", () => { opened++; if (!cancel.classList.contains("hidden")) cancel.click(); });
    return {
      attach,
      open(id) {
        AO.mailTo = id || ""; opened++;
        button.hidden = !AO.mailTo;
        if (note) { if (AO.mailTo) note.removeAttribute("title"); else note.title = "attach needs a session in the seat"; }
      },
    };
  };
  // §4.5a *Add entry form: Attach / drop / paste* (TD-630, built by TD-633): the composer's road on the
  // form's **What**, before any session exists — a drop on the box and an image pasted into it too, each
  // path at the caret. The form's files go to its draft folder at the home (§4.4 *The Add entry form's
  // draft*), its token held while the form is open: `""` until the first file's answer names it, every
  // later piece and file naming it, and each opening a new draft. A batch belongs to the opening it was
  // given in, as the Message dialog's does: once the form closes its file in flight inserts nothing and
  // the rest are never sent. `refuse(words)` refuses Attach in place (a repo whose team runs on a node:
  // *this call does not cross the link*) — the note says the words, a drop or a paste attaches nothing.
  // `draft()` is what a way out hands on, `""` where nothing was attached.
  AO.wireEntryAttach = function (els, upload) {
    const { dlg, button, input, cancel, text, note } = els;
    const hint = note.textContent, tip = button.title;
    let opened = 0, refused = "", held = { draft: "" };
    const attach = AO.wireAttach({
      button, input, compose: text, targets: [text], cancel,
      composer: { classList: { contains: () => !!refused } },
      fail: (m) => AO.toast(m), token: () => opened,
      upload: async (f, ctl) => {
        if (ctl.token !== opened) return null;
        const path = await upload(held)(f, ctl);
        return ctl.token === opened ? path : null;
      },
    });
    dlg.addEventListener("close", () => { opened++; if (!cancel.classList.contains("hidden")) cancel.click(); });
    const refuse = (words) => {
      refused = words || "";
      button.disabled = !!refused; button.title = refused || tip;
      if (button.dataset) { if (refused) button.dataset.refused = "1"; else delete button.dataset.refused; }
      note.textContent = refused || hint;
    };
    return {
      attach, refuse,
      open() { opened++; held = { draft: "" }; refuse(""); },
      draft: () => held.draft,
    };
  };
  let mailAttach = null;
  AO.compose = function (o) {
    const dlg = $("#mailbox");
    if (!mailAttach && $("#mailattach")) {
      const button = $("#mailattach");
      mailAttach = AO.wireMailAttach(
        { dlg, button, input: $("#mailattachfile"), cancel: $("#mailattachcancel"), text: $("#mailtext"), note: $("#mailnote") },
        (id) => AO.attachUpload(id, Number(button.dataset.piece)),
      );
    }
    if (mailAttach) mailAttach.open(o.id);
    $("#mailtitle").textContent = o.reply ? `Reply to ${o.to}` : `Message ${o.to}`;
    $("#mailkindrow").hidden = !!o.reply;
    // §4.8 (TD-171): the role's line, the definition's words as text; a Reply shows none — the
    // sender chose already
    const rl = $("#mailrole");
    if (rl) { rl.textContent = AO.roleLine(o); rl.hidden = !rl.textContent; }
    const q = AO.quoteText(o.quote);
    $("#mailquote").textContent = q ? `re: “${q.length > 160 ? q.slice(0, 160) + "…" : q}”` : "";
    $("#mailkind").value = "ask"; $("#mailabout").value = ""; $("#mailtext").value = o.text || "";  // an ask by default (§4.5a **Message**, 2026-09-25)
    // §4.10 *When it is read* (TD-168): the addressee's pair, from its record's view, never a
    // request; a reply reads as a note does, and switching the kind swaps the sentence
    const when = $("#mailwhen");
    if (when) {
      const show = () => {
        when.textContent = AO.whenLine(o.when, $("#mailkind").value, o.reply); when.hidden = !when.textContent;
      };
      $("#mailkind").onchange = show; show();
    }
    return new Promise((resolve) => {
      dlg.addEventListener("close", () => {
        const text = $("#mailtext").value;
        // `empty`: a send with no words is still a send (Hold…'s line is optional, §4.4 *Hold*)
        resolve(dlg.returnValue === "send" && (text.trim() || o.empty) ? { text, kind: $("#mailkind").value, about: $("#mailabout").value.trim() } : null);
      }, { once: true });
      dlg.returnValue = ""; dlg.showModal(); $("#mailtext").focus();
    });
  };

  // design §4.5a **Inbox row: FYI** → **Put on the board** (TD-140): the page's form (`#boardadd`),
  // opened with the row's board and text. Resolves to the agent's answer once the line is on the
  // board, or null on Cancel. A refusal is drawn in the form and leaves it open, so the person can
  // pick another board or fix the date rather than start again from the row.
  // a board row's line text, written once on the row rather than on each of its buttons (TD-738)
  const lineText = (b) => (b.closest(".mailrow") || b).dataset.text || "";
  AO.boardAdd = function (b, onSend) {
    const dlg = $("#boardadd");
    if (!dlg) { AO.toast("Put on the board: this page has no form for it"); return Promise.resolve(null); }
    const sel = $("#baboard"), text = $("#batext"), due = $("#badue"), err = $("#baerr"), go = $("#bago");
    err.hidden = true; err.textContent = "";
    if (sel) {
      const want = b.dataset.board || "";
      const opts = [...sel.options].map((o) => o.value).filter(Boolean);
      sel.value = opts.includes(want) ? want : opts.length === 1 ? opts[0] : "";
    }
    // the entry's first paragraph, on one line: a board item is one line (§4.4)
    if (text) text.value = String(b.dataset.text || "").split(/\n\s*\n/)[0].split(/\s+/).filter(Boolean).join(" ");
    if (due) due.value = "";
    dlg.querySelectorAll("[data-bawhen]").forEach((w) => { w.onclick = () => { due.value = boardDue(w.dataset.bawhen); }; });
    return new Promise((resolve) => {
      let done = null;
      // Put it on is the form's one submit, so Enter in the date confirms, and Ctrl+Enter (⌘+Enter)
      // in the text, where a plain Enter adds a line (TD-281); Cancel and Esc close with nothing sent
      if (text) text.onkeydown = (e) => {
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); dlg.querySelector("form").requestSubmit(); }
      };
      const cancel = $("#bacancel");
      if (cancel) cancel.onclick = () => dlg.close("cancel");
      dlg.querySelector("form").onsubmit = async (ev) => {
        ev.preventDefault();
        if (!go || go.disabled) return;
        // the box's lines joined into the board's one line (§4.4, TD-281)
        const words = text.value.split(/\s+/).filter(Boolean).join(" ");
        const body = { action: "add", msg: b.dataset.msg, board: sel.value, text: words, due: due.value };
        const miss = !body.board ? "pick a board" : !body.text ? "say what is needed" : !body.due ? "give it a Due date" : "";
        if (miss) { err.textContent = miss; err.hidden = false; return; }
        go.disabled = true;
        if (onSend) onSend();  // the row is marked once the form sends (§4.5 screen 6, TD-340)
        try {
          done = await act("person", "board", body);
          dlg.close("done");
        } catch (e) {
          err.textContent = `not put on the board: ${e.message}`; err.hidden = false;
          const r = b.closest(".mailrow"); if (r) { AO.unPend(r); delete AO.inflight[r.dataset.msg]; }  // a send again marks it again
        } finally { go.disabled = false; }
      };
      dlg.addEventListener("close", () => resolve(done), { once: true });
      dlg.returnValue = ""; dlg.showModal(); (text || dlg).focus();
    });
  };

  // §4.5 screen 6 *A control answers the press* (TD-338, TD-340) and §4.5a **Inbox row: pending**: the
  // verb a pending row shows in place of its age, one table keyed by the control's wire name (a board
  // row's by `board_<its action>`), the wire name itself the fallback; and what a refused press was not
  const PRESS_VERBS = {
    board_done: "checking off…", board_snooze: "snoozing…", board_decide: "deciding…", board_reply: "sending…",
    board_notright: "deciding…", board_add: "writing…", ledger: "deciding…", ledger_reply: "deciding…", ledger_start: "starting…", ledger_release: "releasing…", ledger_hold: "holding…", snooze: "snoozing…", attention_snooze: "snoozing…",
    dismiss: "dismissing…", identity_ack: "dismissing…", clear_work: "dismissing…",
    clear_mark: "dismissing…", clear_promote: "dismissing…", unmail: "deleting…", allow: "sending…", deny: "sending…",
    reply: "sending…", answer: "sending…", gowithit: "sending…", hand_look: "sending…", identity_log: "logging…",
    suspend: "suspending…", promote: "promoting…", ci_rerun: "re-running…", work_start: "starting…", restart: "restarting…",
    resume: "resuming…", "reopen-push": "resuming…", "resume-form": "resuming…", pause: "pausing…",
  };
  const PRESS_NOT = {
    board_done: "checked off", board_snooze: "snoozed", snooze: "snoozed", attention_snooze: "snoozed",
    dismiss: "dismissed", identity_ack: "dismissed", clear_work: "dismissed",
    clear_mark: "dismissed", clear_promote: "dismissed", unmail: "deleted", allow: "allowed", deny: "denied",
    gowithit: "sent", identity_log: "logged", restart: "restarted", resume: "resumed", "reopen-push": "resumed",
  };
  // the presses that take their row away: it leaves as the request leaves (rule 3); a state or board
  // row leaves on any answer but Suspend and a decide, as it did on the answer before
  const PRESS_LEAVES = ["board_done", "board_snooze", "snooze", "attention_snooze", "dismiss", "identity_ack",
    "clear_work", "clear_mark", "clear_promote", "unmail", "allow", "deny", "gowithit", "identity_log", "restart", "resume",
    "reopen-push"];
  AO.pressKey = (action, boardAct) => (action === "board" ? `board_${boardAct || ""}` : action);
  AO.pressVerb = (key) => PRESS_VERBS[key] || key;
  AO.pressErrs = {};  // a refused press's words by entry id, until that row's next press or a reload
  // the presses still in flight, by entry id: a poll's swap must not draw back a row the press took
  // away, nor draw one that stays as pressable, while its request is out (review of #1144)
  AO.inflight = {};
  AO.markPending = function (row, verb) {
    if (row.classList.contains("pending")) return;  // a form sent twice: the row is marked once
    row.classList.add("pending");
    row.setAttribute("aria-busy", "true");
    row.querySelectorAll("button, .btn").forEach((x) => { if (!x.disabled) { x.disabled = true; x.dataset.pressoff = "1"; } });
    const age = row.querySelector(".st.age, [data-slot], .mhead .meta");  // its age, or a board row's due words
    if (age) { age.dataset.was = age.textContent; age.dataset.wasSince = age.dataset.since || ""; delete age.dataset.since; age.textContent = verb; }
  };
  AO.unPend = function (row) {  // a row the press left in place, once its answer is in and nothing redrew it
    row.classList.remove("pending");
    row.removeAttribute("aria-busy");
    row.querySelectorAll("[data-pressoff]").forEach((x) => { x.disabled = false; delete x.dataset.pressoff; });
    const age = row.querySelector("[data-was]");
    if (age) { age.textContent = age.dataset.was; if (age.dataset.wasSince) age.dataset.since = age.dataset.wasSince; delete age.dataset.was; delete age.dataset.wasSince; }
  };

  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-act], [data-copy]");
    if (!b) return;
    // a write that rejects or throws (no clipboard outside a secure context) is refused aloud, as copyWith's (TD-1292)
    if (b.dataset.copy) {
      Promise.resolve().then(() => navigator.clipboard.writeText(b.dataset.copy)).then(
        () => AO.toast(b.dataset.copied || "copied", true), () => AO.toast("clipboard blocked (needs https or localhost)", false));
      return;
    }
    const id = b.dataset.id, action = b.dataset.act;
    let action2 = null;  // the endpoint's name when it differs from the button's (controllers chip)
    // design §4.5a **Inbox row: state** (TD-069 step 2): a state row on the Inbox page carries the
    // card's own controls, so the press goes to the card's own route — and the row, which is the
    // state and not a copy of it, leaves the moment the state is answered.
    // a board row (TD-069 step 3) goes the way a state row does: out on the answer, back on a refusal
    const staterow = b.closest(".staterow, .boardrow");
    // §4.5 screen 6 *A control answers the press* (TD-340): in the frame before the request leaves, the
    // row is marked pending, and a row the press takes away leaves with a toast that waits for the
    // answer; a press that asks first (a prompt, a composer) is marked once it is answered
    const row = b.closest(".mailrow");
    const key = AO.pressKey(action, b.dataset.boardAct);
    const keeps = ["suspend", "board_decide", "board_reply", "board_notright", "board_add", "ledger", "ledger_reply"].includes(key);
    const leaves = !!row && !keeps && (PRESS_LEAVES.includes(key) || !!staterow);
    let waiting = null, left = false;
    const say = (text, ok, href) => {
      if (!waiting) return AO.toast(text, ok, href);
      const w = waiting; waiting = null;
      return w.settle(text, ok, href);
    };
    const pressed = () => {
      if (!row || !row.isConnected) return;
      delete AO.pressErrs[row.dataset.msg];
      const err = row.querySelector(".rowerr"); if (err) { err.hidden = true; err.textContent = ""; }
      const verb = AO.pressVerb(key);
      AO.markPending(row, verb);
      if (row.dataset.msg) AO.inflight[row.dataset.msg] = { leaves, verb };
      if (!leaves) return;
      // the control goes with its row, and while it holds the focus the refresh would decline to redraw
      if (row.contains(document.activeElement)) document.activeElement.blur();
      AO.handRing(row); row.remove(); left = true;
      const what = verb.replace(/…$/, "");
      waiting = AO.toast(action === "board" ? `${what} — landing on the board…` : `${what}…`, true, null, true);
    };
    if (b.dataset.confirm && !confirm(b.dataset.confirm)) return;
    if (action === "popout") { const m = b.closest("details.more"); if (m) m.open = false; AO.popOut(id); return; }
    // A choice made in a row's *more ▾* or *Snooze* menu folds that menu — and only a menu: the
    // nearest `<details>` of any kind used to be closed, and a control that sits in no menu (an FYI
    // row's Dismiss, a snoozed row's own press) has the *section* as its nearest one, so dismissing
    // an entry closed the FYI list under the person (Paul, 2026-09-20; TD-079).
    const menu = b.closest("details.more"); if (menu) menu.open = false;
    try {
      // §4.5a *Focus: Open shell here* (TD-577): the pressing page stays; the shell opens beside it
      if (action === "shell-here") { await AO.shellHere(id, b.dataset.dir, ev.shiftKey || !!AO.poppedId); return; }
      let body = {};
      // The Focus header's toggle carries the mode it is drawn for (TD-096: it is re-drawn in place
      // from the pushed delta, and `.btn.on` is a style); a card's *more* entry carries `.on`.
      if (action === "mode") body = { unattended: "unattended" in b.dataset ? b.dataset.unattended !== "1" : !b.classList.contains("on") };
      // design §4.5a: **Drop** on a claimed progress item, and the grants chip (§4.8, TD-028 step 4)
      if (action === "drop") body = { ref: b.dataset.ref };
      if (action === "wrapup") body = { key: AO.mintKey() };  // one per press: a repeat types it once (TD-806)
      // design §4.5a **Deny** (TD-117): the reason box beside this Deny, if one was filled
      if (action === "deny") { const w = b.parentElement && b.parentElement.querySelector("input.denywhy"); body = AO.denyBody(w && w.value); }
      // a line per open prompt answers its own entry (§4.2 *Every entry is answerable where it is drawn*, TD-950)
      if ((action === "allow" || action === "deny") && b.dataset.call) body.call = b.dataset.call;
      if (action === "grants") body = b.classList.contains("off") ? { add: [b.dataset.grant] } : { remove: [b.dataset.grant] };
      // design §4.5a Focus **controllers** chip (§4.8, TD-036): remove one by clicking it, add one
      // by id. The agent decides what is allowed; a refusal comes back as the toast below.
      if (action === "uncontrol") { action2 = "controllers"; body = { remove: [b.dataset.who] }; }
      // design §4.5a Focus header **stops** badge (§6, TD-026): the same shape — the person types
      // a time, the agent parses it and says no if it cannot. Empty clears it, deliberately: a
      // session that should run on is a decision, not a restart.
      // design §4.5a **starts** note / **Start now** (§6 *Start time*, TD-152): `now`, or the time
      // asked for when the note itself is pressed on Focus
      if (action === "start") {
        let at = b.dataset.at || "now";
        if (b.dataset.ask) {
          const when = prompt("Start this session at… (20:00, +2h, an ISO time, or now)", "now");
          if (!when) return;
          at = when.trim();
        }
        body = { at };
      }
      if (action === "stop") {
        // Filled from the record, not from the badge: the badge reads "stops Mon 06:00" once the
        // stop is not today and gains "· wrap-up sent" after the agent has asked, and both of
        // those come back as a time the agent refuses. The record's UTC instant, shown in the
        // person's own clock as a local ISO string, round-trips exactly.
        const iso = b.dataset.until;
        let now = "";
        if (iso) {
          const d = new Date(iso);
          if (!isNaN(d)) now = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
        }
        const when = prompt("Stop this session at… (06:00, +8h, an ISO time; empty to clear)", now);
        if (when === null) return;
        body = { until: when.trim() };
      }
      // design §4.5a **Message**, Focus Inbox **Reply** and delete (§4.10): mail, never a send
      if (action === "message" || action === "reply") {
        const m = await AO.compose({
          to: b.dataset.name || id, reply: action === "reply", quote: b.dataset.quote, line: b.dataset.line || "",
          // the addressee's session for Attach (TD-531): a Message's own card, a Reply's sender — none on a seat
          id: action === "reply" ? b.dataset.from || "" : b.dataset.seat ? "" : id,
          when: { ask: b.dataset.whenAsk || "", note: b.dataset.whenNote || "" }, text: b.dataset.begun || "",
        });
        if (!m) return;
        // §4.5a **Inbox row: a look** (TD-292): **Not right…** begins the reply with the form, and
        // the form's prefix is kept whatever case it was retyped in, as a board row's is
        if (b.dataset.begun === "Not right: ") m.text = `Not right: ${m.text.trim().replace(/^not right\s*:?\s*/i, "")}`.trim();
        body = action === "reply" ? { reply_to: b.dataset.msg, text: m.text } : m;
      }
      // design §4.5a **Inbox row: suggested answers** (§4.10, TD-070): a press is an ordinary
      // reply — the same route, the same RPC, the same wake — and what it sends is **the index**,
      // never the label. The server looks the text up from the entry it holds, so a tampered DOM
      // cannot make the person "say" something else under a given index, and the RPC re-checks
      // that the two agree. No confirm: a reply is mail, and a wrong press is followed by another.
      if (action === "answer") { action2 = "reply"; body = { reply_to: b.dataset.msg, answer: Number(b.dataset.index) }; }
      if (action === "unmail") body = { msg: b.dataset.msg };
      // design §4.5a **Inbox row: identity alarm** (§4.8a): a record's list, or — with no id — the
      // host's own. A person's act; the agent refuses it to every session. The control is
      // **Dismiss** and the wire name is `identity_ack`: a wire name is not a control, so the
      // rename of 2026-09-20 did not touch it (§4.5a).
      if (action === "identity_ack") body = { id: b.dataset.who || "" };
      // §4.8a *An alarm's answers* (TD-077 a2): **Suspend** — a person's own act on a session, and
      // the one control on an alarm row that **leaves the row standing**: it stops the session, it
      // does not answer the alarm. The confirm is the page's own words (the global gate reads
      // `data-confirm` before this runs), and `why` is left to the agent, which composes it from
      // the alarm's own fields — a page that wrote its own reason would be writing the record.
      if (action === "suspend") body = { id: b.dataset.who || "" };
      // §4.8a *An alarm's answers* (TD-077 b): **Log TD** — an answer, so the row goes. The agent
      // picks the controller and writes the words; the page sends only whose alarms they are.
      if (action === "identity_log") body = { id: b.dataset.who || "" };
      // design §4.5a **Inbox row: promote** (TD-132 slice 3, TD-226 slice 3): **Promote** and a failure
      // or held row's **Dismiss**, the person's own, to `/api/person/<action>` with the repo alone
      if (action === "promote" || action === "clear_promote") body = { repo: b.dataset.repo };
      // design §4.5a **Inbox row: CI not starting** (TD-687): **Re-run**, the person's own, with the account alone
      if (action === "ci_rerun") body = { owner: b.dataset.owner };
      // design §4.5a **Inbox row: team start** (§6 rule 8, TD-227): **Dismiss** is `clear_work` with the
      // team alone; **Start** is the team card's Start — the same route, its refusal in its own words
      if (action === "clear_work") body = { team: b.dataset.team };
      // §4.5a **Inbox row: cadence check failed** / **merged without its read** (TD-258): **Dismiss**
      // is `clear_mark` on the member's record — the PR for the first, every standing crossing for the second
      if (action === "clear_mark") body = { sid: b.dataset.sid, kind: b.dataset.kind, pr: b.dataset.pr ? Number(b.dataset.pr) : null };
      // a team that runs on (§6 rule 8 *A member that finished while its team runs on*, TD-466): **Start**
      // is `work_start` with the team, which replays the named members alone; a bound's refusal is the row's words
      if (action === "work_start" && b.dataset.running) body = { team: b.dataset.team };
      else if (action === "work_start") {
        const team = b.dataset.team;
        pressed();
        const r = await fetch(`/api/teams/${encodeURIComponent(team)}/start`, { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
        let o = {}; try { o = await r.json(); } catch (e) {}
        if (!r.ok) throw new Error(o.detail || r.statusText);
        say(o.text || `${team}: ${(o.sessions || []).length} session${(o.sessions || []).length === 1 ? "" : "s"} started`, true);
        (o.notes || []).forEach((w) => say(`${team}: ${w}`));
        if (typeof AO.refreshInboxPage === "function") AO.refreshInboxPage();
        return;
      }
      // design §4.5a **Inbox row** controls (§4.10, TD-069 step 1): the person's own acts on their
      // own inbox. Each posts to `/api/person/<action>`, which calls the RPC caller-less; the agent
      // is the one that decides what may be done, and its refusal comes back as a toast.
      if (["pause", "resume", "gowithit"].includes(action)) body = { msg: b.dataset.msg };
      // §4.5a **Send to reviewer** (TD-292 slice 4b): the look and its sender's team — the server
      // reads that team's techlead seat from `org.yml`, and the host agent's refusal is the toast
      if (action === "hand_look") body = { msg: b.dataset.msg, team: b.dataset.team };
      // a snoozed row's *now* (§4.10 *Snooze*, TD-373): no `until` clears it, back in its section
      if (action === "snooze" && b.dataset.when === "now") body = { msg: b.dataset.msg };
      else if (action === "snooze") {
        const until = snoozeUntil(b.dataset.when);
        if (!until) return;
        body = { msg: b.dataset.msg, until };
      }
      // design §4.10 *The Inbox is a queue* (TD-079 step 2): **Dismiss** — the one way a `note`,
      // an outcome debt or a trail entry leaves. A list of ids, because *Dismiss all* sends the
      // ones on screen; one press sends a list of one, through the same route and the same RPC.
      if (action === "dismiss") body = { msg: [b.dataset.msg] };
      // design §4.5a **Due strip / Inbox board row** → **Snooze ▾** / **Done** on a board row (§4.4, TD-069
      // step 3): the host agent's one-line edit, committed in that repo. The row sends back what the
      // reader gave it — board, line, text — so the agent can refuse a line that has moved on.
      if (action === "board") {
        // …and its id (§4.4 *A board line's id*, TD-603), by which the agent finds the line first
        body = { action: b.dataset.boardAct, board: b.dataset.board, line: Number(b.dataset.line), text: lineText(b), key: b.dataset.key || "" };
        if (body.action === "snooze") {
          const due = boardDue(b.dataset.when, b.dataset.due);
          if (!due) return;
          body.due = due;
        }
        // **answers** / **Go with it** (§4.4 *Decide*, TD-255): the answer pressed, and the item's
        // answers as the reader gave them to the row — the agent holds the one to the other
        if (body.action === "decide") { body.answer = b.dataset.answer; body.answers = JSON.parse(b.dataset.answers || "[]"); }
      }
      // §4.5a **Inbox row: state**: a state row's snooze. It is keyed on the record **and the row
      // kind** — the home has no mail entry to hang it on — and no `until` is the clear.
      if (action === "attention_snooze") {
        body = { id: b.dataset.sid, kind: b.dataset.row };
        // the restart row's **Dismiss** (§4.5a, TD-103): the store keeps `dismissed:<the mark's at>`
        if (b.dataset.until) body.until = b.dataset.until;
        if (b.dataset.when && b.dataset.when !== "now") {  // *now*: no `until`, the clear
          const until = snoozeUntil(b.dataset.when);
          if (!until) return;
          body.until = until;
        }
      }
      if (action === "control-add") {
        const who = prompt("Which session may act on this one? (its id or name from ao status)");
        if (!who) return;
        action2 = "controllers"; body = { add: [who.trim()] };
      }
      // design §4.5a **Resume** / **Resume with changes…** / **Reopen and push** (TD-081 step 2).
      // One press: the server builds the create from the record and answers either the new
      // session's id or the filled-in form to finish by hand — *it is not a guess*. **Resume with
      // changes…** and **Reopen and push** are the same route: the first asks for the form
      // outright, the second adds the page's own first prompt.
      // design §4.5a **Due strip / Inbox board row** → **Reply** (§4.4, TD-142): the mail composer, the
      // line quoted; what it sends is written on the line by `board_reply`. The row stays — a reply
      // is not Done — and the refresh brings it back with the reply on it. `refs` are the reader's,
      // handed as they came: the home mails each live lease holder on one of them (TD-142).
      if (action === "board_reply") {
        const m = await AO.compose({ to: b.dataset.name || "the board", reply: true, quote: lineText(b) });
        if (!m) return;
        let refs = [];
        try { refs = JSON.parse(b.dataset.refs || "[]"); } catch (_) { refs = []; }
        pressed();
        const res = await act("person", "board", {
          action: "reply", board: b.dataset.board, line: Number(b.dataset.line), text: lineText(b), key: b.dataset.key || "", reply: m.text, refs,
        });
        const to = (res.sent || []).map((x) => `${x.session} (holds ${x.ref})`).join(", ");
        say(to ? `written on the board · sent to ${to}` : res.note || "written on the board", true);
        if (typeof AO.refreshInboxPage === "function") AO.refreshInboxPage();
        return;
      }
      // design §4.5a **Works** / **Not right…** (§4.4 *Decide*, TD-255 slice 3): a live look's second
      // answer. The Reply composer opens with *Not right:* begun; what is sent is the `decide`, one
      // write. Then the page's second call hands an entry to the repo's techlead, as **Add entry…**
      // does (`entry_add`), its first line the item's head and the person's words — after the
      // decide has committed, and a refusal there is toasted: the decision stands.
      if (action === "board_notright") {
        const m = await AO.compose({ to: b.dataset.name || "the board", reply: true, quote: lineText(b), text: "Not right: " });
        if (!m) return;
        const said = m.text.split(/\s+/).filter(Boolean).join(" ");
        // the prefix is the form's, whatever case it was retyped in
        const answer = `Not right: ${said.replace(/^not right\s*:?\s*/i, "")}`.trim();
        pressed();
        await act("person", "board", {
          action: "decide", board: b.dataset.board, line: Number(b.dataset.line), text: lineText(b), key: b.dataset.key || "",
          answer, answers: JSON.parse(b.dataset.answers || "[]"),
        });
        let handed = "", refused = false;
        try {
          const r = await fetch("/api/entry/hand", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ repo: b.dataset.repo, type: "debt", words: `${b.dataset.head} — ${answer}` }) });
          const j = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(j.detail || r.statusText);
          handed = j.text || "handed to the techlead";
        } catch (e) {
          handed = `no entry was handed on: ${e.message}`; refused = true;
        }
        say(`decided: ${answer} — landed on the board on origin · ${handed}`, !refused);
        if (typeof AO.refreshInboxPage === "function") AO.refreshInboxPage();
        return;
      }
      // design §4.5a **Inbox row: ledger entry** (TD-565): an answer sends its index, **Go with it** the
      // default, **Reply** the composer's words — each `ledger_decide`, one decided line written on the
      // repo's board. The row stays, pending, until the reading lists that line and the refresh drops it.
      if (action === "ledger" || action === "ledger_reply") {
        const want = { repo: b.dataset.repo, id: b.dataset.ref };
        // **Done…** / **Back to design…** on any open row (§4.5 screen 12 *any open row*, TD-905): a box for
        // one line of words, then the road — the home tells the entry's holders and its PR's reader, clears
        // a person's hold, and writes *done — <words>* or *back to design — <words>* as one decided line
        if (b.dataset.road) {
          const m = await AO.compose({ to: b.dataset.name || "the board", reply: true, quote: b.dataset.quote, empty: true });
          if (!m) return;
          want.road = b.dataset.road; want.words = m.text;
          pressed();
          const res = await act("person", "ledger", want);
          const told = (res.told || []).length ? ` · told ${res.told.join(", ")}` : "";
          say(`decided: ${res.decided || b.dataset.road} — written on the board on origin, ${b.dataset.ref}'s work order${told}`, true);
          if (typeof AO.refreshInboxPage === "function") AO.refreshInboxPage();
          return;
        }
        if (action === "ledger_reply") {
          const m = await AO.compose({ to: b.dataset.name || "the board", reply: true, quote: b.dataset.quote });
          if (!m) return;
          want.words = m.text;
        } else if (b.dataset.words) want.words = b.dataset.words;  // Done, Lift the hold: fixed words (TD-771)
        else if (b.dataset.go) want.go = true;
        else want.answer = Number(b.dataset.index);
        pressed();
        const res = await act("person", "ledger", want);
        say(`decided: ${res.decided || b.dataset.answer} — written on the board on origin, ${b.dataset.ref}'s work order`, true);
        if (typeof AO.refreshInboxPage === "function") AO.refreshInboxPage();
        return;
      }
      // design §4.5a *Inbox row: held entry* → **Release** (TD-736): the Repo page's `td_hold` with
      // `release`, the person's own act on the home's record; the row leaves on the refresh
      // **Hold…** (§4.4 *Hold*, §4.5 screen 12, TD-905): an optional line of words, the record's `why`,
      // drawn *held (person) — <why>*; the person's own act on the home's record, no ledger edit
      if (action === "ledger_hold") {
        const m = await AO.compose({ to: `the hold on ${b.dataset.ref}`, reply: true, quote: b.dataset.quote, empty: true });
        if (!m) return;
        pressed();
        const got = await fetch("/api/ledger/hold", {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ repo: b.dataset.repo, id: b.dataset.ref, why: m.text || "" }),
        });
        if (!got.ok) { let t = got.statusText; try { t = (await got.json()).detail || t; } catch (e) {} throw new Error(t); }
        say(AO.heldWords(b.dataset.ref, await got.json().catch(() => ({}))), true);
        if (typeof AO.refreshInboxPage === "function") AO.refreshInboxPage();
        return;
      }
      if (action === "ledger_release") {
        pressed();
        const got = await fetch("/api/ledger/hold", {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ repo: b.dataset.repo, id: b.dataset.ref, release: true }),
        });
        if (!got.ok) { let t = got.statusText; try { t = (await got.json()).detail || t; } catch (e) {} throw new Error(t); }
        say(`${b.dataset.ref} released: pickable now`, true);
        if (typeof AO.refreshInboxPage === "function") AO.refreshInboxPage();
        return;
      }
      // design §4.5a *Inbox row: ledger entry* → **Start session** / **Open session** (TD-678), and a Queue card's
      // (TD-912): one press —
      // the session that holds the entry or its name (`focus`), the one it started (`id`), or the New
      // session form filled in with the reason (`form`), as **Resume**'s press lands
      if (action === "ledger_start") {
        pressed();
        const got = await fetch("/api/ledger/start", {
          method: "POST", headers: { "content-type": "application/json" },
          // a Queue card's press names its card (TD-912): the road checks the entry is the card's `start`; an
          // item's names the item too (TD-1246), which the prompt names first
          body: JSON.stringify({
            repo: b.dataset.repo, id: b.dataset.ref,
            ...(b.dataset.card ? { card: b.dataset.card } : {}), ...(b.dataset.item ? { item: b.dataset.item } : {}),
          }),
        });
        if (!got.ok) { let t = got.statusText; try { t = (await got.json()).detail || t; } catch (e) {} throw new Error(t); }
        const r = await got.json();
        if (r.form) { say(`start session needs the form: ${r.why}`, true); location.href = r.form; return; }
        const to = `/focus/${r.focus || r.id}${AO.poppedId ? "?window=1" : ""}`;
        // an item's **Open session** puts its id on the clipboard for the person to paste, typing nothing into the
        // session (§4.5 screen 12 *Started from an item*); refused (plain http off localhost), the toast shows it
        if (r.focus && b.dataset.item) {
          try { await navigator.clipboard.writeText(b.dataset.item); }
          catch (e) {
            if (row && row.isConnected) AO.unPend(row);  // the page stays: its row is pressable again
            AO.toast(`copy ${b.dataset.item} — the browser refused the clipboard`, false, to, false, true);
            return;
          }
          say(`${b.dataset.item} copied — paste it into your session`, true);
        }
        if (!r.focus) say(`started ${r.name || r.id} on ${b.dataset.item || b.dataset.ref}`, true);
        location.href = to;
        return;
      }
      if (action === "board_add") {
        const res = await AO.boardAdd(b, pressed);
        if (!res) return;
        say(res.dismiss_refused
          ? `on the board, committed — but the entry stayed: ${res.dismiss_refused}`
          : "on the board — landed on origin; the entry is dismissed", true);
        if (typeof AO.refreshInboxPage === "function") AO.refreshInboxPage();
        return;
      }
      if (action === "resume-form") {
        pressed();
        const r = await act(id, "resume", { form: true });
        location.href = r.form || `/new`;
        return;
      }
      if (action === "resume" || action === "reopen-push") {
        pressed();
        const r = await act(id, "resume", { push: action === "reopen-push" });
        if (r.form) { say(`resume needs the form: ${r.why}`, true); location.href = r.form; return; }
        say("resumed — same name, same record, its mail came with it", true);
        location.href = `/focus/${r.id}${AO.poppedId ? "?window=1" : ""}`;
        return;
      }
      pressed();
      const res = await act(id, action2 || action, body);
      if (action === "restart") {
        say(`restarted from its launch record, as it was started — ${res.unattended ? "unattended" : "attended"}`, true);
        if (typeof AO.refreshInboxPage === "function") AO.refreshInboxPage();
      }
      if (action === "remove") { const c = $(`#card-${CSS.escape(id)}`); if (c) { AO.handRing(c); c.remove(); } if (location.pathname.startsWith("/focus/") && !AO.poppedId) location.href = "/"; }
      if (action === "allow" || action === "deny") say(`${action}${body.reason ? " with your reason" : ""}: sent through the hook`, true);
      if (action === "drop") say(`${b.dataset.ref}: dropped`, true);
      if (action === "wrapup") say("wrap-up sent — it finishes, pushes and reports; you close it when Ready to close passes", true);
      // an orphaned question's answer (§4.10, TD-216): no reply entry — the home wrote it on the board
      // and mailed the holders, and `note` is its sentence, the row's standing as a result
      const orphanNote = ["reply", "answer", "gowithit"].includes(action) && res.board ? res.note : "";
      if (orphanNote) say(orphanNote, true);
      else if (action === "message" || action === "reply") say(`mailed to ${(res.delivered || []).join(", ")} — lands in the inbox, nothing typed`, true);
      if (action === "answer" && !orphanNote) say(`answered ${(res.delivered || []).join(", ")} — the reply is the answer you pressed`, true);
      if (action === "unmail") say(res.declined ? "declined — the sender is told (design §4.10)" : "deleted from this inbox", true);
      if (["message", "reply", "answer", "unmail"].includes(action) && typeof AO.refreshInbox === "function") AO.refreshInbox();
      if (action === "snooze") say(b.dataset.when === "now" ? "back in its section" : "snoozed — it comes back at that time; the sender is not told", true);
      if (action === "hand_look") {
        say(`sent to ${b.dataset.name || res.to || "the reviewer"} — set aside until it reports, then back with its reading`, true);
        if (typeof AO.refreshInboxPage === "function") AO.refreshInboxPage();
      }
      if (action === "pause") say("paused — the sender is told not to take its default yet", true);
      if (action === "resume") say("resumed — the clock runs again, with what was left", true);
      if (action === "gowithit" && !orphanNote) say("go with it — the sender takes its default now", true);
      // the wire name stays `identity_ack`; the control is **Dismiss** (§4.5a, renamed 2026-09-20)
      if (action === "identity_ack") say("dismissed — the agent's log keeps every alarm, a line each", true);
      if (action === "identity_log") say(`logged → ${(res.to && (res.to.name || res.to.id)) || b.dataset.to || "its controller"}: it owes you an outcome on them`, true);  // `to` is {id, name}
      if (action === "promote") say(`promoting ${res.repo} to ${String(res.sha || "").slice(0, 7)}${res.checks && res.checks !== "green" ? ` — checks read ${res.checks}, pressed through` : ""}: a note says when it is live`, true);
      if (action === "clear_promote") say(res.which === "held" ? "the hold is ended: live stays where it is, and promoting goes on" : res.cleared && b.dataset.held ? "the failure is cleared; the rollback's hold still stands — Dismiss again to end it" : res.cleared ? "the failure is cleared: promoting goes on" : "no failure or hold stood", true);
      if (action === "ci_rerun") say(`re-run asked of ${res.asked} run${res.asked === 1 ? "" : "s"} in ${res.owner || b.dataset.owner}${res.refused ? ` — GitHub refused ${res.refused}${res.why ? `: ${res.why}` : ""}` : ""}; the row stays while they run`, !res.refused);
      if (action === "ci_rerun" && typeof AO.refreshInboxPage === "function") AO.refreshInboxPage();
      if (action === "clear_work") say(res.cleared ? `dismissed — ${(res.ids || []).join(", ") || "those entries"} will not ask again; a later entry does` : "nothing was waiting any more", true);
      if (action === "clear_mark") say(!(res.cleared || []).length ? "nothing was standing any more" : res.kind === "held" ? "dismissed — the crossings stay on the record; the next one is a note again" : "dismissed — the read stays on the record; a later failing read is a row again", true);
      if (action === "suspend") say(`${b.dataset.name || "it"} is suspended — only you lift it, by resuming it or forgetting it`, true);
      if (action === "board" && body.action === "decide") say(`decided: ${body.answer} — landed on the board on origin; the item stays, as its session's work order`, true);
      else if (action === "board") say(body.action === "done" ? "checked off — landed on the board on origin" : `snoozed to ${body.due} — landed on the board on origin`, true);
      if (action === "dismiss") say(`dismissed ${(res.dismissed || body.msg || []).length || 1} — the sender is told where one was owed`, true);
      if (action === "attention_snooze" && String(res.snoozed_until || "").startsWith("dismissed:")) say("dismissed — the mark stays on the record, and a new one comes back as a new row", true);
      else if (action === "attention_snooze") say(res.snoozed_until ? "snoozed — the row comes back at that time; the state itself is untouched" : "back in its section", true);
      // the state is answered, so the row is gone: it is taken out here rather than waited for, and
      // the refresh below puts back whatever the record actually says. **Suspend is the exception**
      // (§4.8a): it acts on the session and *leaves the row standing* — the alarm is still there to
      // be answered — so the row is refreshed in place rather than taken out from under the person.
      // A **decide** leaves its row standing too (§4.4 *Decide*: a decided item is not done): the
      // refresh redraws it reading *decided*, and the ring stays where the person pressed.
      // A row the press took away left with it (`pressed`); one that stays — Suspend, a decide — is
      // redrawn by the refresh, which puts back whatever the record actually says.
      if ((staterow || id === "person") && typeof AO.refreshInboxPage === "function") {
        if (document.activeElement === b) b.blur();
        AO.refreshInboxPage();
      }
      if (action === "grants") say(`grants: ${(res.capabilities || []).join(", ") || "none"}`, true);
      if (action === "stop") say(res.stop_note || "no stop time: nothing will stop this session", true);
      if (action === "start") say(res.start_note ? `${res.start_note} — the agent starts it then` : "starts on the next tick", true);
      if (action2 === "controllers") {
        say(`under: ${(res.controllers || []).join(", ") || "nobody"}`, true);
      }
    } catch (e) {
      // Answered twice — two tabs, or the tool timed out into its own dialog between the poll and
      // the press — is not a failure to shout about: the state is simply no longer pending, and
      // the refresh below shows what it is now (design §4.5a **Inbox row: state**).
      if (staterow && /no pending permission/i.test(e.message)) {
        say("already answered — nothing was sent twice", true);
        if (!left) { AO.handRing(staterow); staterow.remove(); }
        if (typeof AO.refreshInboxPage === "function") AO.refreshInboxPage();
        return;
      }
      const named = { identity_log: "Log TD", board_reply: "Reply", board_add: "Put on the board", board_notright: "Not right…", ledger: "Decide", ledger_reply: "Reply", ledger_start: "Start session", ledger_release: "Release", ledger_hold: "Hold", "shell-here": "Open shell here" };
      say(`${named[action] || action} failed: ${e.message}`);  // a control is not its wire name
      // §4.5a *Inbox row: orphaned question* (TD-216): a refused write is drawn on the row, which stays.
      // Only the presses that write the board line are writes (TD-234): a failed Snooze or Delete
      // wrote nothing, and its toast says so in its own words
      const writes = ["reply", "answer", "gowithit", "ledger", "ledger_reply"].includes(action);
      const rowerr = writes && b.closest(".mailrow") && b.closest(".mailrow").querySelector(".rowerr");
      if (rowerr) { rowerr.textContent = `not written: ${e.message}`; rowerr.hidden = false; }
      // a row the press took away comes back with the next refresh, carrying the refusal on its error
      // line until its next press or a reload — the page holds it, nothing at the home does (TD-340)
      if (row && row.dataset.msg && (left || writes)) AO.pressErrs[row.dataset.msg] = writes ? `not written: ${e.message}` : `not ${PRESS_NOT[key] || AO.pressVerb(key).replace(/…$/, "")}: ${e.message}`;
      if ((staterow || left) && typeof AO.refreshInboxPage === "function") AO.refreshInboxPage();  // put the row back
    } finally {
      if (row && row.dataset.msg) delete AO.inflight[row.dataset.msg];
      if (waiting) say(PRESS_NOT[key] || "done", true);  // a press whose answer said nothing of its own
      if (row && !left && row.isConnected && row.classList.contains("pending")) AO.unPend(row);
    }
  });

  // design §4.5a **Inbox row: details** (§4.10 *How a message to a person is written*; TD-138):
  // which rows' *details* the person has opened, by entry id. The poll replaces rows, so the set is
  // put back after each swap (`reopenFolds`); it lives as long as the page and is never stored —
  // a fold is not state. Both ways (§4.5a *Inbox board row: detail block*, TD-312): a board row with
  // answers is drawn with its fold open, so a poll would open again what the person shut. Recorded
  // from the person's press on the summary, never from `toggle`, which a fold drawn open fires too;
  // the capture runs before the summary's own toggling, so `d.open` is the state being left.
  const foldsOpen = new Set(), foldsShut = new Set();
  document.addEventListener?.("click", (ev) => {
    const s = ev.target && ev.target.closest && ev.target.closest("details.fold > summary, details.cardline > summary");
    const d = s && s.parentElement;
    if (!d || !d.dataset.fold) return;
    const id = d.dataset.fold;
    if (d.open) { foldsShut.add(id); foldsOpen.delete(id); } else { foldsOpen.add(id); foldsShut.delete(id); }
  }, true);
  // the board line's **show** (§4.5 screen 6 *The board's horizon*, TD-220): opens the *not shown*
  // fold beside it for this page view — the fold's own memory above — and writes no setting
  document.addEventListener?.("click", (ev) => {
    const a = ev.target && ev.target.closest && ev.target.closest("a.boardshow");
    if (!a) return;
    ev.preventDefault();
    const box = a.closest("#boardhorizon, .inboxpage"), d = box && box.querySelector("details.boardfold");
    if (d) { if (d.dataset.fold) { foldsShut.delete(d.dataset.fold); foldsOpen.add(d.dataset.fold); } d.open = true; d.scrollIntoView({ block: "nearest" }); }
  });
  AO.reopenFolds = function (root) {
    (root ? $$("details.fold, details.cardline", root) : []).forEach((d) => {  // a card's Read line too (TD-911)
      if (foldsShut.has(d.dataset.fold)) d.open = false;
      else if (foldsOpen.has(d.dataset.fold)) { d.open = true; AO.fillFold(d); }
    });
    // a row a poll redrew keeps its links, from what its context knows, asking nothing (§4.6, TD-1108)
    (root ? $$(".mailrow[data-paths-ctx]", root) : []).forEach((row) => AO.linkItem(row, row, true));
  };
  // design §4.5 *Page loads* (*A row's folded details on a Queue card*, TD-891): a fold a Queue card draws
  // closed comes as its summary alone (`data-lazy`); its first open reads its body, `GET /api/fold?key=`,
  // the row renderer's own HTML. The bodies are kept by key while the page lives, so a fold a re-read swaps
  // in is filled at once from what was kept and read again; a key that names nothing says so.
  const foldBodies = new Map();
  AO.fillFold = async function (d) {
    if (!d || !d.dataset || !d.dataset.lazy || d.dataset.filled) return;
    const key = d.dataset.fold, put = (html) => {
      Array.from(d.children).forEach((c) => { if (c.tagName !== "SUMMARY") c.remove(); });
      d.insertAdjacentHTML("beforeend", html);
      const row = d.closest && d.closest(".mailrow[data-paths-ctx]");  // its paths, linked (§4.6, TD-1108)
      if (row && AO.linkItem) AO.linkItem(row, d, false);
    };
    d.dataset.filled = "1";
    if (foldBodies.has(key)) put(foldBodies.get(key));
    try {
      const r = await fetch(`/api/fold?key=${encodeURIComponent(key)}`);
      if (r.status === 404) { foldBodies.delete(key); put(`<div class="st">gone — reload</div>`); return; }
      if (!r.ok) throw new Error(String(r.status));
      const html = await r.text();
      foldBodies.set(key, html);
      put(html);
    } catch (e) {
      delete d.dataset.filled;  // the next open reads again
      if (!foldBodies.has(key)) put(`<div class="st">could not be read — open it again</div>`);
    }
  };
  document.addEventListener?.("toggle", (ev) => {
    const d = ev.target;
    if (d && d.matches && d.matches("details.fold[data-lazy][open]")) AO.fillFold(d);
  }, true);
  // The Focus panel's entry, folded as the Inbox row is: both halves were rendered by the server's
  // closed-subset renderer (`api_inbox`, `shaped`) — escaped text and its own few tags — so nothing
  // here composes markup from what a session wrote. An entry from an older UI without them is the
  // escaped text, whole, as before.
  AO.foldBody = function (e) {
    if (typeof e.lead_html !== "string") return `<div class="body">${esc(e.text)}</div>`;
    return `<div class="body md">${e.lead_html}</div>`
      + (e.rest_html ? `<details class="fold" data-fold="${esc(e.id)}"><summary>details</summary><div class="body md">${e.rest_html}</div></details>` : "");
  };

  // One mail entry, as the Focus Inbox panel shows it (design §4.5a **Focus Inbox**, §4.10):
  // sender (name, id on hover), kind, `about`, read/unread, age, an `ask`'s state, Reply and
  // delete. `owner` is the session whose inbox it sits in — the person inbox has the Inbox page's
  // rows instead, since 2026-09-19 (TD-069 step 1). No Reply on an entry the person sent: its
  // answer is the session's, which lands in the person inbox.
  // A `steer` carries the default it will take and lapses at its bound; an `ask` to the person
  // carries no bound at all and never expires; `system` is a sender and is never replied to
  // (design §4.10, 2026-09-19, TD-069 step 0).
  AO.mailEntry = function (e, owner) {
    const ask = e.kind === "ask" || e.kind === "steer";
    let st = "";
    if (ask) {
      st = e.closed_reason === "lapsed" ? "lapsed · the sender went with its default"
        : e.closed_reason === "go_with_it" ? "closed · go with it"
        : e.closed_reason === "declined" ? "declined"
        : e.closed_reason === "asker_gone" ? "closed · the asker is gone"
        : e.closed_reason === "asked_person" ? "closed · the asker took it to the person"
        : e.closed_by ? `answered by ${esc(e.closed_by)}`
        : e.expired_at ? "expired"
        : e.paused_at ? "paused · the clock is stopped"
        : (e.pending || []).length ? "addressee exited · pending"
        : e.bound ? `${e.kind === "steer" ? "lapses" : "open · bound"} ${esc(new Date(e.bound).toLocaleString())}`
        : "open · no bound";
    }
    const reply = (e.from === "person" || e.from === "system") ? ""
      : ` <button class="btn sm ghost" data-act="reply" data-id="${esc(owner)}" data-msg="${esc(e.id)}" data-from="${esc(e.from)}" data-name="${esc(e.from_name || e.from)}" data-quote="${esc(e.text)}" data-when-note="${esc(e.reply_when || "")}">Reply</button>`;
    const confirmText = "Delete this entry from this session's inbox? The sender keeps its copy.";
    return `<div class="mail${e.read_at ? "" : " unread"}" data-msg="${esc(e.id)}">`
      + `<div class="row gap"><span class="ref" title="${esc(e.from)} · ${esc(e.from_role || "")}">${esc(e.from_name || e.from)}</span>`
      + `<span class="st kind">${esc(e.kind)}</span>${e.about ? `<span class="st">re ${esc(e.about)}</span>` : ""}`
      + `<span class="grow"></span><span class="st">${e.read_at ? "read" : "unread"}</span>`
      + `<span class="st age" data-since="${esc(e.at || "")}">${fmtAge(e.at)}</span></div>`
      + (e.reply_to ? `<div class="st">reply to ${esc(e.reply_to)}</div>` : "")
      + AO.foldBody(e)
      + (e.default ? `<div class="st">unless you say otherwise: ${esc(e.default)}</div>` : "")
      + `<div class="row gap">${st ? `<span class="st${e.expired_at ? " expired" : ""}">${st}</span>` : ""}<span class="grow"></span>${reply}`
      + ` <button class="btn sm ghost" data-act="unmail" data-id="${esc(owner)}" data-msg="${esc(e.id)}" data-confirm="${confirmText}">Delete</button></div></div>`;
  };

  // design §4.5a Sessions top bar **Inbox** (§4.5 screen 6, TD-069 step 1). The control is a link to
  // `/inbox`, and its number is that page's **Needs you** section — computed server-side in one
  // place (`inbox_sections`), so the top bar and the page cannot disagree. No session record holds
  // the person inbox, so nothing on the pushed stream carries it: this polls the same route the
  // page does, a person's read that marks nothing. (The dialog that hung here until 2026-09-19
  // relied on that same rule and is retired with the page's arrival.)
  // design §4.5a **team header** → *answered for you* count (§4.9b, TD-075): the rows' team and
  // time from the poll, counted here against the newest one this browser has seen with the Inbox's
  // *Answered for you* group open — the browser's own memory, as FYI's *new* mark is, so looking
  // changes nothing at the home. A mark, never a control. `null` is *not known* (the host agent is
  // down): the headers keep what they showed rather than claim nothing was answered.
  const ANSWERED_SEEN = "inboxansweredseenat";
  let answeredMarks = null;
  AO.answeredCounts = function (marks, seen) {
    const n = {};
    (marks || []).forEach((m) => {
      const at = m.at || "";
      if (!seen || at > seen) n[m.team || ""] = (n[m.team || ""] || 0) + 1;
    });
    return n;
  };
  function syncAnsweredMarks() {
    if (!answeredMarks) return;
    const n = AO.answeredCounts(answeredMarks, store.get(ANSWERED_SEEN, ""));
    $$("[data-answered-team]").forEach((el) => {
      const k = n[el.dataset.answeredTeam] || 0;
      el.textContent = k ? `${k} answered for you` : "";
      el.classList.toggle("hidden", !k);
    });
  }
  let overdueN = null;  // the Needs you board items past their date, from the last poll (TD-178)
  // `full`: the Inbox's own pages, which redraw their rows from the read; every other page asks for
  // the counts alone (TD-611), never the megabytes of rows it would throw away
  // The counts' `rev` this page last drew (§4.4 *The Inbox's counts*, TD-616): a counts read sends it
  // as `since`, and one the server still holds answers `{unchanged: true}` with nothing to redraw.
  let countsRev = null;
  AO.refreshInboxCount = async function (full) {
    let got;
    try {
      // a visible page says so (§4.10 *Told on Telegram*, *Looking*): a row on a screen is not told
      const q = [
        full ? "" : "counts=1", !full && countsRev !== null ? `since=${countsRev}` : "",
        document.visibilityState === "visible" ? "watching=1" : "",
      ].filter(Boolean);
      const r = await fetch("/api/person/inbox" + (q.length ? `?${q.join("&")}` : ""));
      if (!r.ok) return null;
      got = await r.json();
    } catch (e) { return null; }
    if (got.unchanged) return got;
    return AO.drawCounts(got);
  };
  // A tab's number: shown only above zero (§4.5a *the bar's three groups*)
  AO.drawTabCount = function (el, n) {
    if (!el) return;
    el.textContent = n > 0 ? String(n) : ""; el.classList.toggle("hidden", !(n > 0));
  };
  // The top bar's numbers, from a read or from the stream's `counts` (TD-616): one drawing for both.
  AO.drawCounts = function (got) {
    // a count with the host agent down holds no revision: the next read must not be `unchanged`
    countsRev = typeof got.rev === "number" && !got.agent_down ? got.rev : null;
    // `needs: null` is *not known* — the host agent is down — and a chip that read 0 would be a
    // lie in the one place a person looks to see whether anything is waiting (TD-069).
    // Two numbers, one per tab (§4.5a *the bar's three groups*, TD-932): the Queue's is the needs-you rows its
    // cards draw (`queue_n`), the Inbox's the rest — they add up to `needs`, what waits on a person
    if (got.needs !== null && got.needs !== undefined) {
      const q = typeof got.queue_n === "number" ? got.queue_n : 0;
      AO.drawTabCount($("#personneeds"), (got.needs || 0) - q);
      AO.drawTabCount($("#queueneeds"), q);
    }
    if (typeof document.dispatchEvent === "function" && typeof CustomEvent === "function") document.dispatchEvent(new CustomEvent("ao:counts", { detail: got }));
    // §4.10 *The Inbox is a queue* (TD-079 step 2): FYI's own quiet number, *Inbox 1 · 5*, never
    // added to the first. `null` is *not known* here too — a chip reading 0 with the host agent
    // down would be the same lie the first one refuses to tell.
    const fyi = $("#personfyi"), m = got.fyi_n || 0;
    if (fyi && got.fyi_n !== null && got.fyi_n !== undefined) { fyi.textContent = m ? `· ${m}` : ""; fyi.classList.toggle("hidden", !m); }
    if (Array.isArray(got.answered_marks)) { answeredMarks = got.answered_marks; syncAnsweredMarks(); }
    // the Org rollup's *m overdue* (TD-178): `null` is not known, and the rollup keeps what it showed
    if (typeof got.overdue_n === "number") { overdueN = got.overdue_n; if (typeof syncSummaries === "function") syncSummaries(); }
    if (got.build_chip) drawBuildChip(got.build_chip);
    return got;
  };
  // A page whose `/events` stream is up draws the counts it pushes and polls nothing (§4.4, TD-616);
  // the poll below runs only while no stream is — a page with none, or one that dropped.
  let streamsUp = 0;
  // §4.5a top bar **build** chip (TD-539): *live <MM-DD HH:MM>* in the browser's zone — the year in
  // front only when it is not this one — from `data-at`, then `data-rest`. Drawn at load and again
  // from each Inbox poll's `build_chip`, so a merge shows without a reload. *main +n* is a link to
  // the Inbox's promote row (`data-link`, `data-href`, TD-581): the chip's one pressable part.
  function buildStamp(at) {
    const d = new Date(Date.parse(at || ""));
    if (isNaN(d)) return "";
    const p = (n) => String(n).padStart(2, "0");
    const md = `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
    return d.getFullYear() === new Date().getFullYear() ? md : `${d.getFullYear()}-${md}`;
  }
  function drawBuildChip(c) {
    const el = $("#buildchip");
    if (!el) return;
    if (c) {
      el.className = `mono ${c.cls || ""}`; el.title = c.title || "";
      if (c.at) { el.dataset.at = c.at; el.dataset.rest = c.rest || ""; } else { delete el.dataset.at; delete el.dataset.rest; }
      if (c.href && c.link) { el.dataset.href = c.href; el.dataset.link = c.link; } else { delete el.dataset.href; delete el.dataset.link; }
    }
    const when = el.dataset.at ? buildStamp(el.dataset.at) : "";
    // at load with no `data-at` the server's own rendering stands
    const full = when ? `live ${when}${el.dataset.rest || ""}` : c ? c.text || "" : null;
    if (full === null) return;
    const link = el.dataset.link, href = el.dataset.href;
    if (link && href && full.endsWith(link)) {
      el.textContent = full.slice(0, -link.length);
      const a = document.createElement("a");
      a.href = href; a.textContent = link; a.title = "the Inbox's promote row";
      el.appendChild(a);
    } else el.textContent = full;
  }
  drawBuildChip(null);
  if ($("#personneeds")) {
    // the Sessions page and the Inbox page render the count server-side; every other page reads it at
    // load. On the Inbox page the poll is the page's own, which refreshes the rows as well.
    // The Org reads it at load too: its number is server-rendered, but the team headers' *answered
    // for you* marks are counted in the browser (§4.9b) and would otherwise wait a whole poll.
    if (location.pathname !== "/inbox") AO.refreshInboxCount();
    setInterval(() => { if (AO.refreshInboxPage) AO.refreshInboxPage(); else if (!streamsUp) AO.refreshInboxCount(); }, 20000);
  }

  $("#theme") && $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme;
    store.set("theme", cur === "dark" ? "light" : "dark"); applyTheme();
  });
  $("#shellbtn") && $("#shellbtn").addEventListener("click", () => {
    const menu = $("#newmenu"); if (menu) menu.open = false;  // the + New ▾ menu folds on its choice
    const d = prompt("Shell in which directory?", store.get("lastdir", "~"));
    if (!d) return; store.set("lastdir", d);
    const f = $("#shellform"); f.querySelector("[name=dir]").value = d; f.submit();
  });

  // ---- countdowns and ages tick locally; transitions arrive as deltas, never from the clock ----
  function fmtAge(iso) {
    if (!iso) return "";
    const s = Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 1000));
    if (s < 60) return s + "s"; if (s < 3600) return Math.floor(s / 60) + "m";
    if (s < 86400) return Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m"; return Math.floor(s / 86400) + "d";
  }
  // The Doing list's short age (§4.5a **Ages and columns**, TD-232), in the very words `_short_age` in
  // `ui/common.py` draws: *0m* under a minute and ahead of the clock (TD-418), then one unit. "" = unreadable.
  // A stamp with no offset is UTC, as `_instant` reads it, never the browser's local time.
  function utcParse(iso) {
    const v = String(iso || "");
    return Date.parse(/T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(v) ? v + "Z" : v);
  }
  function fmtShortAge(iso) {
    const t = utcParse(iso);
    if (isNaN(t)) return "";
    const s = Math.floor((Date.now() - t) / 1000);
    if (s < 60) return "0m"; if (s < 3600) return Math.floor(s / 60) + "m";
    if (s < 86400) return Math.floor(s / 3600) + "h"; return Math.floor(s / 86400) + "d";
  }
  AO.fmtShortAge = fmtShortAge;  // for the node probe (tests/test_ui_team_summary.py)
  // Once a minute, the shape's own grain, and at once for rows just put on the page: the age from the
  // row's timestamp and the exact time in the reader's clock as its tooltip — never `.age[data-since]`,
  // whose one-second tick would write *45s* over it. A cell that cannot be read stays empty.
  function showDoingAges(root) {
    $$("[data-doing-at]", root || document).forEach((el) => {
      const iso = el.dataset.doingAt, d = new Date(utcParse(iso));
      if (!iso || isNaN(d)) { el.textContent = ""; return; }
      el.textContent = fmtShortAge(iso);
      el.title = d.toLocaleString();
    });
  }
  AO.showDoingAges = showDoingAges;
  setInterval(() => showDoingAges(), 60000);
  // A time left, in the very words `_left` in `ui/app.py` renders it into the row (§4.5 screen 6
  // *Layout*, TD-082): the server draws the number, this only keeps it moving, and because both
  // spell it the same way nothing on the row jumps when the first tick lands. "" = already past.
  function fmtLeft(iso) {
    const s = Math.floor((Date.parse(iso) - Date.now()) / 1000);
    if (!(s > 0)) return "";
    if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
    return `${Math.floor(s / 86400)}d`;
  }
  setInterval(() => {
    $$(".age[data-since]").forEach((el) => (el.textContent = fmtAge(el.dataset.since)));
    $$(".countdown[data-deadline]").forEach((el) => {
      if (!el.dataset.deadline) return;
      const left = fmtLeft(el.dataset.deadline);
      el.textContent = left ? `via hook · ${left} left` : "via hook · falling through to the terminal";
    });
    // design §4.5a **Inbox row: `steer`**: the time left, ticking here — the lapse itself is the
    // home's, and arrives as a changed entry on the next poll, never from this clock.
    $$(".timeleft[data-deadline]").forEach((el) => {
      if (!el.dataset.deadline) return;
      const left = fmtLeft(el.dataset.deadline);
      // an orphaned `steer` (§4.5a *Inbox row: orphaned question*, TD-216): nobody takes its default
      // at the bound — it waits on the person from then on
      const then = el.dataset.then;
      if (then) el.textContent = left ? `${left} left, ${then}` : `the time is up: it waits on you`;
      else el.textContent = left ? `${left} left — then it goes with its default` : "the time is up: the sender goes with its default";
    });
    showLocalTimes();
  }, 1000);

  // A stored instant (UTC) shown in the browser's own clock: a person who snoozed until *tomorrow
  // 08:00* must read back tomorrow 08:00, not the UTC instant behind it — which stays on the
  // element's title. It does not change once written, so each element is written once; the callers
  // are the tick above and whatever has just put new rows on the page.
  function showLocalTimes() {
    $$(".localtime[data-at]").forEach((el) => {
      if (el.dataset.shown === "1") return;
      const d = new Date(Date.parse(el.dataset.at || ""));
      el.textContent = isNaN(d) ? el.dataset.at || "" : d.toLocaleString();
      el.dataset.shown = "1";
    });
  }

  // ---- events websocket with backoff; a reconnect reloads the snapshot once, never in a loop ----
  // design §4.5 *A reconnect reloads once, never in a loop* (TD-692, TD-694). The page reloads when its
  // stream comes back after a close, and records each such reload's time in `sessionStorage` under
  // `ao.reloads:<path>`; three in the last 60 s hold the fourth back and draw the reload-loop banner.
  // `ao.reloading:<path>` marks a reload the page made itself, so a load that finds it keeps the
  // times and any other load (F5, a link, **Reload**) clears them. Storage that throws counts nothing.
  AO.RELOADS_MAX = 3; AO.RELOADS_WINDOW = 60000;
  const reloadsKey = () => `ao.reloads:${location.pathname}`, reloadingKey = () => `ao.reloading:${location.pathname}`;
  try {
    if (sessionStorage.getItem(reloadingKey()) !== null) sessionStorage.removeItem(reloadingKey());
    else sessionStorage.removeItem(reloadsKey());
  } catch (e) { /* storage that throws counts nothing */ }
  let reloadLoopDrawn = false;
  function drawReloadLoop() {
    if (reloadLoopDrawn) return;
    reloadLoopDrawn = true;
    const b = $("#reloadloop"); if (b) b.hidden = false;
  }
  // §4.5a *every page: reload-loop banner* **Reload**: clears the count, then a load of the person's own
  const reloadBtn = $("#reloadloopbtn");
  if (reloadBtn) reloadBtn.addEventListener("click", () => {
    try { sessionStorage.removeItem(reloadsKey()); sessionStorage.removeItem(reloadingKey()); } catch (e) {}
    location.reload();
  });
  // A stream came back after a close: reload, unless three reloads in the window hold this one back.
  // Returns whether it reloaded. `location.reload()` does not stop the page at once, so the messages
  // still arriving before it goes are the same reload, counted once.
  let reloadMade = false;
  function reloadOnReturn() {
    if (reloadMade) return true;
    let times;
    try {
      times = JSON.parse(sessionStorage.getItem(reloadsKey()) || "[]");
      if (!Array.isArray(times)) times = [];
    } catch (e) { reloadMade = true; location.reload(); return true; }
    const now = Date.now();
    times = times.filter((t) => typeof t === "number" && now - t < AO.RELOADS_WINDOW && t <= now);
    if (times.length >= AO.RELOADS_MAX) {
      try { sessionStorage.setItem(reloadsKey(), JSON.stringify(times)); } catch (e) {}
      drawReloadLoop();
      return false;
    }
    try {
      times.push(now);
      sessionStorage.setItem(reloadsKey(), JSON.stringify(times));
      sessionStorage.setItem(reloadingKey(), "1");
    } catch (e) {}
    reloadMade = true;
    location.reload();
    return true;
  }
  // the `v=` of the `app.js` link this page loaded: the stream says it as `page=`, so the UI's
  // open-rate warning names the build the page came from beside the one it serves
  const pageHash = (() => {
    try { return new URL(document.currentScript.src, location.href).searchParams.get("v") || ""; } catch (e) { return ""; }
  })();
  let errorToasted = false;  // an `error` event is toasted once per page load
  // `query` asks for a light stream (TD-572): `light=1` on the Focus and Inbox pages, which draw no
  // cards and no team groups, and hear of another record only when it moves (its state, team or
  // controllers); `focus=<id>` keeps that one record's deltas whole.
  function connectEvents(onEvent, query) {
    let delay = 500, reconnected = false, leaving = false;
    window.addEventListener("pagehide", () => { leaving = true; });
    window.addEventListener("pageshow", () => { leaving = false; });
    // the one thing the page says on its stream: whether it is visible, which the counts keeper
    // hands the home as Looking (§4.10 *Told on Telegram*, TD-616)
    let sock = null, up = false;
    const say = () => { if (sock && sock.readyState === 1) sock.send(JSON.stringify({ visible: document.visibilityState === "visible" })); };
    document.addEventListener("visibilitychange", say);
    const params = new URLSearchParams(query || "");
    params.set("page", pageHash); params.set("at", location.pathname);
    function open() {
      const ws = sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/events?${params}`);
      // The handshake succeeds even when the agent is down (the server accepts, then closes), so
      // "up" is the first message that is not `error`, never onopen — and the backoff is put back
      // there too, or an accepted-then-closed socket reopens every half second.
      ws.onopen = () => { say(); };
      ws.onmessage = (m) => { const ev = JSON.parse(m.data);
        // `error` is not up: toasted once, and the stream stays as it was — no banner cleared, no
        // count, no reload, *reconnected* kept — so a stream that fails at each open never reloads
        if (ev.event === "error") { if (!errorToasted) { errorToasted = true; AO.toast(ev.text); } return; }
        delay = 500;
        setDown(false);
        if (reconnected) {
          if (reloadOnReturn()) return;
          reconnected = false;  // held back: this stream is the page's own from here on
        }
        if (!up) { up = true; streamsUp++; }
        if (ev.event === "usage") onUsage(ev); else if (ev.event === "counts") AO.drawCounts(ev); else onEvent(ev);
      };
      // a close the page caused by leaving is no outage (TD-372); the reconnect stays, so a page
      // restored from the back-forward cache reconnects and reloads as after any other close
      ws.onclose = () => { if (!leaving) setDown(true); if (up) { up = false; streamsUp--; } reconnected = true; setTimeout(open, delay); delay = Math.min(delay * 2, 10000); };
      ws.onerror = () => ws.close();
    }
    open();
  }
  AO.connectEvents = connectEvents;  // node's probes (tests) drive it with a fake socket
  // ---- usage chip: one span per account, its **worst** window, the rest on hover (TD-001, TD-073, TD-122) ----
  // The windows and their labels are the adapter's — this file names no window of any one tool, so a
  // tool with one daily window or three windows prints what it has. The server regroups each pushed
  // profile reading into its account (`usage_accounts`) and sends `{account, usage}`; `usage: null`
  // means no live session's profile names that account any more: its chip goes.
  const NEAR_CAP = 80;  // "at or near a cap": never collapsed into +n, whatever the room (Paul 2026-09-19)
  // Why the last poll gave no reading: the adapter's `reason` word in words (§4.2, TD-087). Keyed on
  // the word, never on text; a word this table does not know is printed as itself.
  const USAGE_WHY = {
    rate_limited: "rate-limited by the usage endpoint", no_credentials: "no credentials for this profile",
    no_profile: "no such profile", error: "the usage endpoint could not be read",
  };
  // One account's chip, or null for none — `usage_chip` in app.py is the same rule for the server's
  // render, and the tests hold the two to the same cases. **The age** (§4.5a, TD-233 slice 1): past
  // five minutes the reading's age follows the number, past `USAGE_FRESH` the chip is dimmed, past
  // `USAGE_UNKNOWN` or the worst window's reset it reads *unknown since 22:21 (was 88%)*; the hover
  // says when it was read, from where, and why the poll since failed. A refusal with nothing ever
  // held is `<profile>: no reading yet`. An `ok` with no windows is a tool that reports no quota: no chip.
  // This window's row of the gate's reading (§6, TD-100), where the profile's reserve makes a line.
  function usageLine(w, lines) {
    const row = (Array.isArray(lines) ? lines : []).find((r) => r && typeof r === "object" && r.label === w.label);
    return row && typeof row.line === "number" ? row : null;
  }
  // The projection the gate reads for a window (§6, TD-233): the row's `pct` when it is `projected`.
  const projectedOf = (row) => (row && row.projected && typeof row.projected === "object" && !Array.isArray(row.projected) && typeof row.pct === "number" ? row.pct : null);
  function usageHover(w, row) {
    if (!row) return `${w.label} ${w.pct}% (resets ${w.resets || "?"})`;
    const pr = projectedOf(row);
    return `${w.label} ${w.pct}%${pr !== null ? `, projected ${pr}%` : ""} / line ${row.line}% (${reserveWhy(row)}; resets ${w.resets || "?"})`;
  }
  // A line's reserve, the days left a per-day reserve counts, and when the line next moves — the
  // account's lowest line and each profile's own alike (TD-100, TD-122).
  function reserveWhy(row) {
    const r = row.reserve, ln = row.line;
    let why;
    if (r && typeof r === "object" && Number.isInteger(r.per_day) && r.per_day > 0) {
      why = `reserve ${r.per_day}% a day`;
      if (ln > 0) why += `, ${Math.floor((100 - ln) / r.per_day)} days left`;
    } else why = r == null ? "reserve ?" : `reserve ${r}%`;
    return `${why}; line moves ${row.next || "?"}`;
  }
  // The profiles sharing the account, each with its lines (reserve, days left, next move) and live
  // sessions, for the hover (TD-122).
  function usageProfiles(u) {
    const parts = [];
    for (const p of Array.isArray(u.profiles) ? u.profiles : []) {
      if (!p || typeof p !== "object") continue;
      const lines = (Array.isArray(p.lines) ? p.lines : []).filter((r) => r && typeof r === "object" && typeof r.line === "number").map((r) => `${r.label} line ${r.line}% (${reserveWhy(r)})`);
      // a metered profile's own amounts (TD-151): the chip prints the smallest, the hover each
      for (const a of Array.isArray(p.amounts) ? p.amounts : []) {
        const said = a && typeof a === "object" ? amountSays(a.amount) : "";
        if (said) lines.push(`${a.label} amount ${said}`);
      }
      const names = (Array.isArray(p.sessions) ? p.sessions : []).map(String);
      let part = String(p.name);
      if (lines.length) part += ` [${lines.join(", ")}]`;
      if (names.length) part += `: ${names.join(", ")}`;
      parts.push(part);
    }
    return parts.length ? `profiles on this account:\n${parts.join("\n")}` : "";  // one per line (TD-270)
  }
  // A token count as the server says it (`tokens_short`): `231k`, `1.2M`, `2.1B`; under a thousand, as it is;
  // a unit promotes where its rounding reaches the next (999,500 is `1M`, never `1000k`).
  // Half to even, as Python's `round` and format are, so a tie reads the same in both homes.
  const halfEven = (x) => { const f = Math.floor(x), d = x - f; return d > 0.5 || (d === 0.5 && f % 2 !== 0) ? f + 1 : f; };
  const tokShort = (n) => {
    if (n < 1e3) return String(n);
    const k = halfEven(n / 1e3), m = halfEven(n / 1e5);
    return k < 1e3 ? `${k}k` : m < 1e4 ? String(m / 10) + "M" : String(halfEven(n / 1e8) / 10) + "B";
  };
  const money = (v) => "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).replace(/\.00$/, "");
  // A metered profile's amount for a window as the chip writes it — `_amount_says` in common.py.
  function amountSays(a) {
    if (!a || typeof a !== "object" || typeof a.value !== "number" || !Number.isFinite(a.value)) return "";
    return a.unit === "$" ? money(a.value) : `${tokShort(Math.trunc(a.value))} tok`;
  }
  const METERED_KINDS = [["input", "in"], ["output", "out"], ["cache_read", "cache read"], ["cache_write", "cache write"]];
  // A **metered** account's chip (§4.5a **usage**, TD-151 slice 5) — `_metered_chip` in app.py is
  // the same rule: the account's spend over the window's amount, worst the one nearest its amount,
  // amber from eight tenths, red at it; *spend unknown* when the adapter could not read; never stale.
  // A window's turns and pace on the hover (TD-151) — `_pace_says` in app.py is the same rule.
  function paceSays(w, now) {
    let out = "";
    if (Number.isInteger(w.turns)) out += ` · ${w.turns.toLocaleString("en-US")} turn${w.turns === 1 ? "" : "s"}`;
    const p = w.pace && typeof w.pace === "object" ? w.pace : null;
    if (!p || typeof p.per_hour !== "number" || !Number.isFinite(p.per_hour) || !["$", "tok"].includes(p.unit)) return out;
    out += ` · ${p.unit === "$" ? money(p.per_hour) : `${tokShort(Math.trunc(p.per_hour))} tok`}/h`;
    const at = instant(p.at), amount = amountSays(w.amount);
    if (at !== null && amount) {
      const d = new Date(at), pad = (n) => String(n).padStart(2, "0"), hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
      const today = d.toDateString() === new Date(now).toDateString();
      out += ` · at this pace ${amount} by ${today ? hm : `${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()]} ${hm}`}`;
    }
    return out;
  }
  function meteredChip(profile, u, windows, now) {
    now = typeof now === "number" ? now : Date.now();
    const isNum = (v) => typeof v === "number" && Number.isFinite(v);
    const spend = (w) => {
      const s = w.spent, a = w.amount && typeof w.amount === "object" ? w.amount : {};
      return a.unit === "tok" || !isNum(s.cost) ? `${tokShort(Math.trunc(s.total || 0))} tok` : money(s.cost);
    };
    const amount = (w) => amountSays(w.amount);
    const pct = (w) => Number.isInteger(w.pct) ? w.pct : null;
    let worst = windows[0];
    for (const w of windows) if (pct(w) !== null && (pct(worst) === null || pct(w) > pct(worst))) worst = w;
    const n = pct(worst) || 0;
    let text = `${profile} · ${worst.label} ${spend(worst)}`;
    if (amount(worst)) text += ` / ${amount(worst)}`;
    let title = windows.map((w) => {
      const t = w.spent.tokens && typeof w.spent.tokens === "object" ? w.spent.tokens : {};
      const kinds = METERED_KINDS.map(([k, word]) => `${tokShort(Math.trunc(t[k] || 0))} ${word}`).join(", ");
      let part = `${w.label} ${spend(w)}`;
      if (amount(w)) part += ` / ${amount(w)} (${pct(w) !== null ? pct(w) : "?"}%)`;
      part += paceSays(w, now);
      return `${part} — ${kinds} (resets ${w.resets || "?"})`;
    }).join("\n");  // one window per line (TD-270)
    const reason = String(u.reason || "ok");
    if (reason !== "ok") { text += " · spend unknown"; title = `spend unknown: ${USAGE_WHY[reason] || reason}\n${title}`; }
    const sharing = usageProfiles(u);
    if (sharing) title += `\n\n${sharing}`;
    const near = n >= NEAR_CAP;
    return { text, title, pct: n, cls: n >= 100 ? "cap" : near ? "near" : "", near };
  }
  // How old a reading may be before the chip says so (§4.5a *The age*, TD-233 slice 1), in seconds:
  // `USAGE_AGED` and the rest in app.py are the same three numbers.
  const USAGE_AGED = 5 * 60, USAGE_FRESH = 15 * 60, USAGE_UNKNOWN = 3 * 3600;
  const USAGE_SOURCE = { asked: "asked of the endpoint", reported: "reported by a session" };
  // An instant off a record, or null for what `_instant` would not read: an ISO date, a naive one UTC.
  function instant(iso) {
    if (typeof iso !== "string" || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return null;
    let s = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso + "T00:00:00" : iso;
    if (!/(Z|[+-]\d{2}:?\d{2})$/.test(s)) s += "Z";
    const t = Date.parse(s);
    return Number.isNaN(t) ? null : t;
  }
  const usageAge = (secs) => { secs = Math.max(0, Math.floor(secs)); return secs < 3600 ? `${Math.floor(secs / 60)}m` : secs < 86400 ? `${Math.floor(secs / 3600)}h` : `${Math.floor(secs / 86400)}d`; };
  function usageClock(t, now) {
    const d = new Date(t), pad = (n) => String(n).padStart(2, "0");
    const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    return now - t >= 86400e3 ? `${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()]} ${hm}` : hm;
  }
  AO.tokShort = tokShort;  // read by tests/test_models.py's edge cases, held to `tokens_short`
  AO.usageChip = function (profile, u, now) {
    if (!u || typeof u !== "object") return null;
    const spent = (Array.isArray(u.windows) ? u.windows : []).filter((w) => w && typeof w === "object" && w.spent && typeof w.spent === "object" && !Array.isArray(w.spent));
    if (spent.length) return meteredChip(profile, u, spent, now);
    const windows = (Array.isArray(u.windows) ? u.windows : []).filter((w) => w && typeof w.pct === "number");
    const reason = String(u.reason || "ok"), refused = reason !== "ok";
    if (!windows.length && !refused) return null;
    let why = "";
    if (refused) {
      why = "the last poll was refused: " + (USAGE_WHY[reason] || reason);
      if (typeof u.retry_after === "number") why += `, which asked to be left ${Math.max(1, Math.ceil(u.retry_after / 60))} min`;
    }
    const sharing = usageProfiles(u);
    if (!windows.length) return { text: `${profile}: no reading yet`, title: `no usage reading for ${profile} yet — ${why}` + (sharing ? `\n\n${sharing}` : ""), pct: 0, cls: "unknown", near: false };
    now = typeof now === "number" ? now : Date.now();
    const at = instant(u.fetched), secs = at === null ? null : Math.max(0, (now - at) / 1000);
    const read = at === null ? null : { secs, age: usageAge(secs), clock: usageClock(at, now), source: USAGE_SOURCE[String(u.source || "asked")] || String(u.source) };
    // a window past its reset is unknown until read again — never zero, never a cap (§4.4)
    const gone = new Set(windows.filter((w) => { const r = instant(w.resets); return r !== null && r <= now; }));
    // worst = the smallest gap to its line, the tool's 100% where the profile has no reserve (§4.5a, TD-100)
    // the number the gate reads: the projection while it projects (§6, TD-233), else the reading
    const shown = ([w, r]) => { const pr = projectedOf(r); return pr === null ? w.pct : pr; };
    const gap = (x) => (x[1] ? x[1].line : 100) - shown(x);
    const ws = windows.map((w) => [w, usageLine(w, u.lines)]).sort((a, b) => (gone.has(a[0]) - gone.has(b[0])) || gap(a) - gap(b) || shown(b) - shown(a));
    const [worst, row] = ws[0];
    const projected = gone.has(worst) ? null : projectedOf(row);
    const parts = ws.map(([w, r]) => gone.has(w) ? `${w.label} unknown since its reset at ${usageClock(instant(w.resets), now)} (was ${w.pct}%)` : usageHover(w, r));
    // the reading, why it is held, then each window on its own line; a blank line; the profiles (TD-270)
    let title = [...(read ? [`read at ${read.clock}, ${read.age} ago, ${read.source}`] : []), ...(why ? [why] : []), ...parts].join("\n");
    if (sharing) title += `\n\n${sharing}`;
    if (gone.has(worst) || (projected === null && read && read.secs > USAGE_UNKNOWN)) {
      // the number is no longer offered as the account's (§4.5a *The age*); it stays on the hover
      const since = gone.has(worst) ? instant(worst.resets) : at;
      return { text: `${profile} · ${worst.label} unknown since ${usageClock(since, now)} (was ${worst.pct}%)`, title, pct: 0, cls: "unknown", near: false };
    }
    const n = shown([worst, row]);
    const near = n >= 100 || (row ? n >= row.line - 10 : n >= NEAR_CAP);
    let cls = n >= 100 ? "cap" : near ? "near" : "";
    let text = `${profile} · ${worst.label} ${worst.pct}%`;  // *Claude · paul · week 24%* (TD-122)
    if (row && projected === null) text += ` / ${row.line}%`;  // *grind · week 61% / 70%* (TD-100)
    if (read && read.secs > USAGE_AGED) text += ` · ${read.age}`;  // *Claude · paul · week 88% · 6h* (TD-230)
    if (row && projected !== null) text += ` · projected ${projected}% / ${row.line}%`;  // *week 88% · 2h · projected 96% / 95%* (TD-233)
    if (read && read.secs > USAGE_FRESH) cls = (cls + " old").trim();  // still red at a cap
    return { text, title, pct: n, cls, near };
  };
  function onUsage(ev) {
    const chip = $("#usagechip"); if (!chip) return;
    let el = chip.querySelector(`[data-account="${CSS.escape(ev.account)}"]`);
    const c = AO.usageChip(ev.account, ev.usage);
    // The chip and the space after it were added together, so they go together: an account that
    // comes and goes all day would otherwise leave a text node behind each time, and those widths
    // are what `fitUsage` measures against (review of PR #279).
    if (!c) { if (el) { const sep = el.nextSibling; if (sep && sep.nodeType === 3) sep.remove(); el.remove(); } fitUsage(); return; }
    if (!el) { el = document.createElement("span"); el.dataset.account = ev.account; chip.insertBefore(el, $("#usagemore")); chip.insertBefore(document.createTextNode(" "), $("#usagemore")); }
    el.dataset.usage = JSON.stringify(ev.usage);
    drawUsage(el, c);
    fitUsage();
    if (AO.focusUsage) AO.focusUsage();  // a Focus keeps it for its disconnect card (TD-923)
  }
  function drawUsage(el, c) {
    el.dataset.pct = c.pct;
    el.dataset.near = c.near ? "1" : "";
    el.textContent = c.text;
    el.className = c.cls;
    el.title = c.title;
  }
  // A reading ages with no event to say so — the endpoint refusing is exactly when none comes — so
  // each chip is drawn again once a minute from the reading it holds (`data-usage`, TD-233 slice 1).
  function ageUsage() {
    const chip = $("#usagechip"); if (!chip) return;
    for (const el of chip.querySelectorAll("[data-usage]")) {
      let u; try { u = JSON.parse(el.dataset.usage); } catch (e) { continue; }
      const c = AO.usageChip(el.dataset.account, u);
      if (c) drawUsage(el, c);
    }
    fitUsage();
  }
  setInterval(ageUsage, 60e3);
  // Chips side by side while they fit; past that the worst accounts and `+n`, which shows the rest
  // on hover. No rotation: a display that rotates hides the number at the moment it is looked at,
  // and the one that matters may be the one off screen (TD-073, decided by Paul 2026-09-19).
  function fitUsage() {
    const chip = $("#usagechip"); if (!chip) return;
    const more = $("#usagemore"), spans = [...chip.querySelectorAll("[data-account]")];
    spans.forEach((s) => s.classList.remove("hidden"));
    if (!more) return;
    more.classList.add("hidden"); more.textContent = ""; more.title = "";
    // Hide the least important first: lowest worst-window percentage, and never one at or near a cap
    // — near its line where a profile on the account has a reserve (TD-100), which is the chip's own `near`.
    const droppable = spans.filter((s) => !s.dataset.near).sort((a, b) => (+a.dataset.pct || 0) - (+b.dataset.pct || 0));
    const hidden = [];
    while (chip.scrollWidth > chip.clientWidth + 1 && droppable.length) {
      const s = droppable.shift(); s.classList.add("hidden"); hidden.push(s);
      more.textContent = `+${hidden.length}`; more.classList.remove("hidden");
    }
    if (hidden.length) more.title = hidden.map((s) => `${s.textContent} — ${s.title}`).join("\n\n");  // a chip's title is lines now: a blank line between chips (TD-270)
  }
  // design §4.5 *The host agent's down banner* (TD-372): drawn only once the socket has stayed
  // down for `AO.DOWN_GRACE`, so a navigation or a promote's two-second restart draws nothing; any
  // message clears it at once. A close while one is already pending or shown keeps the first.
  AO.DOWN_GRACE = 3000;
  let downTimer = null, downShown = false;
  function drawDown(down) {
    downShown = down;
    const dot = $("#hostdot"); if (dot) dot.classList.toggle("down", down);
    const b = $("#agentdown"); if (b) b.classList.toggle("hidden", !down);
  }
  function setDown(down) {
    if (down) { if (!downTimer && !downShown) downTimer = setTimeout(() => { downTimer = null; drawDown(true); }, AO.DOWN_GRACE); return; }
    clearTimeout(downTimer); downTimer = null;
    drawDown(false);  // a banner the server rendered at load included
  }
  AO.setDown = setDown;

  // ---- Org (design §4.5 screen 1) ----
  // The page is one or more `.tgroup` sections, each an optional header plus its own `.grid`: one
  // per team when any session carries a `team` badge or any team is defined (design §4.5a **team
  // groups**, §4.9), and one unnamed, headerless group otherwise. One order, no control (design
  // §4.5, 2026-09-18): inside a group the manager's card, then urgency, then name.
  const sections = () => $$("#groups .tgroup");
  function layout() {
    const box = $("#groups"); if (!box) return;
    sections().forEach((sec) => {
      const grid = $(".grid", sec), manager = sec.dataset.manager || "";
      // a team's + card (§4.5a *team card: + card*, TD-379) is no session: it is not sorted, and
      // placing every session from index 0 leaves it last
      const cards = $$(".sc:not(.plus)", grid);
      // `card_order` in cards.py: urgency, then an unseen session first (TD-1228), then an interactive
      // session ahead of an unattended one (TD-095)
      cards.sort((a, b) => (b.dataset.id === manager) - (a.dataset.id === manager) || (+a.dataset.rank - +b.dataset.rank)
        || (!!b.dataset.unseen - !!a.dataset.unseen) || (!!b.dataset.mine - !!a.dataset.mine)
        || a.dataset.name.localeCompare(b.dataset.name))
        .forEach((c, i) => AO.placeAt(grid, c, i));
    });
    applyFilter();
    const shown = $$("#groups .sc:not(.plus)").filter((c) => !c.hidden);
    // the Org's title line; the Repo page draws the cards without it (TD-740)
    if ($("#count")) $("#count").textContent = `${shown.length} session${shown.length === 1 ? "" : "s"}`;
    if ($("#empty")) $("#empty").hidden = shown.length > 0;
    const counts = {}; shown.forEach((c) => (counts[c.dataset.state] = (counts[c.dataset.state] || 0) + 1));
    if ($("#badges")) $("#badges").innerHTML = [["needs-you", "needs", "needs you"], ["limited", "limited", "limited"], ["stalled?", "stalled", "stalled"]]
      .filter(([k]) => counts[k]).map(([k, cls, l]) => `<span class="pill s-${cls}"><span class="dot"></span>${counts[k]} ${l}</span>`).join("");
    syncTeams();
  }
  // The Org's filter box (§4.5a **filter…**, TD-418, built by TD-428): words, each one a test, and a
  // card is shown when it passes them all. `team:<name>` is the form the card's team badge writes: an
  // exact match on the badge, not a substring of the card's text, so a team whose name also appears
  // in a branch stays clean. `state:<word>` is the form the rollup's Agents pills write (TD-176): the
  // card's pill word, hyphenated — `needs-you`, `working`, `on-call`. `mine`, the whole word alone,
  // is the person's own — the interactive sessions — `unseen`, the whole word alone, the cards carrying
  // the unseen mark whatever their pill (TD-1228), and `kind:command` shows the command runs,
  // hidden without it (the two in place of the *mine* toggle and the *show command runs* box). Any
  // other word is text the card must contain.
  AO.orgWords = function (raw) {
    const w = { team: null, state: null, mine: false, unseen: false, command: false, text: [] };
    String(raw || "").trim().split(/\s+/).filter(Boolean).forEach((word) => {
      const low = word.toLowerCase();
      if (low.startsWith("team:")) w.team = low.slice(5);
      else if (low.startsWith("state:")) w.state = low.slice(6);
      else if (low === "mine") w.mine = true;
      else if (low === "unseen") w.unseen = true;
      else if (low === "kind:command") w.command = true;
      else w.text.push(low);
    });
    return w;
  };
  // A team badge or an Agents pill presses one word (`team:<name>`, `state:<word>`): it replaces a
  // word of the same prefix, or is added, and pressed again it is taken out — the box's other words
  // (`mine`, `kind:command`, text) stay as they were. A bare word (`unseen`) is added or taken out alone.
  AO.orgToggleWord = function (raw, word) {
    const prefix = word.slice(0, word.indexOf(":") + 1).toLowerCase(), low = word.toLowerCase();
    const words = String(raw || "").trim().split(/\s+/).filter(Boolean);
    const had = words.some((w) => w.toLowerCase() === low);
    const rest = words.filter((w) => (prefix ? !w.toLowerCase().startsWith(prefix) : w.toLowerCase() !== low));
    return (had ? rest : [...rest, word]).join(" ");
  };
  // `c` is what a card says of itself: its `data-*` (`kind`, `team`, `pill`, `mine`, `unseen`) and its text.
  AO.orgPasses = function (c, w) {
    if (c.kind === "command" && !w.command) return false;
    if (w.team !== null && (c.team || "").toLowerCase() !== w.team) return false;
    if (w.state !== null && (c.pill || "") !== w.state) return false;
    if (w.mine && !c.mine) return false;
    if (w.unseen && !c.unseen) return false;
    const text = (c.text || "").toLowerCase();
    return w.text.every((t) => text.includes(t));
  };
  function applyFilter() {
    const raw = ($("#filter") ? $("#filter").value : "").trim(), words = AO.orgWords(raw);
    // `kind:command` alone shows more than the bare page, so it is no filter: the + card stays
    const filtering = words.team !== null || words.state !== null || words.mine || words.unseen || words.text.length > 0;
    $$("#groups .sc").forEach((c) => {
      if (c.classList.contains("plus")) { c.hidden = filtering; return; }  // a filter hides the + card (§4.5a)
      c.hidden = !AO.orgPasses({ ...c.dataset, text: c.textContent }, words);
    });
    // A group with nothing left to show goes away with its header; the empty page says so once.
    // A team's card stays while no filter is set, sessions or none: it is where Start lives.
    sections().forEach((sec) => {
      sec.hidden = !$$(".sc", sec).some((c) => !c.hidden) && (filtering || !sec.dataset.team);
      sec.classList.toggle("filtering", filtering);  // a filter shows what it matched, folded or not
    });
    // a repo's line, and a project's heading, hide when the filter hides everything under them
    // (§4.9 *The Sessions page*, TD-725), and show again with the first match
    $$("#groups .rline").forEach((line) => {
      line.hidden = filtering && !sections().some((s) => s.dataset.repo === line.dataset.repo && !s.hidden);
    });
    $$("#groups .phead").forEach((head) => {
      head.hidden = filtering && !$$("#groups .rline").some((l) => l.dataset.project === head.dataset.project && !l.hidden);
    });
    syncLineFacets();
  }
  // The server derives the groups on every render and every delta (only it sees the whole fleet),
  // so a badge or `controllers` change moves cards between groups here without a page reload.
  // `groups` null means the flat grid: one unnamed section, no header anywhere.
  function syncGroups(gs, drop = false) {
    const box = $("#groups"); if (!box) return;
    box.classList.toggle("flat", !gs);
    const wanted = gs || [{ team: "", key: "", manager: "", ids: $$("#groups .sc:not(.plus)").map((c) => c.dataset.id), html: "" }];
    // a scrolled list keeps where the person left it (TD-205): every summary's boxes are read here,
    // before anything moves — the read forces a layout, and one taken halfway through the swap let
    // the page's scroll anchoring chase a section being moved, throwing the page to the top (TD-224).
    // They are put back in syncSummaries, once the face each sits in is shown: a hidden box takes no scrollTop.
    // What the last swap kept and no summary took back (a team whose summary went) is dropped first.
    Object.keys(scrollKept).forEach((k) => delete scrollKept[k]);
    $$(".tsum", box).forEach((sum) => (scrollKept[sum.dataset.team] = AO.scrolls(sum)));
    const keep = [];
    let at = 0;  // where the next element goes among `#groups`' children: headings and lines count too
    const lines = $$("#groups .phead, #groups .rline"), kept = [];
    wanted.forEach((g) => {
      // a project heading or a repo's line (§4.9 *The Sessions page*, TD-725): swapped whole, in the server's order
      if (g.kind === "heading" || g.kind === "repo") {
        const tpl = document.createElement("template"); tpl.innerHTML = g.html.trim();
        const fresh = tpl.content.firstElementChild, old = lines.find((l) => l.dataset.key === g.key);
        const ringBack = !!old && old.contains(document.activeElement);  // a ringed line keeps the ring
        if (old) old.remove();
        const fsum = $(".tsum", fresh); if (fsum) showSummary(fsum);
        AO.placeAt(box, fresh, at++); kept.push(fresh);
        if (ringBack) fresh.focus({ preventScroll: true });
        return;
      }
      const key = g.key !== undefined ? g.key : g.team;
      let sec = sections().find((s) => (s.dataset.key !== undefined ? s.dataset.key : s.dataset.team) === key);
      if (!sec) {
        sec = document.createElement("section");
        sec.className = "tgroup"; sec.dataset.team = g.team;
        sec.innerHTML = '<div class="grid"></div>';
      }
      sec.dataset.key = key;
      sec.dataset.repo = g.repo || ""; sec.dataset.project = g.project || "";
      sec.dataset.manager = g.manager || "";
      sec.dataset.live = g.live || 0;
      let head = $(".ghead", sec);
      if (g.html) {
        if (!head) { head = document.createElement("div"); head.className = "row gap wrap ghead"; sec.prepend(head); }
        head.innerHTML = g.html;
        AO.applyHelpMarks(head);  // the header's *i* panel comes back as this browser left it
      } else if (head) head.remove();
      // a live team's summary (TD-176 slice 3): swapped whole, between the header and the grid
      let sum = $(".tsum", sec);
      if (g.summary) {
        const tpl = document.createElement("template"); tpl.innerHTML = g.summary.trim();
        const fresh = tpl.content.firstElementChild;
        showSummary(fresh);  // the person's own faces before it is inserted, so it lands at the height it keeps
        if (sum) {
          const kept = AO.denyWhys(sum);
          sum.replaceWith(fresh); AO.restoreDenyWhys(fresh, kept);
        }
        else { const h = $(".ghead", sec); if (h) h.after(fresh); else sec.prepend(fresh); }
      } else if (sum) sum.remove();
      const grid = $(".grid", sec);
      (g.ids || []).forEach((id) => { const c = $(`#card-${CSS.escape(id)}`); if (c && c.parentElement !== grid) grid.appendChild(c); });
      // each member's lane count (TD-484): a sibling's claim moves this card's count with no delta of its own
      Object.entries(g.lanes || {}).forEach(([id, html]) => {
        const pill = $(`#card-${CSS.escape(id)} .r1 .pill`); if (!pill) return;
        const old = $(".lanecount", pill);
        if (old && old.outerHTML === html) return;
        if (old) old.remove();
        if (html) pill.insertAdjacentHTML("beforeend", html);
      });
      // the team's + card (TD-379): drawn by the server on a defined team, kept as it is, gone with the definition
      const plus = $(".sc.plus", grid);
      if (g.plus && !plus) { const tpl = document.createElement("template"); tpl.innerHTML = g.plus.trim(); grid.appendChild(tpl.content.firstElementChild); }
      else if (!g.plus && plus) { AO.handRing(plus); plus.remove(); }
      AO.placeAt(box, sec, at++);  // in the server's order
      keep.push(sec);
    });
    lines.forEach((l) => { if (!kept.includes(l)) { AO.handRing(l); l.remove(); } });
    sections().forEach((sec) => {
      if (keep.includes(sec)) return;
      // A card the server did not list keeps its place on the page — somewhere it can be seen: the
      // first group may now be a stopped team, folded (review of PR #226), so *No team* or a live
      // team is preferred.
      const dest = keep.find((k) => !k.dataset.team) || keep.find((k) => +k.dataset.live) || keep[0];
      const home = !drop && dest && $(".grid", dest);
      $$(".sc:not(.plus)", sec).forEach((c) => { if (home) home.appendChild(c); else { AO.handRing(c); c.remove(); } });
      sec.remove();
    });
    // the Repo page (`drop`, TD-740) is one repo's items: a card no item lists now is another repo's
    if (drop) {
      const ids = new Set(wanted.flatMap((g) => g.ids || []));
      $$("#groups .sc:not(.plus)").forEach((c) => { if (!ids.has(c.dataset.id)) { AO.handRing(c); c.remove(); } });
    }
  }
  // The Repo page's items among a delta's groups (§4.5 screen 11, TD-740): the repo's line, its teams'
  // cards and its no-team strip — `repo_items`' test, on what the stream sends. `undefined` for the
  // flat page's `null`, which names no repo: the page keeps what it drew.
  AO.repoItems = function (gs, repo) {
    if (!gs) return undefined;
    return gs.filter((g) => g.key === "repo:" + repo || ((g.kind === "team" || g.kind === "strip") && g.repo === repo));
  };
  // A delta on the Org's stream, applied to the page's `#groups` (§4.5a *team groups*): a card swapped
  // or placed, the groups and the rollup re-sent. `repo` is the Repo page's (TD-740): only its items
  // are kept, and a new card of another repo is never put in.
  function groupsEvent(ev, repo) {
    const cut = (gs) => (repo ? AO.repoItems(gs, repo) : gs);
    const sync = (gs) => { const got = cut(gs); if (got !== undefined) syncGroups(got, !!repo); };
    if (ev.event === "session") {
      const old = $(`#card-${CSS.escape(ev.id)}`);
      const tpl = document.createElement("template"); tpl.innerHTML = ev.html.trim();
      const fresh = tpl.content.firstElementChild;
      if (old) {
        // a delta redraws the card; a menu the person has open stays open (TD-121), as a Deny reason stays typed
        // and a ringed card stays ringed (TD-124)
        const kept = AO.denyWhys(old), menu = !!$("details.more[open]", old), ring = document.activeElement === old;
        old.replaceWith(fresh); AO.restoreDenyWhys(fresh, kept);
        if (ring) fresh.focus({ preventScroll: true });
        const d = menu && $("details.more", fresh); if (d) d.open = true;
      }
      else if (!repo || (cut(ev.groups) || []).some((g) => (g.ids || []).includes(ev.id))) {
        // syncGroups below moves it into its own group; with no grid yet (a repo's first strip), the box holds it
        const grid = $("#groups .tgroup .grid") || $("#groups");
        if (grid) grid.appendChild(fresh);
      }
      // TD-156 (g): Paul saw two cards named designer-ao-1 after a resume superseded the exited
      // record of that name. The swap above is by id, so a second element needs a second insert
      // of one id, and the cause is not reproduced yet; until it is, a delta leaves one card per id.
      $$(`[id="card-${CSS.escape(ev.id)}"]`).slice(1).forEach((dup) => dup.remove());
      if (ev.groups !== undefined) sync(ev.groups);
      if (ev.rollup !== undefined) AO.swapRollup(ev.rollup);
      AO.markPopped(fresh);
      layout();
    } else if (ev.event === "gone") {
      const c = $(`#card-${CSS.escape(ev.id)}`); if (c) { AO.handRing(c); c.remove(); }
      if (ev.groups !== undefined) sync(ev.groups);
      if (ev.rollup !== undefined) AO.swapRollup(ev.rollup);
      layout();
    } else if (ev.event === "groups") {
      // the repo facts or a doing call moved (TD-176): the summaries are in the groups
      sync(ev.groups);
      if (ev.rollup !== undefined) AO.swapRollup(ev.rollup);
      layout();
    }
  }
  // The presses on a team's card — Start, Wind down, Stop now, Forget all, Apply, the fold, a facet's
  // selector — the same on the Org and on the Repo page (TD-740), which draws the cards by the same partials
  function wireGroups(box) {
    box.addEventListener("click", (e) => {
      const b = e.target.closest("[data-team-act]");
      // a concluded team's Start closes its sessions first, and its confirm names them (TD-099); a
      // Start reads the lanes first (TD-265)
      if (b && b.dataset.teamAct === "start") return startPress(b);
      if (b) return b.dataset.confirm && !confirm(b.dataset.confirm) ? undefined : teamAct(b.dataset.team, b.dataset.teamAct, b);
      const fa = e.target.closest("[data-forget-all]");
      if (fa) return confirm(fa.dataset.confirm) ? forgetAll(fa) : undefined;
      const ap = e.target.closest("[data-flow-apply]");
      if (ap) return confirm(ap.dataset.confirm) ? flowApply(ap) : undefined;
      const f = e.target.closest("[data-fold]");
      if (f) return toggleFold(f.closest(".tgroup"));
      // the header's row is the fold's mouse target (TD-194): not a press on its controls, links,
      // inputs or marks, nor one that ends a text selection, so a name can still be copied
      const head = e.target.closest(".tgroup > .ghead");
      if (head && $(".fold", head) && !e.target.closest(FOLD_SKIP) && !String(window.getSelection ? window.getSelection() : "")) {
        return toggleFold(head.parentElement);
      }
      const p = e.target.closest(".tsum .seg[data-pick] button");
      if (p && !p.disabled) pickSummary(p);
    });
  }
  Object.assign(AO, { orgLayout: layout, orgSyncGroups: syncGroups, orgGroupsEvent: groupsEvent });  // run under node by tests/test_ui_org_plus.py (TD-390)
  // ---- a team's card: the fold, and a request in flight (design §4.5a *team card: fold*) ----
  // Any team with sessions folds to its header, by the header's row or its *n sessions* button. A
  // team opens as it did before anyone chose — open while something is live (a concluded team is
  // live), folded with nothing live — and a person's choice, once pressed, wins whatever the team's
  // state becomes (TD-194). *No team* is a section, not a card, and never folds.
  const foldKey = (team) => "fold:" + team;
  const FOLD_SKIP = "button, a, input, select, textarea, summary, label, .badge, .pill, .helppanel, .answeredmark, .prswaiting, .flowchanged";
  AO.teamFolded = (team, live, get) => !!team && !!get(foldKey(team), !+live);
  const isFolded = (sec) => !!$(".ghead .fold", sec) && AO.teamFolded(sec.dataset.team, sec.dataset.live, store.get);
  // a repo's line draws its Repo facet only while no card of the repo shows one (§4.5a *team card: Repo
  // facet*, TD-1189): each card `{hidden, folded, filtering, facet}` — folded hides the summary unless a
  // filter is set; a repo with no team, or every card hidden, folded or drawing no Repo facet, shows the line's
  AO.lineFacetShown = (cards) => !cards.some((c) => !c.hidden && (!c.folded || c.filtering) && c.facet);
  function syncLineFacets() {
    $$("#groups .rline").forEach((line) => {
      const f = $(".rcompact", line); if (!f) return;  // the compact facet; the whole (`.rsum`) is the Repo page's (TD-1240)
      const cards = sections().filter((s) => s.dataset.repo === line.dataset.repo).map((s) => ({
        hidden: s.hidden, folded: isFolded(s), filtering: s.classList.contains("filtering"), facet: !!$(".tsum > .frepo", s),
      }));
      f.hidden = !AO.lineFacetShown(cards);
    });
  }
  function toggleFold(sec) {
    store.set(foldKey(sec.dataset.team), !isFolded(sec));
    syncTeams();
  }
  // a press on the rollup's *answer needed* or *asked you* (§4.5a *Sessions: rollup*, TD-924): the
  // filter box cleared first, since the count reads every counted session whatever the filter shows,
  // then the team it goes to opened when folded, the opening stored as a press on its header is
  AO.rollupGo = function (team, filter, folded, set) {
    if (filter) filter.value = "";
    if (team && folded) set(foldKey(team), false);
  };
  // ---- the rollup's rows (design §4.5a *Sessions: rollup*, *rollup: press and menus*; TD-1203, built by
  // TD-1204). A row's key is its layout item's (`team:<name>`, `repo:<name>`, `strip:<repo>`, `norepo`) and
  // its hash the URL's (`team=<name>`, …): a press lands on the item, a load with the hash does once.
  const HASH_KEY = { team: "team:", repo: "repo:", strip: "strip:" };
  AO.rollupKey = function (hash) {
    const h = String(hash || "").replace(/^#/, "");
    if (h === "norepo") return "norepo";
    const at = h.indexOf("="), kind = h.slice(0, at), name = at > 0 ? h.slice(at + 1) : "";
    if (!(kind in HASH_KEY) || !name) return "";
    try { return HASH_KEY[kind] + decodeURIComponent(name); } catch (e) { return ""; }
  };
  AO.rollupHash = function (key) {
    if (key === "norepo") return "norepo";
    const kind = Object.keys(HASH_KEY).find((k) => key.startsWith(HASH_KEY[k]));
    return kind ? `${kind}=${encodeURIComponent(key.slice(HASH_KEY[kind].length))}` : "";
  };
  // the press: the filter box cleared when it hides the target, a folded team opened and the opening stored,
  // the heading scrolled into view below the held bar and marked for 1.2 s, the hash written. False when the
  // page draws nothing of that key, and nothing moves.
  function rollupLand(key) {
    const find = () => $$("#groups [data-key]").find((el) => el.dataset.key === key);
    let el = find(); if (!el) return false;
    const f = $("#filter");
    if (f && f.value && !el.getClientRects().length) { f.value = ""; layout(); el = find() || el; }
    if (el.classList.contains("tgroup") && isFolded(el)) { AO.rollupGo(el.dataset.team, null, true, store.set); layout(); el = find() || el; }
    const head = $(".ghead", el) || el;
    head.scrollIntoView({ block: "start" });
    if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
      head.classList.add("landed"); setTimeout(() => head.classList.remove("landed"), 1200);
    }
    history.replaceState(null, "", "#" + AO.rollupHash(key));
    return true;
  }
  // the two menus, one open at a time; a delta's swap waits while one is (`AO.swapRollup`), and on close
  // focus goes back to the same row's same button, found by the row's key, or the first row's link
  let rollupMenu = null, rollupHeld = null;
  function rollupClose(refocus) {
    if (!rollupMenu) return;
    const { btn, menu } = rollupMenu;
    menu.hidden = true; btn.setAttribute("aria-expanded", "false"); rollupMenu = null;
    if (rollupHeld !== null) {
      const row = btn.closest("tr").dataset.row, which = btn.dataset.menu, html = rollupHeld;
      rollupHeld = null; AO.swapRollup(html);
      // focus goes back only on a close from the menu itself (Esc, an item): a press elsewhere keeps its own
      if (refocus) { const to = rollupButton(row, which) || $("#rollup .ru-go"); if (to) to.focus({ preventScroll: true }); }
    } else if (refocus) btn.focus({ preventScroll: true });
  }
  const rollupButton = (row, which) => {
    const tr = $$("#rollup tr[data-row]").find((el) => el.dataset.row === row);
    return tr ? $(`[data-menu="${which}"]`, tr) : null;
  };
  function rollupOpen(btn) {
    if (rollupMenu && rollupMenu.btn === btn) return rollupClose(true);
    const row = btn.closest("tr").dataset.row, which = btn.dataset.menu;
    rollupClose(false);
    // the close may have applied a held swap: the button pressed is then the fresh row's, found by its key
    if (!btn.isConnected) btn = rollupButton(row, which);
    if (!btn) return;
    const menu = btn.nextElementSibling;
    menu.hidden = false; btn.setAttribute("aria-expanded", "true"); rollupMenu = { btn, menu };
    const first = $("[role=menuitem]", menu); if (first) first.focus();
  }
  AO.swapRollup = function (html) {
    const box = $("#rollup"); if (!box) return;
    if (rollupMenu) { rollupHeld = html; return; }
    box.innerHTML = html;
    syncSummaries();  // the window's PR words and the copied counts, which the server's markup does not know
  };
  function rollupKeys(e) {
    if (!rollupMenu || !(rollupMenu.menu.contains(e.target) || e.target === rollupMenu.btn)) return;
    const items = $$("[role=menuitem]", rollupMenu.menu), i = items.indexOf(document.activeElement);
    // the menu's keys are its own: the page's ring (`j` / `k`, the arrows) never moves past an open menu
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); rollupClose(true); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); e.stopPropagation();
      const n = items.length, j = e.key === "ArrowDown" ? (i + 1) % n : (i - 1 + n) % n;
      if (items[j]) items[j].focus();
    } else if (e.key === "Tab") rollupClose(false);
  }
  // a press inside the rollup: a menu's button, an item (the menu closed first, then the act with its
  // control's own confirm, or the link), a row anywhere but its buttons, an Agents pill, *n from teams*
  function rollupPress(e) {
    const btn = e.target.closest("[data-menu]");
    if (btn) { e.preventDefault(); return rollupOpen(btn); }
    const item = e.target.closest("[role=menuitem]");
    if (item) {
      rollupClose(true);
      if (item.dataset.press) {
        const sec = sections().find((s) => s.dataset.key === "team:" + item.dataset.team);
        const b = sec && $$(".ghead [data-team-act]", sec).find((x) => x.dataset.teamAct === item.dataset.press);
        if (b) b.click();
        return;
      }
      if (!item.matches("[data-open-team], [data-open-card]")) return;  // Add entry…'s own handler, or a link
    }
    const go = e.target.closest("[data-open-team], [data-open-card]");
    if (go) {
      e.preventDefault();
      const team = go.dataset.openTeam || "", sec = team ? sections().find((s) => s.dataset.team === team) : null;
      AO.rollupGo(team, $("#filter"), !!sec && isFolded(sec), store.set);
      layout();
      const at = document.getElementById(go.getAttribute("href").slice(1));
      if (at) at.scrollIntoView({ block: "start" });
      return;
    }
    const pill = e.target.closest("[data-state-filter], [data-word-filter]");
    if (pill) {
      const f = $("#filter");
      f.value = AO.orgToggleWord(f.value, pill.dataset.wordFilter || "state:" + pill.dataset.stateFilter);
      return layout();
    }
    const row = e.target.closest("tr[data-row]");
    if (row && !e.target.closest(".ru-menu, button, .ru-tot a")) { e.preventDefault(); rollupLand(row.dataset.row); }
  }
  function syncTeams() {
    sections().forEach((sec) => {
      const team = sec.dataset.team, b = $(".ghead .fold", sec), head = $(".ghead", sec);
      const folded = isFolded(sec);
      sec.classList.toggle("folded", folded);
      // what the button shows and hides: the card's body, the summary and the grid, by id — the
      // summary keeps the server's `tsum-<team>`, which the rollup's links land on
      const body = [$(".tsum", sec), $(".grid", sec)].filter(Boolean);
      body.forEach((el) => { if (!el.id) el.id = `tgrid-${team}`; });
      if (b) {
        b.textContent = `${folded ? "▸" : "▾"} ${b.dataset.n} session${b.dataset.n === "1" ? "" : "s"}`;
        b.setAttribute("aria-expanded", folded ? "false" : "true");
        b.setAttribute("aria-controls", body.map((el) => el.id).join(" "));
      }
      // a folded team's header is a stop in the ring in place of its cards (§4.5a *Sessions: keys*)
      if (head) { if (b) head.tabIndex = folded ? 0 : -1; else head.removeAttribute("tabindex"); }
    });
    // a header re-rendered for a delta must not re-arm a request in flight
    $$("#groups .ghead [data-team-act]").forEach((b) => (b.disabled = pendingTeams.has(b.dataset.team)));
    $$("#groups .ghead [data-forget-all]").forEach((b) => (b.disabled = pendingTeams.has(b.dataset.forgetAll)));
    syncAnsweredMarks();  // …nor lose the answered-for-you mark the browser counted (§4.9b)
    syncSummaries();
    syncLineFacets();  // a fold or a swap may show or hide a card's Repo facet (TD-1189)
  }
  // ---- a team's summary: its selectors (design §4.5a *team card: Repo facet*, *Answer needed /
  // Doing*, TD-176 slice 3). Every variant is in the markup; these pick which shows. The window
  // picker is **one value per browser** for every picker on the page; the Technical debt selector
  // is remembered per team; the answer / doing toggle is the person's until the set of pending
  // answers changes, and a new one flips it back to *answer*. TDs in motion's *in motion · completed*
  // is stored per team, as the fold is: a stored pick wins whatever the team then holds, and until one
  // the server's default — *in motion* while the team holds a claim (TD-1189).
  AO.motionFace = (team, dflt, get) => {
    const v = get("motion:" + team, dflt || "motion");
    return v === "motion" || v === "completed" ? v : dflt || "motion";  // a stale key never blanks the facet
  };
  const faceFlip = {};  // team → {key, face}: a flip, held while the pending answers are the same
  const scrollKept = {};  // team → the summary's scrolled boxes, from the swap to the next sync
  function summaryState(sum) {
    const team = sum.dataset.team, key = sum.dataset.answerKey || "";
    const flip = faceFlip[team];
    const face = flip && flip.key === key ? flip.face : sum.dataset.faceDefault || "doing";
    const motion = AO.motionFace(team, sum.dataset.motionDefault, store.get);
    return { led: store.get("led:" + team, "open"), win: store.get("win", "day"), face, motion };
  }
  function syncSummaries() {
    AO.showDoingAges(); // the Doing rows just swapped in: their tooltips in the reader's clock (TD-232)
    // the rollup's window picker is the same one value (§4.5a *Sessions: rollup*), and its *in the
    // Inbox* is the top bar's count
    const ro = $("#rollup .rollup");
    if (ro) {
      const win = store.get("win", "day");
      $$(".wv", ro).forEach((el) => (el.hidden = el.dataset.wv !== win));
      $$(".seg[data-pick=win] button", ro).forEach((b) => b.setAttribute("aria-pressed", b.dataset.v === win ? "true" : "false"));
      const n = $("#personneeds"), into = $("[data-inbox-needs]", ro);
      if (n && into) into.textContent = n.textContent.trim() || "0";
      const q = $("#queueneeds"), qinto = $("[data-queue-needs]", ro);  // *q on the Queue*: the tab's number
      if (q && qinto) qinto.textContent = q.textContent.trim() || "0";
      // …and *m overdue* beside it (§4.5 screen 1, TD-178), from the last poll; unknown keeps what it showed
      const od = $("[data-inbox-overdue]", ro);
      if (od && overdueN !== null) { od.textContent = String(overdueN); od.parentElement.classList.toggle("hidden", !overdueN); }
    }
    $$(".tsum").forEach((sum) => {
      showSummary(sum);
      AO.restoreScrolls(sum, scrollKept[sum.dataset.team]); delete scrollKept[sum.dataset.team];
    });
  }
  function showSummary(sum) {
    const st = summaryState(sum);
    $$(".lv", sum).forEach((el) => (el.hidden = el.dataset.lv !== st.led));
    $$(".wv", sum).forEach((el) => (el.hidden = el.dataset.wv !== st.win));
    $$(".fv", sum).forEach((el) => (el.hidden = el.dataset.fv !== st.face));
    $$(".mv", sum).forEach((el) => (el.hidden = el.dataset.mv !== st.motion));
    $(".fface", sum)?.classList.toggle("answering", st.face === "answer" && !!sum.dataset.answerKey);
    $$(".seg[data-pick]", sum).forEach((seg) => {
      const v = st[seg.dataset.pick];
      $$("button", seg).forEach((b) => b.setAttribute("aria-pressed", b.dataset.v === v ? "true" : "false"));
    });
  }
  function pickSummary(b) {
    const sum = b.closest(".tsum"), pick = b.closest(".seg").dataset.pick, v = b.dataset.v;
    if (pick === "win") store.set("win", v);
    else if (!sum) return;
    else if (pick === "led") store.set("led:" + sum.dataset.team, v);
    else if (pick === "motion") store.set("motion:" + sum.dataset.team, v);
    else faceFlip[sum.dataset.team] = { key: sum.dataset.answerKey || "", face: v };
    syncSummaries();
  }
  // design §4.5a team card **Forget all** (TD-071 item 1): the Forget each card carries, one after
  // another — the same route and the same `remove` — so a record the agent refuses (a suspended one,
  // §4.8a) is refused in its own words and the rest go on. The cards leave as the removals land.
  async function forgetAll(btn) {
    const team = btn.dataset.forgetAll, ids = (btn.dataset.ids || "").split(" ").filter(Boolean);
    if (pendingTeams.has(team)) return;
    pendingTeams.add(team); btn.disabled = true;
    let gone = 0;
    try {
      for (const id of ids) {
        try {
          await AO.act(id, "remove", {});
          gone++;
          const c = $(`#card-${CSS.escape(id)}`); if (c) { AO.handRing(c); c.remove(); }
        } catch (err) { AO.toast(`${id}: ${err.message}`); }
      }
    } finally { pendingTeams.delete(team); btn.disabled = false; }
    AO.toast(`${team}: forgot ${gone} of ${ids.length}`, gone === ids.length);
  }
  // A stop returns before its manager does (design §4.9: the members settle first, which is minutes).
  // Nothing pushes that outcome, so the page asks for it — bounded, and only while one is pending —
  // rather than leaving a failure nobody ever sees (design §4.5 "Errors"; review of PR #124).
  async function watchStop(name, manager) {
    for (let i = 0; i < 90; i++) {
      await new Promise((r) => setTimeout(r, 5000));
      let rows = [];
      try { rows = (await (await fetch("/api/teams")).json()).teams || []; } catch (e) { continue; }
      const row = rows.find((t) => t.name === name);
      if (!row) return;
      if (row.error) { AO.toast(`${name}: ${row.error}`); return; }
      if (!row.stopping) { AO.toast(`${name}: ${manager} stopped`, true); return; }
    }
    AO.toast(`${name}: ${manager} is still stopping — see the agent log`);
  }
  // The button is not the guard: a stop moves its members' states at once, each delta re-renders
  // the header, and the fresh Stop would be pressable while the first request is still out — a
  // second wrap-up prompt to every member (review of PR #183). The team's name is the guard.
  const pendingTeams = new Set();
  // design §4.5a team card **Start** (TD-262, built by TD-265; TD-563): what every lane the start creates —
  // the members', the manager's where it has one — holds is read on
  // the press. Every lane empty opens the Start anyway / Cancel dialog in place of starting — one
  // confirm, a concluded team's closes as its second line; otherwise a concluded team's own confirm
  // carries the lane line, and the start's toast says it. A ledger that cannot be read opens nothing.
  async function startPress(b) {
    const name = b.dataset.team;
    if (pendingTeams.has(name) || b.dataset.reading) return;  // one press at a time, the read included
    b.dataset.reading = "1";
    let picks = null;
    try {
      const r = await fetch(`/api/teams/${encodeURIComponent(name)}/lanes`);
      if (r.ok) picks = await r.json();
    } catch (e) {
    } finally {
      delete b.dataset.reading;
    }
    const line = (picks && picks.line) || "";
    if (picks && picks.empty) {
      const dlg = $("#startdlg");
      $("#starthead").textContent = `Start ${name}?`;
      $("#starttext").textContent = "Nothing to pick: every lane is empty, so the team will wind down as soon as it starts.";
      // the definition's renames and removals (§4.9, TD-706), then a concluded team's closes
      const first = [b.dataset.moved || "", b.dataset.closes ? `It first closes ${b.dataset.closes}.` : ""].filter(Boolean);
      $("#startcloses").textContent = first.join(" ");
      $("#startcloses").hidden = !first.length;
      $("#startlanes").textContent = line;
      if (dlg.open) return;
      dlg.returnValue = "";
      dlg.addEventListener("close", () => { if (dlg.returnValue === "go") teamAct(name, "start", b, true, line); }, { once: true });
      return dlg.showModal();
    }
    if (b.dataset.confirm && !confirm(b.dataset.confirm + (line ? `\n\n${line}` : ""))) return;
    return teamAct(name, "start", b, false, line);
  }

  // design §4.5a team card **flow changed — Apply** (§4.9c *Switching*, TD-309): `ao team flow <team>
  // --apply`'s act, one toast per member it applied, skipped or left with a reader, in its own words
  async function flowApply(btn) {
    const name = btn.dataset.flowApply;
    btn.disabled = true;
    try {
      const r = await fetch(`/api/teams/${encodeURIComponent(name)}/flow/apply`, { method: "POST" });
      let o = {}; try { o = await r.json(); } catch (e) {}
      if (!r.ok) throw new Error(o.detail || r.statusText);
      const lines = [...(o.applied || []), ...(o.skipped || []), ...(o.stays || [])].map((d) => d.line);
      if (!lines.length) AO.toast(`${name}: every live record already matches ${o.flow || "the definition"}`, true);  // no flow: its seats (TD-399)
      lines.forEach((l) => AO.toast(`${name}: ${l}`, true));
    } catch (e) {
      AO.toast(`${name}: ${e.message}`);
      btn.disabled = false;
    }
  }

  // design §4.5a *Settings page: Teams* **flow** (§4.9c *Switching*, TD-356, TD-359; the team card's
  // **Flow** pick moved there, TD-418): a Save writes the setting and nothing more — no confirm,
  // nothing relaunched; the running team moves on **Apply**, the one gate. The toast says which, and
  // what **Add entry**'s feature now opens
  AO.flowSet = (name, o) => {
    const moved = (o.differences || []).length;
    AO.toast(`${name}: flow set to ${o.flow}${moved ? " — Apply on the team card to switch the running team" : ""}`, true);
    if (o.feature) AO.toast(`${name}: Add entry's feature now opens a ${o.feature}`, true);
  };

  async function teamAct(name, what, btn, anyway = false, lanes = "") {
    if (pendingTeams.has(name)) return;
    pendingTeams.add(name);
    const stop = what !== "start";
    const url = `/api/teams/${encodeURIComponent(name)}/${stop ? "stop" : "start"}`;
    btn.disabled = true;
    try {
      const r = await fetch(url, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ now: what === "stopnow", anyway }),
      });
      let o = {}; try { o = await r.json(); } catch (e) {}
      // A refused start created nothing (design §4.9): the agent's own message is the whole report,
      // in a toast, as every other RPC error on this page is (design §4.5 "Errors").
      if (!r.ok) throw new Error(o.detail || r.statusText);
      // a concluded team's Start closed its sessions first (TD-099): said, since the cards it drew are gone
      const shut = (o.closed || []).length ? ` (closed ${(o.closed || []).map((c) => c.name).join(", ")} first)` : "";
      AO.toast(o.text || `${name}: ${(o.sessions || []).length} session${(o.sessions || []).length === 1 ? "" : "s"} started${shut}`, true);
      (o.moved || []).forEach((l) => AO.toast(`${name}: ${l}`, true));  // the definition's renames and removals (TD-706)
      if (lanes) AO.toast(`${name}: ${lanes}`, true);  // what the lanes held at the press (TD-265)
      // The same two things `ao team start|stop` says and a request could not: a member the
      // definition starts interactive is out of its manager's reach (design §9 invariant 5), and the
      // manager's own stop happens after the response (review of PR #124).
      (o.out_of_reach || []).forEach((who) =>
        AO.toast(`${name}: ${who} is interactive, so its manager cannot act on it — §9 invariant 5`));
      // TD-042: a brief written for one night cannot start the next. The team started; this is a note.
      (o.unrepeatable || []).forEach((w) => AO.toast(`${name}: ${w}`));
      // What `ao team start` prints to stderr and the team still started on: a techlead seat without
      // its primer, or one that came up under another id (design §4.9b).
      (o.notes || []).forEach((w) => AO.toast(`${name}: ${w}`));
      if (o.manager) watchStop(name, o.manager);
    } catch (e) {
      AO.toast(`${name}: ${e.message}`);
    } finally {
      pendingTeams.delete(name);
      btn.disabled = false;
      syncTeams();  // the button on the page now may not be the one that was pressed
    }
  }

  // ---- Inbox (design §4.5 screen 6, §4.5a **Inbox page**; TD-069 step 1) ----
  // The rows are rendered by the server, by the same template the page was rendered with, and a
  // poll swaps a whole section's markup: nothing here composes markup out of what a session wrote.
  // What lives in the browser is what belongs to this browser — the filter, the FYI fold — exactly
  // as the Org's filter and team folds do.
  const IN_SECS = ["needs", "steering", "waiting", "answered", "later", "fyi", "snoozed"];
  let landed = "";  // the row a `?row=` link landed on: marked until the page is left, across the poll's swaps

  // §4.5a **Snooze**: 1 h · tomorrow 08:00 · a date. Returned as a UTC instant, whole seconds,
  // which is what the entry stores; the prompt is in the person's own clock.
  // A board item's new `Due:` date (§4.5a Snooze ▾: +1 day · +1 week · a date), counted from the
  // later of today and the item's own date (`from`, a row coming up, TD-220), on this browser's own
  // calendar — the board's dates are civil dates, never instants — so a Snooze never brings a date nearer.
  function boardDue(when, from) {
    const day = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const d = new Date();
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(from || "");
    if (m) { const own = new Date(+m[1], +m[2] - 1, +m[3]); if (own > d) d.setTime(own.getTime()); }
    if (when === "1d" || when === "1w") { d.setDate(d.getDate() + (when === "1d" ? 1 : 7)); return day(d); }
    const s = prompt("Snooze to… (YYYY-MM-DD)", (d.setDate(d.getDate() + 1), day(d)));
    if (!s) return null;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(s.trim())) { AO.toast(`${s}: a date is YYYY-MM-DD`); return null; }
    return s.trim();
  }

  function snoozeUntil(when) {
    const iso = (d) => new Date(d.getTime() - d.getMilliseconds()).toISOString().replace(/\.\d+Z$/, "Z");
    const d = new Date();
    if (when === "1h") { d.setHours(d.getHours() + 1); return iso(d); }
    if (when === "tomorrow") { d.setDate(d.getDate() + 1); d.setHours(8, 0, 0, 0); return iso(d); }
    if (when === "1d") { d.setDate(d.getDate() + 1); return iso(d); }  // the promote row's (§4.5a)
    if (when === "1w") { d.setDate(d.getDate() + 7); return iso(d); }
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    const s = prompt("Snooze until… (YYYY-MM-DDTHH:MM, your own clock)", local);
    if (!s) return null;
    const t = new Date(s.trim());
    if (isNaN(t)) { AO.toast(`${s}: not a time I can read`); return null; }
    if (t <= new Date()) { AO.toast("that time has passed: a snooze goes forwards"); return null; }
    return iso(t);
  }

  // design §4.5a **Inbox: section heading, the i mark** (§4.5 screen 6 *Layout*, TD-082). The mark
  // is a `<button>`, so Enter and Space press it; the paragraph it holds is in the page always and
  // merely `hidden`, because it is also the button's `aria-describedby` and a description may
  // point at a hidden node but never at a missing one. Pressed, it opens **in place** under the
  // heading, pushing the rows down rather than covering one; which are open is remembered here.
  // Inside FYI's `<summary>` the press must not also fold the section, which is the stopPropagation.
  function setupInfoMarks() {
    $$(".inboxpage .imark").forEach((b) => {
      const para = document.getElementById(b.dataset.info);
      if (!para) return;
      const key = "inboxinfo:" + b.dataset.info;
      const show = (on) => { para.hidden = !on; b.setAttribute("aria-expanded", on ? "true" : "false"); if (on) para.classList.remove("peek"); };
      show(store.get(key, false));
      b.addEventListener("click", (e) => {
        e.preventDefault(); e.stopPropagation();
        const on = para.hidden;
        show(on); store.set(key, on);
      });
      // §4.5a: *a tooltip on hover **and keyboard focus***. `title` is the hover one — the UA's,
      // which is also what a page with no script still has — but no browser shows a `title` to a
      // keyboard, so focus gets the same words the other way: the very paragraph, floated over the
      // rows rather than pushing them down, which is what a press does. The same node, so the
      // tooltip and the description cannot drift apart. `:focus-visible`, so a mouse press — which
      // focuses too, and opens the paragraph in place — does not also float a copy of it.
      b.addEventListener("focus", () => { if (para.hidden && b.matches(":focus-visible")) para.classList.add("peek"); });
      b.addEventListener("blur", () => para.classList.remove("peek"));
    });
  }
  // §4.10 *Told on Telegram when nobody is looking* (TD-319 slice 3): `/inbox?row=<key>` scrolls to that
  // row and marks it — the rail cleared first when its picks hide it, a snoozed row's box opened — and
  // says *that row is gone — it was answered* when the page has no such row
  function landOn(id) {
    const find = () => $$(".inboxpage .mailrow").find((r) => r.dataset.msg === id);
    let r = find();
    if (r && r.hidden && $("#railclear")) { $("#railclear").click(); r = find(); }
    const gone = $("#landgone");
    if (!r) { if (gone) gone.classList.remove("hidden"); return; }
    landed = id;
    const box = r.closest("details"); if (box) box.open = true;
    r.classList.add("landed");
    r.focus({ preventScroll: true }); r.scrollIntoView({ block: "center" });
  }
  // §4.10: **Dismiss all** — the entries this browser has **on screen**, by id, never
  // *everything FYI holds now*: mail that arrived after the page was drawn is what must not go
  // unseen. The confirm says the number it is about, and the ids come off the DOM for that
  // reason. It sits in FYI's `<summary>`, so its press must not also fold the section.
  // §4.5a *Inbox: Answered for you, Dismiss all* (TD-599) is the same press on that group's rows,
  // with its own words: an answer dismissed takes its Overrule with it. The Queue's cards carry the
  // same press on a card's *Answered for you* and *FYI* (§4.5 screen 12, TD-828): `rows` is a selector,
  // or a function answering the rows, and `refresh` re-reads the page it is on.
  AO.DISMISS_ASK = {
    fyi: (n) => `Dismiss ${n} FYI ${n === 1 ? "entry" : "entries"}? Only the ones on screen now — anything that arrives after this is untouched.`,
    answered: (n) => `Dismiss the ${n} ${n === 1 ? "answer" : "answers"} on screen? Their Overrule goes with them.`,
  };
  AO.dismissOnScreen = (btn, rows, empty, ask, refresh) => {
    if (btn) btn.addEventListener("click", async (e) => {
      e.preventDefault(); e.stopPropagation();
      const on = typeof rows === "function" ? rows() : $$(rows);
      const ids = [...on].filter((r) => !r.hidden).map((r) => r.dataset.msg).filter(Boolean);  // on screen: a row the rail hides is not
      if (!ids.length) return AO.toast(empty, true);
      if (!confirm(ask(ids.length))) return;
      try {
        await act("person", "dismiss", { msg: ids });
        AO.toast(`dismissed ${ids.length} — the sender is told where one was owed`, true);
      } catch (err) { AO.toast(`dismiss failed: ${err.message}`); }
      if (refresh) refresh();
    });
  };

  AO.inbox = function () {
    const f = $("#ifilter");
    setupInfoMarks();
    $("#sec-fyi").open = store.get("inboxfyi", false);  // folded by default, remembered here
    // …but a fold the find opened is the find's, not the person's (§4.5 screen 6 *Find*)
    $("#sec-fyi").addEventListener("toggle", () => {
      if (findOpened.has("sec-fyi")) { if (!$("#sec-fyi").open) findOpened.delete("sec-fyi"); return; }
      store.set("inboxfyi", $("#sec-fyi").open);
    });
    // §4.9b *Answered for you*: open until the person folds it, and remembered here as FYI's is
    const ans = $("#sec-answered");
    if (ans) {
      ans.open = store.get("inboxanswered", true);
      ans.addEventListener("toggle", () => { store.set("inboxanswered", ans.open); markAnsweredSeen(); });
    }
    // the board's *not shown* fold (TD-220): its rows join the rail's *board items* while it is open
    document.addEventListener("toggle", (ev) => { if (ev.target.matches && ev.target.matches("details.boardfold")) inboxFilter(); }, true);
    // design §4.5 screen 6 *The rail* (TD-135): the picks are the page's URL. A bare `/inbox` takes
    // the browser's last picks and writes them back into the URL, so a link copied from the bar is
    // always the page as seen; a press is a history entry, so Back undoes it; typing is not.
    const fromUrl = AO.railPicks(location.search);
    const landing = AO.rowOfKey(new URLSearchParams(location.search).get("row"));  // read before the picks rewrite the URL
    const any = (p) => !!(p.team.length || p.repo.length || p.sec.length || p.kind.length || p.find);
    rail = any(fromUrl) ? fromUrl : AO.railPicks(store.get("inboxpicks", ""));
    const save = (push) => {
      const q = AO.railQuery(rail);
      store.set("inboxpicks", q);
      const url = location.pathname + q;
      if (url !== location.pathname + location.search) history[push ? "pushState" : "replaceState"](null, "", url);
    };
    save(false);
    f.value = rail.find;
    f.addEventListener("input", () => { rail.find = f.value.trim(); save(false); inboxFilter(); });
    window.addEventListener("popstate", () => { rail = AO.railPicks(location.search); f.value = rail.find; store.set("inboxpicks", AO.railQuery(rail)); inboxFilter(); });
    const toggle = (group, value) => {
      const on = rail[group].includes(value);
      rail[group] = on ? rail[group].filter((v) => v !== value) : [...rail[group], value];
      save(true); inboxFilter();
    };
    document.addEventListener("click", (e) => {
      const line = e.target.closest(".rail .railline, .railchips .railline");
      if (line) { e.preventDefault(); return toggle(line.dataset.group, line.dataset.value); }
      // the row's team badge is the same press as the rail's line for its team
      const b = e.target.closest(".mailrow .badge.team");
      if (b) { e.preventDefault(); return toggle("team", b.dataset.team || "none"); }
    });
    // §4.5 screen 6 *The message page* (TD-136): a mail row's text, and its *whole entry ›* link,
    // open the entry's page — carrying the list's picks for Back, and the list's order as filtered
    // for `j` / `k` there (this tab's own memory, `sessionStorage`)
    document.addEventListener("click", (e) => {
      const link = e.target.closest(".inboxpage .mailrow a.pagelink");
      const body = !link && e.target.closest(".inboxpage .mailrow[data-page] .body, .inboxpage .mailrow[data-page] > .subj");
      if (!link && !body) return;
      if (body && (e.target.closest("a, summary, button") || String(window.getSelection ? window.getSelection() : "").trim())) return;
      if (link && (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1)) return;  // a new tab is the browser's
      e.preventDefault();
      AO.openEntry(e.target.closest(".mailrow").dataset.msg);
    });
    $("#railclear").addEventListener("click", () => {
      rail = AO.railPicks(""); f.value = ""; save(true); inboxFilter();
    });
    // §4.5 screen 6 *Narrow* (TD-137): **Filters ▾** opens the sheet, and the sheet holds the rail
    // itself — moved in while it is open and back when it closes, so there is one set of toggles.
    const sheet = $("#railsheet"), railEl = $("#rail"), home = railEl && railEl.parentElement;
    if (sheet && railEl && home) {
      $("#railsheetbtn").addEventListener("click", () => { $("#railsheetbody").appendChild(railEl); sheet.showModal(); });
      $("#railsheetdone").addEventListener("click", () => sheet.close());
      sheet.addEventListener("close", () => { home.insertBefore(railEl, home.firstChild); });
      // widened past the breakpoint with the sheet open: the rail belongs beside the column again
      const wide = window.matchMedia ? window.matchMedia("(min-width: 721px)") : null;
      if (wide && wide.addEventListener) wide.addEventListener("change", (m) => { if (m.matches && sheet.open) sheet.close(); });
    }
    AO.dismissOnScreen($("#dismissall"), "#rows-fyi .mailrow", "nothing in FYI to dismiss", AO.DISMISS_ASK.fyi, refreshInbox);
    AO.dismissOnScreen($("#dismissanswered"), "#rows-answered .mailrow", "no answers on screen to dismiss", AO.DISMISS_ASK.answered, refreshInbox);
    AO.refreshInboxPage = refreshInbox;
    inboxFilter();
    // back from an entry's page: the list rings the row it came from (`#<id>`)
    const from = location.hash.slice(1);
    const row = from && $$(".inboxpage .mailrow").find((r) => r.dataset.msg === from && !r.hidden);
    if (row) { row.focus({ preventScroll: true }); row.scrollIntoView({ block: "center" }); }
    if (landing) landOn(landing);
    refreshInbox();
  };

  // design §4.5 *no silent failure path* / TD-029: **the terminal's two client rules, kept pure**,
  // for the reason `maySwapSection` below is — a rule that lives inside a closure is a rule no test
  // can reach, and TD-029's entry said for nine days that its client half could not be tested
  // "because it is JavaScript, which this repo has no harness for". The harness is the node probe
  // in `tests/test_ui_inbox.py`; what was missing was something for it to call.
  //
  // **The pane is gone for good.** `closed` or `pane: false` — from the record the page was drawn
  // with, or from a pushed delta, which is authoritative and arrives before any reconnect could.
  AO.paneIsGone = function (s) {
    return !!s && (s.state === "closed" || s.pane === false);
  };
  // **What a closed terminal socket means**, and it is the whole of TD-029's loop: a connection the
  // server accepts and then ends is *not* a working terminal, so the backoff must not reset here —
  // it resets on the first byte of pane output and nowhere else. `4404` is the server saying the
  // pane is gone, which is final and never retried. Everything else retries, with the delay
  // doubling to a ceiling. `opened` is whether the socket ever opened: a 1006 before it did is a
  // handshake that never reached the server, which is a different thing to say to a person.
  // `reason` is the close frame's, when there is one. It is **part of the sentence, so it is part
  // of the rule**: the caller appending it separately is how the two came apart in review — the
  // call site suppressed it for every 1006 where the original suppressed it only for a 1006 the
  // socket never opened. Nothing can reach that difference today (a 1006 is client-synthesised and
  // carries no reason, and this server sends none), which is exactly why it had to be closed here
  // rather than left as a comment.
  // The wheel over the terminal (design §4.6 *The mouse is the browser's*, TD-174): one animation
  // frame's notches, in lines, become one scroll message — `{scroll: up|down, lines: n}` — and the
  // fraction left over waits for the next frame, so a trackpad's small steps add up rather than
  // each scrolling a line. Nothing whole yet is no message.
  AO.wheelStep = function (acc) {
    const n = Math.trunc(acc);
    return { msg: n ? { scroll: n < 0 ? "up" : "down", lines: Math.abs(n) } : null, rest: acc - n };
  };
  // A finger's drag on the terminal (design §4.6 *A finger's drag scrolls it too*, TD-989): `total` is the
  // touch's vertical travel since it started, `sent` the travel already turned into scroll. Nothing while
  // the touch is still inside the 10 px slop and nothing has been sent; then all of `total - sent`, so the
  // first 10 px count once and nothing twice. The caller divides `add` by the cell height and negates it
  // into the wheel's accumulator: the content follows the finger, a drag down is `up`.
  AO.TOUCH_SLOP = 10;
  AO.touchStep = function (total, sent) {
    if (!sent && Math.abs(total) < AO.TOUCH_SLOP) return { add: 0, sent: 0 };
    return { add: total - sent, sent: total };
  };
  // The soft-key row (design §4.5a **Focus pane: soft-key row**, TD-990): a key's name to the bytes xterm.js
  // sends for it — an arrow `ESC [ A`–`D`, or `ESC O A`–`D` while the program has set application cursor
  // keys; null for a name the row does not have
  AO.softKey = function (name, appCursor) {
    const arrow = { Up: "A", Down: "B", Right: "C", Left: "D" }[name];
    if (arrow) return (appCursor ? "\x1bO" : "\x1b[") + arrow;
    if (/^[1-9]$/.test(name)) return name;
    return { Tab: "\t", Esc: "\x1b", Enter: "\r" }[name] || null;
  };
  // ...and whether it is drawn: where the terminal takes keys — neither ended nor unattended, the page
  // with a terminal (`paneGone` false). Its own state: never read from `readOnly`, which an attach resets
  AO.softShown = (v, paneGone) => !!v && !v.unattended && !["exited", "closed"].includes(v.state) && !paneGone;
  AO.termClose = function (code, opened, delay, reason) {
    if (code === 4404) return { retry: false, final: true, delay, why: "no terminal for this session" };
    if (code === 1006 && !opened) {
      const why = "websocket handshake failed (code 1006) — does your route to the UI pass websockets? ssh -L does";
      return { retry: true, final: false, delay: Math.min(delay * 2, 10000), why };
    }
    const why = `closed (code ${code}${reason ? ", " + reason : ""})`;
    return { retry: true, final: false, delay: Math.min(delay * 2, 10000), why };
  };

  // The **restarted** chip goes when `RESTART_WINDOW` passes its newest entry (§4.5a, TD-487), whether or
  // not a delta re-draws its card: each carries the instant as `data-until`, and a minute's look hides
  // the ones past it. The next render, which derives it again, agrees.
  AO.restartedExpired = function (until, now) {
    const t = Date.parse(until || "");
    return Number.isFinite(t) && now >= t;
  };
  setInterval(() => {
    const now = Date.now();
    document.querySelectorAll(".badge.restarted[data-until]").forEach((b) => {
      if (AO.restartedExpired(b.dataset.until, now)) b.classList.add("hidden");
    });
  }, 60000);

  // **The terminal mark** (design §4.6 *Reconnect contract*, *Attach behaviour with another client
  // present*; §4.5a; TD-474, TD-480): what the Focus terminal is doing, one mark at a time, in this
  // order — the socket closed with a retry pending, past a three-second grace (`retryAt`: when the
  // retry was scheduled, cleared by the next pane byte); another tmux client sizing the pane (the
  // bridge's `{clients, window}` frame: more than one client and a window that is not this grid);
  // a `working` session whose pane has drawn nothing for thirty seconds on an open socket (`lastByte`,
  // counted up each second; never on `idle`, where silence is normal). Null when none holds.
  AO.TERM_GRACE = 3000;
  AO.TERM_SILENT = 30000;
  AO.termMark = function (st, now) {
    if (st.retryAt != null && now - st.retryAt >= AO.TERM_GRACE) {
      return { kind: "reconnecting", text: "reconnecting…", title: "the terminal socket dropped and retries on its own — reload if it stays" };
    }
    const w = st.window, g = st.grid;
    if (st.clients > 1 && w && g && (w[0] !== g[0] || w[1] !== g[1])) {
      return { kind: "resized", text: "resized by another client", title: "another tmux client (a VS Code attach, a second tab) is sizing this pane — use one, or detach the other" };
    }
    if (st.open && st.state === "working" && st.lastByte != null && now - st.lastByte >= AO.TERM_SILENT) {
      const n = Math.floor((now - st.lastByte) / 1000);
      return { kind: "silent", text: `no output for ${n}s`, title: "the session reads working and the pane has drawn nothing — Transcript or `ao tail` say whether it is thinking or stuck" };
    }
    return null;
  };

  // **The disconnect card** (design §4.6 *The disconnect card*, §4.5a; TD-923): while the mark reads
  // *reconnecting…*, the spend the page last held. `held` is what `AO.dropRead` kept under
  // `ao.drop.<id>`: the Spend readings (`team` and `all`, each `day` and `week`), the chips' usage per
  // account, and `at`, when they were read. A row's figures are its seats' summed by `unit`, so a
  // subscription's `≈$` and a metered profile's `$` stay two figures where the Spend page folds a mixed
  // sum to `≈$`; *unweighed* tokens beside, as the page draws them (`figure` in spend.py); every kind of
  // token summed, the kinds on the hover. A reading the page never got is *no reading*.
  AO.DROP_KINDS = [["input", "input"], ["output", "output"], ["cache_read", "cache read"], ["cache_write", "cache write"]];
  AO.dropSum = function (reading, keep) {
    if (!reading || !Array.isArray(reading.seats)) return null;
    const out = { money: {}, unweighed: 0, tokens: {} };
    for (const [k] of AO.DROP_KINDS) out.tokens[k] = 0;
    for (const s of reading.seats) {
      if (!s || typeof s !== "object" || (keep && !keep(s))) continue;
      const unit = s.unit === "$" ? "$" : "≈$", fig = Number(s.figure) || 0;
      out.money[unit] = (out.money[unit] || 0) + fig;  // a unit with nothing spent still says which it is
      out.unweighed += Number(s.unweighed_tokens) || 0;
      const t = s.tokens && typeof s.tokens === "object" ? s.tokens : {};
      for (const [k] of AO.DROP_KINDS) out.tokens[k] += Number(t[k]) || 0;
    }
    return out;
  };
  // A sum as the card writes it: `{money, tok, kinds}`, or null for *no reading*.
  AO.dropSays = function (sum) {
    if (!sum) return null;
    const cash = (unit, v) => unit + Number(v).toLocaleString("en-US", Math.abs(v) >= 100
      ? { maximumFractionDigits: 0 } : { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const parts = ["≈$", "$"].filter((u) => sum.money[u]).map((u) => cash(u, sum.money[u]));
    let money = parts.join(" · ");
    if (sum.unweighed) money = parts.length ? `${money} + ${tokShort(sum.unweighed)} tok unweighed` : `unweighed · ${tokShort(sum.unweighed)} tok`;
    // nothing spent: a zero in the scope's own unit (a metered profile's `$0.00`), `≈$` where it has no seat
    if (!money) money = cash("$" in sum.money && !("≈$" in sum.money) ? "$" : "≈$", 0);
    const total = AO.DROP_KINDS.reduce((n, [k]) => n + sum.tokens[k], 0);
    const kinds = AO.DROP_KINDS.map(([k, word]) => `${word} ${sum.tokens[k].toLocaleString("en-US")}`).join(" · ");
    return { money, tok: `${tokShort(total)} tok`, kinds };
  };
  AO.dropCard = function (held, id, team, now) {
    held = held && typeof held === "object" ? held : {};
    now = typeof now === "number" ? now : Date.now();
    const read = (scope, w) => ((held[scope] || {})[w]) || null;
    const mine = (s) => Array.isArray(s.records) && s.records.includes(id);
    const row = (label, scope, keep) => ({
      label,
      day: AO.dropSays(AO.dropSum(read(scope, "day"), keep)),
      week: AO.dropSays(AO.dropSum(read(scope, "week"), keep)),
    });
    const rows = [row("this session", team ? "team" : "all", mine)];
    if (team) rows.push(row(`team ${team}`, "team", null));
    rows.push(row("all teams", "all", null));
    // the account's windows as the chip's hover reads them: label, percentage and reset, one a line
    const usage = held.usage && typeof held.usage === "object" ? held.usage : {};
    const names = Object.keys(usage), windows = [];
    for (const name of names) {
      const ws = Array.isArray((usage[name] || {}).windows) ? usage[name].windows : [];
      for (const w of ws) {
        if (!w || typeof w !== "object" || !w.label) continue;
        let line = names.length > 1 ? `${name} · ${w.label}` : String(w.label);
        if (Number.isFinite(w.pct)) line += ` ${w.pct}%`;
        const r = instant(w.resets);
        if (r !== null) {
          const d = new Date(r), pad = (n) => String(n).padStart(2, "0");
          line += ` · resets ${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()]} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
        }
        windows.push(line);
      }
    }
    const at = Number.isFinite(held.at) ? usageClock(held.at, now) : null;
    return { rows, windows, asof: at };
  };
  // The reading the card draws, taken at the Focus's load and at each reconnect's open — never while
  // the link is down — and kept in `sessionStorage` under the session's id, so the page the one reload
  // brings back draws it before its attach answers. A seat keeps only what the card sums.
  const dropKey = (id) => `ao.drop.${id}`;
  AO.dropHeld = function (id) {
    try { const h = JSON.parse(sessionStorage.getItem(dropKey(id)) || "null"); return h && typeof h === "object" ? h : null; } catch (e) { return null; }
  };
  const dropKeep = (id, held) => { try { sessionStorage.setItem(dropKey(id), JSON.stringify(held)); } catch (e) { /* no storage: the card reads no reading after a reload */ } };
  function chipUsage() {
    const out = {};
    for (const el of document.querySelectorAll("#usagechip [data-usage]")) {
      try { out[el.dataset.account] = JSON.parse(el.dataset.usage); } catch (e) { /* a chip with no reading */ }
    }
    return out;
  }
  AO.dropUsage = function (id) { const h = AO.dropHeld(id) || {}; h.usage = chipUsage(); dropKeep(id, h); };
  AO.DROP_FRESH = 30e3;  // a reading this young is not taken again: a socket that opens and ends retries often
  AO.dropRead = function (id, team, now) {
    now = typeof now === "number" ? now : Date.now();
    const was = AO.dropHeld(id);
    if (was && Number.isFinite(was.at) && now - was.at < AO.DROP_FRESH) return Promise.resolve(was);
    const got = {};
    const one = (scope, t, w) => fetch(`/api/spend?window=${w}&top=all${t ? `&team=${encodeURIComponent(t)}` : ""}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((j) => {
        if (!j || !Array.isArray(j.seats)) return;
        const seats = j.seats.filter((s) => s && typeof s === "object")
          .map((s) => ({ records: s.records, unit: s.unit, figure: s.figure, unweighed_tokens: s.unweighed_tokens, tokens: s.tokens }));
        (got[scope] = got[scope] || {})[w] = { seats };
      })
      .catch(() => { /* this one stays as the page last held it */ });
    const reads = [];
    for (const w of ["day", "week"]) {
      if (team) reads.push(one("team", team, w));
      reads.push(one("all", "", w));
    }
    return Promise.all(reads).then(() => {
      const h = AO.dropHeld(id) || {};
      for (const scope of Object.keys(got)) h[scope] = { ...(h[scope] || {}), ...got[scope] };
      if (Object.keys(got).length) h.at = now;
      h.usage = chipUsage();
      dropKeep(id, h);
      return h;
    });
  };

  // Deny's optional reason (design §4.5a, TD-117): one line beside Deny that goes back with the
  // refusal through the hook, for the session to read. Never required, so an empty box is a bare
  // Deny — the body carries no `reason` at all rather than an empty one.
  AO.denyBody = function (value) {
    const why = (value || "").trim();
    return why ? { reason: why } : {};
  };
  // The card, the Focus header and an Inbox row are redrawn from pushed deltas and polls, and a
  // redraw must not take a half-typed reason from under the person: read the boxes before it (by
  // session id), put them back after it.
  AO.denyWhys = function (root) {
    const kept = {};
    if (!root) return kept;
    root.querySelectorAll("input.denywhy").forEach((i) => {
      if (i.value || i === document.activeElement) kept[i.dataset.id] = { value: i.value, focused: i === document.activeElement };
    });
    return kept;
  };
  // The team summary is swapped whole on every delta (TD-176 slice 3), and a scrolled list in it —
  // the Doing feed — would snap back to the top each time (TD-205). Read each `data-keep-scroll`
  // box's position before the swap, by its name; one at the top is not kept, so it stays at the
  // top where the newest rows land.
  AO.scrolls = function (root) {
    const kept = {};
    if (!root) return kept;
    root.querySelectorAll("[data-keep-scroll]").forEach((el) => { if (el.scrollTop > 0) kept[el.dataset.keepScroll] = el.scrollTop; });
    return kept;
  };
  // Put `node` at child index `i` of `parent`, and leave it alone when it is there already. Every
  // delta re-orders the Org's sections and cards; appending each one detached it even when it had
  // not moved, and the node the page's scroll anchoring holds on to went with it (TD-224).
  AO.placeAt = function (parent, node, i) {
    const at = parent.children[i] || null;
    if (at !== node) parent.insertBefore(node, at);
  };
  AO.restoreScrolls = function (root, kept) {
    if (!root || !kept) return;
    root.querySelectorAll("[data-keep-scroll]").forEach((el) => {
      const top = kept[el.dataset.keepScroll];
      if (top) el.scrollTop = top;
    });
  };
  // §4.5a *Inbox row: orphaned question* (TD-216): a refused write is drawn on the row, which stays
  // — so the words are carried across the poll's swap, by the row's entry id, as a Deny reason is
  AO.rowErrs = function (root) {
    const kept = {};
    if (root) root.querySelectorAll(".rowerr:not([hidden])").forEach((el) => {
      const row = el.closest(".mailrow");
      if (row && row.dataset.msg) kept[row.dataset.msg] = el.textContent;
    });
    return kept;
  };
  AO.restoreRowErrs = function (root, kept) {
    // a press still in flight: its row stays out, or stays pending, whatever the swap drew (TD-340)
    if (root) root.querySelectorAll(".mailrow[data-msg]").forEach((r) => {
      const f = AO.inflight[r.dataset.msg];
      if (f && f.leaves) r.remove(); else if (f) AO.markPending(r, f.verb);
    });
    if (root) root.querySelectorAll(".mailrow[data-msg] .rowerr").forEach((el) => {
      const msg = el.closest(".mailrow").dataset.msg;
      const text = kept[msg] || AO.pressErrs[msg];  // a refused press's words, held by the page (TD-340)
      if (text) { el.textContent = text; el.hidden = false; }
    });
  };
  AO.restoreDenyWhys = function (root, kept) {
    if (!root) return;
    root.querySelectorAll("input.denywhy").forEach((i) => {
      const k = kept[i.dataset.id];
      if (!k) return;
      i.value = k.value;
      if (k.focused) i.focus();
    });
  };

  // Whether the poll may replace this section's rows now. It may not while the person is inside
  // them: an open Snooze menu would close under the press, and a swap would take the focus of
  // someone tabbing through a row's controls. Neither is worth a few seconds' freshness — the next
  // poll does it, and the count above never waits. Kept pure (element in, boolean out) so the rule
  // is one readable line rather than conditions spread through the swap.
  AO.maySwapSection = function (el, focused) {
    if (!el) return false;
    // a menu the person has opened; an open *details* fold is not one — it is put back after the swap
    if (el.querySelector("details[open]:not(.fold)")) return false;
    return !(focused && focused !== document.body && el.contains(focused));
  };

  // §4.9b: the team header's *answered for you* count runs from the last time the person **opened
  // the group** — here, the newest row on screen while the group is open and the tab is in view.
  function markAnsweredSeen() {
    const sec = $("#sec-answered");
    if (!sec || !sec.open || sec.classList.contains("hidden") || document.visibilityState === "hidden") return;
    let newest = store.get(ANSWERED_SEEN, "");
    $$("#rows-answered .mailrow").forEach((r) => { if ((r.dataset.at || "") > newest) newest = r.dataset.at; });
    if (newest) store.set(ANSWERED_SEEN, newest);
  }

  let inboxDownWait = null, inboxDownLong = false;  // the grace's retry pending; it has fired (TD-372)
  async function refreshInbox() {
    const got = await AO.refreshInboxCount(true);
    const down = $("#agentdown");
    if (down) {
      // the banner the page renders at load, turned on and off by the poll: a host agent that goes
      // away under an open page must not leave its rows looking current (design §4.5)
      // `.hidden` the class, never the attribute: `.warn` sets `display`, which beats the UA's
      // `[hidden]` rule — the trap `.badge[hidden]` is commented for in app.css, and the Org's own
      // banner avoids the same way (review of PR #271)
      // …after the grace (TD-372): a first failed poll asks again in `AO.DOWN_GRACE` and draws
      // nothing, so a promote's restart between two polls never shows it; a banner the page
      // rendered at load is the server's word and stands until a poll succeeds
      const isDown = !!(got && got.agent_down), shown = !down.classList.contains("hidden");
      if (!isDown) { clearTimeout(inboxDownWait); inboxDownWait = null; inboxDownLong = false; }
      else if (!shown && !inboxDownWait && !inboxDownLong) inboxDownWait = setTimeout(() => { inboxDownWait = null; inboxDownLong = true; refreshInbox(); }, AO.DOWN_GRACE);
      if (!isDown || shown || inboxDownLong) {
        down.classList.toggle("hidden", !isDown);
        if (isDown && got.why) $("#agentdownwhy").textContent = got.why;
      }
    }
    // …and nothing else changes while it is down: an empty `html` would blank every section and a
    // `needs` of 0 would claim nothing is waiting, which is precisely what is not known (§4.5)
    if (!got || got.agent_down || !got.html) return;
    // the board reader's note (TD-069 step 3): a board that could not be read is said, not blank
    const bn = $("#boardnote");
    if (bn) { bn.textContent = got.board_note || ""; bn.classList.toggle("hidden", !got.board_note); }
    IN_SECS.forEach((k) => {
      const el = $("#rows-" + k);
      // A row that is merely ringed (TD-124) — the focus on the row, not on a control inside it —
      // does not hold the swap back: the ring is put back on the same row, or on the one that took
      // its place when a key's press ended it.
      const on = document.activeElement, ring = on && on.matches && on.matches(".mailrow") && el && el.contains(on) ? on : null;
      if (el && AO.maySwapSection(el, ring ? null : on)) {
        const kept = AO.denyWhys(el), errs = AO.rowErrs(el), at = ring ? $$(".mailrow", el).indexOf(ring) : -1;
        el.innerHTML = got.html[k] || "";
        AO.restoreDenyWhys(el, kept);
        AO.restoreRowErrs(el, errs);
        AO.reopenFolds(el);
        if (landed) $$(".mailrow", el).forEach((r) => r.classList.toggle("landed", r.dataset.msg === landed));
        if (ring) {
          const rows = $$(".mailrow", el), back = rows.find((r) => r.dataset.msg === ring.dataset.msg) || rows[at] || rows[rows.length - 1];
          if (back) back.focus({ preventScroll: true });
        }
      }
    });
    // the board's horizon (TD-220): *Board, coming up*, the fold and the line, put back whole under
    // the same rule as a section — an open *not shown* fold is a `.fold`, reopened after the swap
    const hz = $("#boardhorizon");
    if (hz && typeof got.html.horizon === "string" && AO.maySwapSection(hz, document.activeElement)) {
      const errs = AO.rowErrs(hz);
      hz.innerHTML = got.html.horizon;
      AO.restoreRowErrs(hz, errs);
      AO.reopenFolds(hz);
    }
    // the ledger's entries that wait on you (TD-368, TD-565): put back whole when they changed, their
    // folds reopened as the person left them, a refused write's words kept, and a ringed row (TD-124)
    // holding nothing back — the ring goes back on the same row, or the one in its place, as a section's
    const lf = $("#ledgerforyou");
    const lon = document.activeElement, lring = lon && lon.matches && lon.matches(".mailrow") && lf && lf.contains(lon) ? lon : null;
    if (lf && AO.maySwapSection(lf, lring ? null : lon)) {
      const errs = AO.rowErrs(lf), at = lring ? $$(".mailrow", lf).indexOf(lring) : -1;
      if (AO.ledgerSwap(lf, got.html.ledger)) {
        AO.restoreRowErrs(lf, errs);
        AO.reopenFolds(lf);
        if (lring) {
          const rows = $$(".mailrow", lf), back = rows.find((r) => r.dataset.msg === lring.dataset.msg) || rows[at] || rows[rows.length - 1];
          if (back) back.focus({ preventScroll: true });
        }
      }
    }
    // *Later* (TD-565): drawn while it holds a row coming up, a *not shown* fold, a ledger row or a team
    // start row of its own (TD-781)
    const lt = $("#sec-later");
    if (lt) lt.classList.toggle("hidden", !AO.laterHas(lt) && !rail.sec.includes("later"));
    // *Waiting on them* is empty for most people most of the time, so it draws only when it has
    // something — like the snoozed box (§4.5a **Inbox section: Waiting on them**).
    const w = $("#sec-waiting");
    if (w) w.classList.toggle("hidden", !(got.sections && (got.sections.waiting || []).length) && !rail.sec.includes("waiting"));
    // *Answered for you* (§4.9b) the same way: most teams have no techlead, and an empty heading
    // there would be a section that is never anything
    const a = $("#sec-answered");
    if (a) a.classList.toggle("hidden", !(got.sections && (got.sections.answered || []).length) && !rail.sec.includes("answered"));
    // its **Dismiss all** is drawn only while the group holds a row — a rail pick draws the heading alone
    const da = $("#dismissanswered");
    if (da) da.hidden = !$$("#rows-answered .mailrow").length;
    // the rail's *Teams* lines come with the rows: a team appears or goes with its mail
    const rt = $("#railteams");
    if (rt && typeof got.html.rail_teams === "string" && !rt.contains(document.activeElement)) rt.innerHTML = got.html.rail_teams;
    // …and its *Repos* lines with the board's rows (TD-741)
    const rr = $("#railrepos");
    if (rr && typeof got.html.rail_repos === "string" && !rr.contains(document.activeElement)) rr.innerHTML = got.html.rail_repos;
    markAnsweredSeen();
    // §4.10: **FYI opens itself when its count is higher than this browser last saw it**, and is
    // otherwise as the person left it. That comparison is the browser's own — nothing on an entry
    // and nothing at the home changes, so reading still changes no row. A folded, uncounted FYI
    // is how five notes sat unseen for three days, which is the failure this closes.
    const fyi = $("#sec-fyi"), n = got.fyi_n || 0;
    if (fyi && got.fyi_n !== null && got.fyi_n !== undefined) {
      if (n > store.get("inboxfyiseen", 0)) { fyi.open = true; store.set("inboxfyi", true); }
      store.set("inboxfyiseen", n);
      // …and the entries that are why: an FYI entry newer than this browser last saw is marked
      // **new** — a mark and never a control, and the browser's own memory, as the fold is:
      // nothing on the entry and nothing at the home changes, so reading still changes no row.
      const seen = store.get("inboxfyiseenat", ""), rowsFyi = $$("#rows-fyi .mailrow");
      let newest = seen;
      rowsFyi.forEach((r) => {
        const at = r.dataset.at || "";
        r.classList.toggle("isnew", !!seen && !!at && at > seen);
        if (at > newest) newest = at;
      });
      if (newest) store.set("inboxfyiseenat", newest);
    }
    showLocalTimes();
    const sn = got.snoozed_n || 0;
    $("#snoozedbox").hidden = !sn;
    $("#snoozedlabel").textContent = `(${sn})`;
    inboxFilter();
  }
  AO.inboxPoll = refreshInbox;  // the poll as itself, for `tests/test_ui_down_grace.py`'s fake clock (TD-383)

  // design §4.5 screen 6 *The rail* and *Find* (TD-129, built by TD-135). Within a group the picks
  // are OR'd, across groups AND'd, a group with nothing picked means all of it, and the find is a
  // fourth group: every word typed must match, in any order, as a substring of the row's
  // `data-find`. `railCounts` is `app.py`'s `rail_counts` again, over the rows in the DOM — every
  // count is a count of rows on the page now — and a test holds the two to one answer.
  const RAIL_SECS = ["needs", "steering", "waiting", "answered", "later", "fyi"];
  const RAIL_KINDS = ["questions", "steering", "states", "board", "ledger", "notes", "trail"];
  const FIND_EDGE = ",.;:!?()[]{}\"'“”‘’<>";
  let rail = { team: [], repo: [], sec: [], kind: [], find: "" };
  const findOpened = new Set();
  // the Inbox's `?row=<key>` (§4.10 *Told on Telegram*, TD-319 slice 3): a Telegram message's link names
  // its row by the home's key — `<session>|<kind>` for a state row, `work:<team>` for a team with work —
  // and the page's row for it is `data-msg` `<session>:<kind>`, `work:<team>` as it is. Pure, for the tests.
  AO.rowOfKey = function (key) {
    const k = String(key || "").trim();
    if (!k || k.startsWith("work:")) return k;
    const i = k.indexOf("|");
    return i < 0 ? k : `${k.slice(0, i)}:${k.slice(i + 1)}`;
  };
  AO.railPicks = function (search) {
    const q = new URLSearchParams(search || "");
    const lst = (k) => (q.get(k) || "").split(",").map((x) => x.trim()).filter(Boolean);
    return {
      team: lst("team"),
      repo: lst("repo"),
      sec: lst("sec").filter((x) => RAIL_SECS.includes(x)),
      kind: lst("kind").filter((x) => RAIL_KINDS.includes(x)),
      find: (q.get("find") || "").trim(),
    };
  };
  AO.railQuery = function (p) {
    const parts = [];
    ["team", "repo", "sec", "kind"].forEach((k) => { if (p[k].length) parts.push(`${k}=${p[k].map(encodeURIComponent).join(",")}`); });
    if (p.find) parts.push(`find=${encodeURIComponent(p.find)}`);
    return parts.length ? "?" + parts.join("&") : "";
  };
  AO.findWords = function (find) {
    const trim = (w) => { let a = 0, b = w.length; while (a < b && FIND_EDGE.includes(w[a])) a++; while (b > a && FIND_EDGE.includes(w[b - 1])) b--; return w.slice(a, b); };
    return String(find || "").toLowerCase().split(/\s+/).map(trim).filter(Boolean);
  };
  // the board's rows coming up and the fold's (TD-220) sit under *Later* (TD-565), counted and picked with it
  const RAIL_UNDER = { coming: "later", unshown: "later" };
  // the values a row has in a group: a board row's teams are its repo's, and only a board row has a repo (TD-741)
  const railVals = (r, g) => (g === "team" ? r.teams : g === "repo" ? (r.repo ? [r.repo] : []) : g === "sec" ? [RAIL_UNDER[r.section] || r.section] : [r.kind]);
  function railPasses(r, picks, words, skip) {
    for (const g of ["team", "repo", "sec", "kind"]) {
      if (g !== skip && picks[g].length && !railVals(r, g).some((v) => picks[g].includes(v))) return false;
    }
    return words.every((w) => r.find.includes(w));
  }
  AO.railCounts = function (rows, picks) {
    const words = AO.findWords(picks.find);
    const teams = [...new Set(rows.flatMap((r) => r.teams).filter((t) => t !== "none"))].sort();
    if (rows.some((r) => r.teams.includes("none"))) teams.push("none");
    (picks.team || []).forEach((t) => { if (!teams.includes(t)) teams.push(t); });
    const labels = {};
    rows.forEach((r) => { if (r.repo && !(r.repo in labels)) labels[r.repo] = r.repo_label || r.repo; });
    const repos = Object.keys(labels).sort();
    (picks.repo || []).forEach((x) => { if (!repos.includes(x)) repos.push(x); });
    const line = (group, value, among) => {
      const mine = among.filter((r) => railVals(r, group).includes(value));
      const shown = picks[group].length && !picks[group].includes(value) ? 0 : mine.filter((r) => railPasses(r, picks, words, group)).length;
      return { shown, all: mine.length };
    };
    const needs = rows.filter((r) => r.section === "needs");
    const out = { filtered: !!(picks.team.length || picks.repo.length || picks.sec.length || picks.kind.length || words.length), sections: {}, teams: {}, team_order: teams, repos: {}, repo_order: repos, repo_labels: {}, kinds: {}, heads: {} };
    const inSec = (r, s) => railVals(r, "sec")[0] === s;
    RAIL_SECS.forEach((s) => {
      out.sections[s] = line("sec", s, rows);
      out.heads[s] = { shown: rows.filter((r) => inSec(r, s) && railPasses(r, picks, words)).length, all: rows.filter((r) => inSec(r, s)).length };
    });
    teams.forEach((t) => { out.teams[t] = line("team", t, needs); });
    repos.forEach((x) => { out.repos[x] = line("repo", x, needs); out.repo_labels[x] = labels[x] || x; });
    RAIL_KINDS.forEach((k) => { out.kinds[k] = line("kind", k, rows); });
    return out;
  };
  // a text cut at the find's words (TD-280): `[[piece, matched], …]`, case-insensitive, the longer
  // word first where two overlap; pure, so the probe tests it without a page
  AO.findSplit = function (text, words) {
    const t = String(text || ""), out = [];
    if (!words.length) return [[t, false]];
    const re = new RegExp([...words].sort((a, b) => b.length - a.length).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "gi");
    let at = 0;
    for (let m; (m = re.exec(t)); ) {
      if (m.index > at) out.push([t.slice(at, m.index), false]);
      out.push([m[0], true]);
      at = m.index + m[0].length;
    }
    if (at < t.length || !out.length) out.push([t.slice(at), false]);
    return out;
  };
  // the find's words marked in the rows it shows (§4.5a *Inbox page: find*, TD-280): every match in a
  // row's text — the body, its *details* and its replies — wrapped in `<mark class="findmark">`, the
  // marks taken off first, so a find that changes or empties leaves none; text nodes only, so no
  // markup is ever built from what a row says
  AO.markFind = function (root, words) {
    if (!root) return;
    // a text already marked for these words is left alone — the poll re-filters every 20 s, and
    // re-marking would collapse a selection the person is making; a swapped row is new and unmarked
    const key = words.join(" ");
    const unmark = (el) => {
      $$("mark.findmark", el).forEach((m) => { const p = m.parentNode; m.replaceWith(document.createTextNode(m.textContent)); p.normalize(); });
      delete el.dataset.findmarked;
    };
    $$("[data-findmarked]", root).forEach((el) => { if (el.dataset.findmarked !== key) unmark(el); });
    if (!words.length) return;
    $$(".mailrow:not([hidden]) .subj, .mailrow:not([hidden]) .body, .mailrow:not([hidden]) .boardreply", root).forEach((body) => {
      if (body.dataset.findmarked === key) return;
      body.dataset.findmarked = key;
      const walk = document.createTreeWalker(body, NodeFilter.SHOW_TEXT), nodes = [];
      while (walk.nextNode()) nodes.push(walk.currentNode);
      nodes.forEach((n) => {
        const parts = AO.findSplit(n.nodeValue, words);
        if (!parts.some(([, hit]) => hit)) return;
        const frag = document.createDocumentFragment();
        parts.forEach(([piece, hit]) => {
          if (!hit) { frag.append(piece); return; }
          const mk = document.createElement("mark"); mk.className = "findmark"; mk.textContent = piece; frag.append(mk);
        });
        n.replaceWith(frag);
      });
    });
  };
  // design §4.5 screen 6 *The ledger's entries that wait on you* (TD-368, TD-565): full rows in
  // *Later*. The rules are `AO.` so that `tests/test_ui_inbox_ledger.py` runs them under node (TD-374).
  // *Later* holds something: a row coming up, a *not shown* fold, or a ledger row
  AO.laterHas = (sec) => !!sec.querySelector("#rows-coming .mailrow, details.boardfold, #ledgerforyou .mailrow, #rows-later .mailrow");
  // the poll's swap: put back whole when the server's markup changed — compared with what it sent
  // last, not with the DOM, whose `open` and `hidden` differ. True when it swapped.
  AO.ledgerSwap = function (lf, html) {
    if (!lf || typeof html !== "string" || lf.dataset.src === html) return false;
    lf.innerHTML = lf.dataset.src = html;
    return true;
  };
  // the rows are filtered as every row is; a repo's name goes with its last row shown
  AO.ledgerFilter = function (root) {
    $$(".inboxpage .ledgergroup", root).forEach((g) => { g.hidden = !$$(".ledgerrow", g).some((el) => !el.hidden); });
  };
  // a board row carries its repo and its repo's teams (TD-741); every other row its one team
  const railRow = (el) => {
    const board = el.dataset.teams !== undefined;
    const teams = board ? el.dataset.teams.split(" ").filter(Boolean) : [el.dataset.team || "none"];
    return { section: el.dataset.section || "", teams: teams.length ? teams : ["none"], repo: board ? el.dataset.repo || "" : "", repo_label: board ? el.dataset.repoLabel || el.dataset.repo || "" : "", kind: el.dataset.rkind || "", find: el.dataset.find || "" };
  };

  function inboxFilter() {
    const box = $("#ifilter"); if (!box) return;
    const words = AO.findWords(rail.find);
    const num = (c, filtered) => (filtered ? `${c.shown} of ${c.all}` : `${c.all}`);
    // every row on the page, the snoozed list included (its box is not a section: a section pick
    // hides it whole, below), shown or hidden by the same rule
    $$(".inboxpage .mailrow").forEach((el) => {
      const r = railRow(el);
      el.hidden = !railPasses(r, rail, words, r.section === "snoozed" ? "sec" : "");
    });
    // …and the board's rows coming up, the fold's once it is open (TD-220) and the ledger's (TD-565):
    // counted under *Later*, by their kinds and in no number that means *due now*
    const rows = $$([...RAIL_SECS.map((k) => `#rows-${k} .mailrow`), "#rows-coming .mailrow", "details.boardfold[open] #rows-unshown .mailrow", "#ledgerforyou .mailrow"].join(", ")).map(railRow);
    const c = AO.railCounts(rows, rail);
    // a team line for a picked team the poll no longer carries, so the pick can be undone
    const rt = $("#railteams");
    if (rt) c.team_order.forEach((t) => {
      if (!$$(".railline", rt).some((b) => b.dataset.value === t)) {
        rt.insertAdjacentHTML("beforeend", `<button type="button" class="railline" data-group="team" data-value="${esc(t)}" aria-pressed="false"><span class="raillabel">${esc(t === "none" ? "no team" : t)}</span><span class="railn"></span></button>`);
      }
    });
    // …and a repo line for a picked repo the poll no longer carries (TD-741)
    const rr = $("#railrepos");
    if (rr) c.repo_order.forEach((x) => {
      if (!$$(".railline", rr).some((b) => b.dataset.value === x)) {
        rr.insertAdjacentHTML("beforeend", `<button type="button" class="railline" data-group="repo" data-value="${esc(x)}" aria-pressed="false" title="${esc(c.repo_labels[x] || x)}"><span class="raillabel">${esc(c.repo_labels[x] || x)}</span><span class="railn"></span></button>`);
      }
    });
    $$(".rail .railline").forEach((b) => {
      const g = b.dataset.group, v = b.dataset.value;
      const cnt = g === "sec" ? c.sections[v] : g === "kind" ? c.kinds[v] : g === "repo" ? c.repos[v] || { shown: 0, all: 0 } : c.teams[v] || { shown: 0, all: 0 };
      b.setAttribute("aria-pressed", rail[g].includes(v) ? "true" : "false");
      $(".railn", b).textContent = num(cnt, c.filtered);
      b.classList.toggle("dim", c.filtered && !cnt.shown);
    });
    $("#railclear").disabled = !c.filtered;  // held in place, so the toggles never move under the pointer (TD-423)
    // a repo's name in *Later* goes with its last ledger row shown (TD-565)
    AO.ledgerFilter(document);
    // the narrow chip row (TD-137): the number of picks on **Filters ▾**, then the team chips from
    // the same counts, picked first so a pick never scrolls out of sight
    const pn = rail.team.length + rail.repo.length + rail.sec.length + rail.kind.length + (words.length ? 1 : 0);
    const pe = $("#picksn"); if (pe) pe.textContent = pn ? `${pn}` : "";
    const ct = $("#chipteams");
    if (ct) {
      const order = [...c.team_order.filter((t) => rail.team.includes(t)), ...c.team_order.filter((t) => !rail.team.includes(t))];
      const html = order.map((t) => {
        const cnt = c.teams[t] || { shown: 0, all: 0 }, on = rail.team.includes(t);
        return `<button type="button" class="btn sm chip railline${c.filtered && !cnt.shown ? " dim" : ""}" data-group="team" data-value="${esc(t)}" aria-pressed="${on}"><span class="raillabel">${esc(t === "none" ? "no team" : t)}</span> <span class="railn">${num(cnt, c.filtered)}</span></button>`;
      }).join("");
      if (ct.innerHTML !== html) {
        const had = document.activeElement && ct.contains(document.activeElement) ? document.activeElement.dataset.value : null;
        ct.innerHTML = html;
        if (had !== null) { const back = $$(".railline", ct).find((b) => b.dataset.value === had); if (back) back.focus({ preventScroll: true }); }
      }
    }
    // a section not picked is not drawn; one picked and emptied draws its heading and its empty line
    RAIL_SECS.forEach((k) => {
      const sec = $("#sec-" + k); if (!sec) return;
      sec.classList.toggle("railout", rail.sec.length > 0 && !rail.sec.includes(k));
      const h = c.heads[k];
      $("#n-" + k).textContent = c.filtered ? num(h, true) : h.all ? `${h.all}` : "";
      // *Later* says it is empty only when a pick emptied it: unfiltered, a fold and a line are not nothing
      const empty = $(".note.empty", sec); if (empty) empty.hidden = h.shown > 0 || (k === "later" && !c.filtered);
    });
    const sz = $("#snoozedbox"); if (sz) sz.classList.toggle("railout", rail.sec.length > 0);
    // the find's own count, and the folds it opens (§4.5 screen 6 *Find*): a match inside FYI or
    // the snoozed list unfolds it while the box holds words, and folds it back when the box empties
    // — unless the person had it open, whose fold memory is theirs
    const all = rows.length, shown = rows.filter((r) => railPasses(r, rail, words)).length;
    $("#findn").textContent = words.length ? `${shown} of ${all}` : "";
    AO.markFind($(".inboxpage"), words);
    ["sec-fyi", "snoozedbox"].forEach((id) => {
      const d = document.getElementById(id); if (!d) return;
      const hit = words.length && $$(".mailrow", d).some((el) => !el.hidden);
      if (hit && !d.open) { findOpened.add(id); d.open = true; }
      else if (!words.length && findOpened.has(id)) { d.open = false; if (id !== "sec-fyi") findOpened.delete(id); }  // FYI's own toggle clears it
    });
  }

  const ENTRY_ORDER = "inboxorder";
  const sess = {
    get: (k) => { try { return JSON.parse(sessionStorage.getItem(k) || "null"); } catch (e) { return null; } },
    set: (k, v) => { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode: j / k then do nothing */ } },
  };
  AO.entryUrl = (id, back) => `/inbox/${encodeURIComponent(id)}${back ? `?back=${encodeURIComponent(back)}` : ""}`;
  AO.openEntry = function (id) {
    // the list the row is drawn in: the Inbox's as filtered, or the Queue's cards (TD-771), Back to it
    const queue = !!$(".queuepage");
    const order = $$(queue ? ".queuepage .qcard:not(.qoff) .mailrow[data-page]" : ".inboxpage .mailrow[data-page]")
      .filter((r) => !r.hidden).map((r) => r.dataset.msg);
    const back = queue ? `/queue${location.search}` : location.search;
    sess.set(ENTRY_ORDER, { back, ids: order });
    location.href = AO.entryUrl(id, back);
  };
  // `j` / `k` on the page: the next and previous entry of the list as it was filtered
  AO.entryStep = function (step) {
    const page = $(".msgpage"), o = sess.get(ENTRY_ORDER);
    if (!page || !o || !Array.isArray(o.ids)) return;
    const i = o.ids.indexOf(page.dataset.msg), next = i < 0 ? null : o.ids[i + step];
    if (next) location.href = AO.entryUrl(next, o.back || "");
  };
  AO.inboxEntry = function () {
    const page = $(".msgpage"); if (!page) return;
    const o = sess.get(ENTRY_ORDER), i = o && Array.isArray(o.ids) ? o.ids.indexOf(page.dataset.msg) : -1;
    if (i >= 0) $("#msgpos").textContent = `${i + 1} of ${o.ids.length} · j / k`;
    // the row's team badge: back to the list with that team picked
    document.addEventListener("click", (e) => {
      const b = e.target.closest(".msgentry .badge.team"); if (!b) return;
      e.preventDefault();
      location.href = `/inbox?team=${encodeURIComponent(b.dataset.team || "none")}`;
    });
    // an answer here is the answer (the row's own controls and RPCs); when it takes the entry out
    // of the section it was in, the page returns to the list, and otherwise shows what it is now.
    // Only after a press of the entry's own: the top bar's 20 s poll calls this hook too, and a page
    // being read is never reloaded under the reader — nor while the composer is open over it.
    const sec = $(".msgentry .mailrow") && $(".msgentry .mailrow").dataset.section;
    let answered = false;
    document.addEventListener("click", (e) => { if (e.target.closest(".msgentry [data-act]")) answered = true; }, true);
    AO.refreshInboxPage = async () => {
      const got = await AO.refreshInboxCount(true);
      if (!answered || document.querySelector("dialog[open]")) return;
      answered = false;
      const still = got && got.sections && (got.sections[sec] || []).includes(page.dataset.msg);
      if (got && !got.agent_down && !still) location.href = page.dataset.back; else location.reload();
    };
  };

  // design §4.5a *team card: Members…* and the *Members dialog* (§4.9, TD-163, built by TD-172). The
  // listing is the definition as `org.yml` writes it, with the sessions holding each entry; Add and
  // Remove edit the file through the UI process and, on a live team, start or wind down the members;
  // **− / +** set a line's size, a setting, on every team a repo's included (§4.9 *A team's size*,
  // TD-1165). Every name here is text (`esc`); a refusal is said in the dialog, which stays open.
  AO.membersConfirm = function (e, team) {
    const ss = e.sessions || [];
    const up = ss.filter((x) => x.id && !["exited", "closed", "not live"].includes(x.state)).map((x) => x.name);
    const edit = `removes the ${e.name || e.role} line`;
    const shared = new Set(e.shared || []), down = up.filter((n) => !shared.has(n));
    const runs = e.twice ? `; another entry still names ${ss.filter((x) => shared.has(x.name)).map((x) => x.name).join(", ")}, so it runs on` : "";  // TD-268
    return `Remove from ${team}? It edits org.yml (${edit})` + (down.length ? ` and winds down ${down.join(", ")} — Wrap up's prompt, never a kill; each card stays until Forget` : "") + runs + ".";
  };
  // **−**'s confirm names the session it winds down (§4.5a *Members dialog* **− / +**); "" where it
  // winds none down — a stopped team, or a line whose last name no kept member holds — and asks nothing
  AO.membersSizeConfirm = function (e, team) {
    if (!e.down) return "";
    return `${team}: ${e.name || e.role} ${e.size} → ${e.size - 1}? It winds down ${e.down} — Wrap up's prompt, never a kill; its card stays until Forget.`;
  };
  // a member line's row: role · name · lane, then − size + (*2 (file says 1)*), *· from the next Start* on a
  // stopped team whose size is above its count, the sessions holding it, and Remove (disabled on a repo's team)
  AO.membersRow = function (e, v) {
    const who = (h) => h ? `${esc(h.name)} · ${esc(h.state)}` : "";
    const held = (e.sessions || []).map(who).join(", ");
    const off = v.editable ? "" : ` disabled title="${esc(v.note || "")}"`;
    const rm = ` <span class="grow"></span><button class="btn sm ghost" type="button" data-mremove="${e.index}"${off}>Remove</button>`;
    const twin = e.twice ? ` disabled title="another entry shares a name with this line: rename one of them in the definition"` : "";
    const size = `<button class="btn sm ghost" type="button" data-msize="${e.index}" data-step="-1"${twin || (e.size > 0 ? "" : " disabled")} title="one session fewer on this line — a setting, the definition untouched" aria-label="one fewer ${esc(e.name || e.role)}">−</button>`
      + ` <span class="msize">${esc(e.words || String(e.size))}</span> `
      + `<button class="btn sm ghost" type="button" data-msize="${e.index}" data-step="1"${twin} title="one session more on this line — a setting, the definition untouched" aria-label="one more ${esc(e.name || e.role)}">+</button>`
      + (e.next_start ? ` <span class="meta">· from the next Start</span>` : "");
    return `<div class="row gap wrap"><span>${esc(e.role)} · ${esc(e.name || e.role)} · ${esc((e.lane || []).join(", ") || "—")} ·</span>${size}<span class="meta">${held}</span>${rm}</div>`;
  };
  async function openMembers(team) {
    const dlg = $("#membersdlg"); if (!dlg) return;
    const err = $("#memberserr");
    const say = (m) => { err.textContent = m || ""; err.classList.toggle("hidden", !m); };
    let v;
    async function load() {
      const r = await fetch(`/api/teams/${encodeURIComponent(team)}/members`);
      v = await r.json();
      if (!r.ok) { say(v.detail || "the definition could not be read"); return; }
      $("#membershead").textContent = `Members of ${team}`;
      $("#membersnote").textContent = v.live ? "live: + starts the line's next member under the manager and − winds one down; Add member and Remove edit the definition" : "stopped: an edit is the definition or the size only — the next Start brings it";
      const who = (h) => h ? `${esc(h.name)} · ${esc(h.state)}` : "";
      const rows = [];
      if (v.manager) rows.push(`<div class="row gap"><span class="meta">manager</span> ${who(v.manager)}</div>`);
      if (v.techlead) rows.push(`<div class="row gap"><span class="meta">techlead seat</span> ${who(v.techlead)}</div>`);
      v.members.forEach((e) => rows.push(AO.membersRow(e, v)));
      // a definition that already names one session twice says so (TD-268): Remove on either line keeps the session
      if ((v.twice || []).length) rows.push(`<div class="row gap"><span class="meta">named twice: ${v.twice.map(esc).join(", ")} — Remove one line; the session runs on</span></div>`);
      $("#memberslist").innerHTML = rows.join("");
      // a repo's team: Add member drawn disabled, the reason and **Open file** beside it (§4.5a, TD-1165)
      ["#maddrole", "#maddname", "#maddlane", "#maddgo"].forEach((q) => { $(q).disabled = !v.editable; });
      const why = $("#maddwhy"); why.textContent = v.editable ? "" : v.note || ""; why.classList.toggle("hidden", !!v.editable);
      const of = v.open_file;
      $("#maddopen").innerHTML = of ? `<a class="editor btn sm ghost" data-file-link href="${esc(of.url)}" data-label="${esc(of.label)}"${of.folder ? ` data-folder="${esc(of.folder)}" data-wait="${esc(String(of.wait))}"` : ""} title="open ${esc(v.source || "")} in ${esc(of.label)}">Open file</a>` : "";
      const sel = $("#maddrole");
      sel.innerHTML = (v.roles || []).filter((x) => x !== "plain").map((x) => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
      if ([...sel.options].some((o) => o.value === "grinder")) sel.value = "grinder";
      // the next free name of the team's pattern, never an existing member's (TD-268)
      const fill = () => { $("#maddname").value = (v.next || {})[sel.value] || sel.value; };
      sel.onchange = fill; fill();
    }
    say(""); await load();
    $("#memberslist").onclick = async (ev) => {
      const z = ev.target.closest("[data-msize]");
      if (z) {
        const e = v.members.find((m) => String(m.index) === z.dataset.msize); if (!e) return;
        const step = Number(z.dataset.step), ask = step < 0 ? AO.membersSizeConfirm(e, team) : "";
        if (ask && !confirm(ask)) return;
        const r = await fetch(`/api/teams/${encodeURIComponent(team)}/members`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "size", line: e.name || e.role, step }) });
        const got = await r.json();
        if (!r.ok) return say(got.detail || "refused");
        say(""); AO.toast(got.text, true); return load();
      }
      const b = ev.target.closest("[data-mremove]"); if (!b || b.disabled) return;
      const e = v.members.find((m) => String(m.index) === b.dataset.mremove); if (!e) return;
      if (!confirm(AO.membersConfirm(e, team))) return;
      const r = await fetch(`/api/teams/${encodeURIComponent(team)}/members`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "remove", index: e.index, role: e.role }) });
      const got = await r.json();
      if (!r.ok) return say(got.detail || "refused");
      say(""); AO.toast(got.text, true); await load();
    };
    $("#maddgo").onclick = async () => {
      const body = { action: "add", role: $("#maddrole").value, name: $("#maddname").value, lane: $("#maddlane").value };
      const r = await fetch(`/api/teams/${encodeURIComponent(team)}/members`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const got = await r.json();
      if (!r.ok) return say(got.detail || "refused");
      say(""); AO.toast(got.text, true); await load();
    };
    if (!dlg.open) dlg.showModal();
  }
  document.addEventListener?.("click", (e) => {
    const b = e.target.closest && e.target.closest("[data-members]"); if (!b) return;
    e.preventDefault(); openMembers(b.dataset.members);
  });

  // design §4.5a **Add entry…** and the *Add entry form* (§4.9 *Add an entry to the ledger*, TD-219
  // slice 3): one form from the Repo page and the team card's Repo facet, the repo fixed by the press.
  // **Hand to the techlead** (slice 4) sends the words to `entry_add` and toasts the message's id, a
  // link to its page. **Open a session** starts an interactive session in a new worktree and goes to its Focus with the
  // composer holding `entry.md`'s lines and the words — kept here as that session's draft until sent
  // (`AO.draftKey`); nothing is typed into the pane. The page writes no file.
  AO.draftKey = (sid) => `ao.draft.${sid}`;
  let entryAttach = null;
  function openEntry(repo) {
    const dlg = $("#entrydlg"); if (!dlg) return;
    if (!entryAttach && $("#entryattach")) {
      const button = $("#entryattach");
      entryAttach = AO.wireEntryAttach(
        { dlg, button, input: $("#entryattachfile"), cancel: $("#entryattachcancel"), text: $("#entrywhat"), note: $("#entryattachnote") },
        (held) => AO.draftUpload(held, Number(button.dataset.piece)),
      );
    }
    if (entryAttach) entryAttach.open();
    const draft = () => (entryAttach ? entryAttach.draft() : "");
    const err = $("#entryerr");
    const say = (m) => { err.textContent = m || ""; err.hidden = !m; };
    const type = () => (dlg.querySelector("input[name=entrytype]:checked") || {}).value || "debt";
    const priority = () => (dlg.querySelector("input[name=entrypriority]:checked") || {}).value || "medium";
    let asked = 0;  // a later Type press or keystroke wins over an earlier answer that arrives after it
    // §4.5a *Add entry form: Name* (TD-677): untouched, the box follows the plan's default; typed in, it is
    // the person's, sent with every read; emptied, the default is its placeholder and the press takes it
    const nameBox = $("#entryname");
    let named = false;
    const typed = () => (named && nameBox.value.trim() ? nameBox.value : "");
    // the **Team** pick (TD-740): drawn where two or more teams service the repo; blank is the first with a seat
    const teamSel = $("#entryteam"), picked = () => (teamSel ? teamSel.value : "");
    if (teamSel) { teamSel.innerHTML = ""; teamSel.dataset.teams = ""; teamSel.onchange = plan; }
    let handWhy = "…";  // **Hand to the techlead**'s reason to be disabled, from the plan (TD-219 slice 4)
    let busy = false;  // a hand in flight: nothing re-enables the button under it, so one press hands once
    const hand = $("#entryhand");
    // disabled with its reason where no team or seat takes it, and while **What** is empty (§4.5a)
    const handState = () => {
      const empty = !$("#entrywhat").value.trim();
      hand.disabled = busy || !!handWhy || empty;
      hand.title = handWhy || (empty ? "write what the entry is first" : "");
    };
    $("#entrywhat").oninput = handState;
    // no read of the plan blanks a line (TD-1190): each is written from the answer, and only where its text changed
    const put = (sel, text) => { const el = $(sel); if (el && el.textContent !== text) el.textContent = text; };
    async function plan() {
      const mine = ++asked;
      let r, v;
      try {
        const q = (typed() ? `&name=${encodeURIComponent(typed())}` : "") + (picked() ? `&team=${encodeURIComponent(picked())}` : "");
        r = await fetch(`/api/entry/plan?repo=${encodeURIComponent(repo)}&type=${encodeURIComponent(type())}${q}`);
        v = await r.json();
      } catch (e) { if (mine === asked) { say(`the page could not ask: ${e.message}`); $("#entrygo").disabled = true; } return; }
      if (mine !== asked) return;
      if (!r.ok) { say(v.detail || "the repo could not be read"); $("#entrygo").disabled = true; return; }
      say(""); $("#entrygo").disabled = !!v.name_why;
      nameBox.placeholder = v.default || "";
      if (!named) nameBox.value = v.default || "";
      put("#entrywhere", `${v.repo} · ${v.ledger}`);
      const ts = (v.teams || []).map((t) => t.team), set = [...ts].sort().join(" ");
      if (teamSel && set !== (teamSel.dataset.teams || "")) {
        // the options once per set of teams, in the plan's order — the blank first, *first with a seat* — read
        // with no pick, so the blank names the first; a pick stays picked
        const was = picked(), first = v.picked ? {} : (v.teams || []).find((t) => t.seat) || {};
        teamSel.innerHTML = [`<option value="">${esc(first.team ? `first with a seat (${first.team})` : "first with a seat")}</option>`, ...ts.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`)].join("");
        teamSel.dataset.teams = set;
        teamSel.value = ts.includes(was) ? was : "";
      }
      if ($("#entryteamrow")) $("#entryteamrow").hidden = ts.length < 2;
      // a name that is not free: its reason stands in place of the line, and the button is disabled
      put("#entryline", v.name_why || v.line || "");  // the server's whole sentence, the page wrapping nothing
      $("#entryline").classList.toggle("bad", !!v.name_why); nameBox.classList.toggle("bad", !!v.name_why);  // as the *taken* shot draws it
      const h = v.hand || { why: "the host agent did not say who takes it" };
      handWhy = h.why || "";
      put("#entryseat", h.name || h.to || "");
      $("#entryhandwhat").hidden = !!handWhy;
      put("#entrywhen", h.why || h.line || "");  // the reason in place of both lines, else when it is read
      if (entryAttach) entryAttach.refuse(v.attach || "");
      handState();
    }
    hand.onclick = async () => {
      if (busy) return;
      busy = true; handState();
      let r, got;
      try {
        r = await fetch("/api/entry/hand", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ repo, type: type(), priority: priority(), words: $("#entrywhat").value, draft: draft(), team: picked() }) });
        got = await r.json();
      } catch (e) { busy = false; handState(); return say(`the page could not ask: ${e.message}`); }
      if (!r.ok) { busy = false; handState(); return say(got.detail || "refused"); }
      busy = false;
      dlg.close();
      AO.toast(got.text, true, got.href);
    };
    $("#entrywhere").textContent = repo;
    $("#entrywhat").value = ""; $("#entryseat").textContent = ""; $("#entrywhen").textContent = ""; $("#entryline").textContent = "";
    named = false; nameBox.value = ""; nameBox.placeholder = ""; nameBox.classList.remove("bad"); $("#entryline").classList.remove("bad");
    // checked as typed, debounced as New session's name field is (§4.5a *New session: name field → holder*)
    nameBox.oninput = () => { named = true; clearTimeout(nameBox._t); nameBox._t = setTimeout(plan, 250); };
    dlg.querySelector("input[name=entrytype][value=debt]").checked = true;
    dlg.querySelector("input[name=entrypriority][value=medium]").checked = true;  // each opening starts at Medium
    dlg.querySelectorAll("input[name=entrytype]").forEach((x) => { x.onchange = plan; });
    $("#entrygo").onclick = async () => {
      $("#entrygo").disabled = true;
      let r, got;
      try {
        r = await fetch("/api/entry/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ repo, type: type(), priority: priority(), words: $("#entrywhat").value, draft: draft(), name: typed() }) });
        got = await r.json();
      } catch (e) { $("#entrygo").disabled = false; return say(`the page could not ask: ${e.message}`); }
      if (!r.ok) { $("#entrygo").disabled = false; return say(got.detail || "refused"); }
      try { localStorage.setItem(AO.draftKey(got.id), got.text); } catch (_) { /* no storage: Focus opens with an empty composer */ }
      // …and Focus opens it, filled and focused, once: a draft the person folded stays on the bar (TD-500)
      try { sessionStorage.setItem("ao.draft.open", got.id); } catch (_) { /* no storage: it waits on the bar */ }
      location.href = `/focus/${encodeURIComponent(got.id)}`;
    };
    say(""); plan();
    if (!dlg.open) dlg.showModal();
    $("#entrywhat").focus();
  }
  document.addEventListener?.("click", (e) => {
    const b = e.target.closest && e.target.closest("[data-addentry]"); if (!b) return;
    e.preventDefault(); openEntry(b.dataset.addentry);
  });

  AO.org = function () {
    // the Repo page's team link lands here filtered to that team (§4.5a *Repo page: links*)
    const wantTeam = new URLSearchParams(location.search).get("team");
    if (wantTeam) $("#filter").value = "team:" + wantTeam;
    $("#filter").addEventListener("input", layout);
    $("#retry").addEventListener("click", () => location.reload());
    const box = $("#groups");
    // The card's team badge filters the page to that team; pressing it again takes the word out.
    box.addEventListener("click", (e) => {
      const b = e.target.closest(".badge.team"); if (!b) return;
      e.preventDefault();
      const f = $("#filter");
      f.value = AO.orgToggleWord(f.value, "team:" + b.dataset.team);
      layout();
    });
    // Start, Wind down and Stop now are all on the team's card, and so is its fold.
    wireGroups(box);
    // the rollup (TD-1204): a row's press, its two menus, an Agents pill typing `state:<word>` into the filter
    // box (pressed again, it takes the word out); a press outside an open menu closes it
    const rollupBox = $("#rollup");
    if (rollupBox) {
      rollupBox.addEventListener("click", rollupPress);
      rollupBox.addEventListener("keydown", rollupKeys);
      // …never for a press whose target a held swap has just replaced: that press opened the menu now open
      document.addEventListener("click", (e) => {
        if (rollupMenu && e.target.isConnected && !rollupMenu.menu.parentElement.contains(e.target)) rollupClose(false);
      });
    }
    layout();
    // a load with a row's hash lands there once the groups are drawn; a hash naming nothing drawn is dropped
    const landKey = AO.rollupKey(location.hash);
    if (landKey && !rollupLand(landKey)) history.replaceState(null, "", location.pathname + location.search);
    if (popChan()) popChan().postMessage({ who: true });  // the popped windows answer with their ids
    connectEvents((ev) => groupsEvent(ev, ""));
  };


  // ---- the Repo page (design §4.5 screen 11, TD-176 slice 5, TD-740) ----
  // The page's top is the repo's items of the Org — its line, its teams' whole cards, its no-team
  // strip — kept by the Org's own deltas (`groupsEvent` with the repo); its lists are `repo_part.html`,
  // re-read on a poll and on every `repos` or `doing` event. The facets' selectors and the folds are
  // the team card's, the doing chips are remembered per browser, and a typed Deny reason survives a re-read.
  // design §4.5 screen 9 **Transcript** (TD-166): the page is a snapshot drawn by the server; the one
  // script is *earlier turns*, which fetches the twenty before the first shown and puts them in the
  // button's place — above the turns already there. Folds are plain <details>, remembered nowhere.
  AO.transcript = function () {
    const box = $("#transcript"); if (!box) return;
    const id = box.dataset.id;
    showLocalTimes();
    // a path in a turn (TD-691): served only where the page draws its editor button
    let pe = null;
    try { pe = box.dataset.paths ? JSON.parse(box.dataset.paths) : null; } catch (e) { pe = null; }
    if (pe && pe.file) {
      const asker = AO.pathsAsker((runs) => fetch(`/api/sessions/${encodeURIComponent(id)}/paths`, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ runs }),
      }).then((r) => (r.ok ? r.json() : Promise.reject(r.status))));
      box.addEventListener("mouseover", (ev) => AO.transcriptBlock(ev.target.closest(".tturns > *"), asker, pe));
    }
    // the twenty turns before the first shown, in the button's place; true when they came
    const earlier = async (b) => {
      b.disabled = true;
      try {
        const res = await fetch(`/transcript/${encodeURIComponent(id)}?part=1&before=${encodeURIComponent(b.dataset.before)}`);
        const html = await res.text();
        if (!res.ok) { b.insertAdjacentHTML("afterend", html); return false; }
        const wrap = b.closest(".tearlier");
        const tmp = document.createElement("div"); tmp.innerHTML = html;
        const got = tmp.querySelector(".tturns");
        const shown = $("#tshown");
        if (shown && got) shown.textContent = String((+shown.textContent || 0) + (+got.dataset.turns || 0));
        wrap.replaceWith(...tmp.childNodes);
        showLocalTimes();
        return true;
      } finally { b.disabled = false; }
    };
    box.addEventListener("click", (ev) => {
      const b = ev.target.closest('[data-act="transcript-earlier"]'); if (!b || b.disabled) return;
      earlier(b);
    });
    // **Opened with `?at=<time>`** (§4.5 screen 9, TD-977): the Prompts card's way in for a prompt that
    // left the terminal's history — earlier turns fetched as the button does until the prompt sent at
    // that time is held, the file's start, or `TRANSCRIPT_SEEK` fetches
    const at = new URLSearchParams(location.search).get("at");
    if (!at) return;
    const say = (text) => { const n = document.createElement("p"); n.className = "note tseek"; n.textContent = text; box.prepend(n); };
    AO.transcriptSeek(
      () => [...box.querySelectorAll(".tprompt [data-at]")].find((el) => el.dataset.at === at) || null,
      () => { const b = box.querySelector('[data-act="transcript-earlier"]'); return b ? earlier(b) : Promise.resolve(null); },
    ).then((r) => {
      if (r.found) { const p = r.found.closest(".tprompt"); p.classList.add("tfound"); p.scrollIntoView({ block: "center" }); }
      else if (r.why === "start") say("that prompt is not in this transcript");
      else if (r.why === "further") say("that prompt is further back — press earlier turns");
      else say("earlier turns could not be read — press earlier turns");
    }, () => say("earlier turns could not be read — press earlier turns"));
  };
  AO.TRANSCRIPT_SEEK = 50;  // fetches a `?at=` makes before it hands over to **earlier turns**
  // The seek behind `?at=` (§4.5 screen 9): `find()` the prompt held, else `more()` — the next twenty
  // turns, resolving true when they came, false when a fetch failed, null at the file's start. Resolves
  // `{found}`, or `{why}`: "start", "further" (at `TRANSCRIPT_SEEK` fetches) or "failed". Pure, for a test.
  AO.transcriptSeek = async function (find, more) {
    for (let n = 0; ; n++) {
      const found = find();
      if (found) return { found };
      if (n >= AO.TRANSCRIPT_SEEK) return { why: "further" };
      const got = await more();
      if (got === null) return { why: "start" };
      if (!got) return { why: "failed" };
    }
  };

  // The id a page's hash names, or "" — a hash that does not decode names nothing. Pure, for a test.
  AO.hashId = function (hash) {
    try { return decodeURIComponent(String(hash || "").replace(/^#/, "")); } catch (e) { return ""; }
  };

  // A card's move in the whole Up next order (design §4.4 *A move lands*, §4.5a *Queue page, Up next*,
  // TD-770): `order` the Up next cards' ids, `id` the moved one, `how` "top", "up", "down", or
  // {before: id} / {after: id} for a drop beside a card. The neighbours are the adjacent cards in the
  // whole order, whatever the page hides: `{prev, next, order}` (none: null), or null for a move that
  // leaves the card where it is. Pure, for a test.
  AO.rankMove = function (order, id, how) {
    const i = order.indexOf(id); if (i < 0) return null;
    const rest = order.filter((x) => x !== id);
    let at;  // where the card lands among the others
    if (how === "top") at = 0;
    else if (how === "up") at = i - 1;
    else if (how === "down") at = i + 1;
    else {
      const j = rest.indexOf(how && (how.before || how.after)); if (j < 0) return null;
      at = how.before ? j : j + 1;
    }
    if (at < 0 || at > rest.length || at === i) return null;
    return { prev: at > 0 ? rest[at - 1] : null, next: at < rest.length ? rest[at] : null, order: [...rest.slice(0, at), id, ...rest.slice(at)] };
  };

  // The same move on a Repo page (design §4.4 *A move lands*, TD-901): `own` the repo's own Up next cards,
  // in the whole order `order`. The neighbours are adjacent among `own`, but ⤒ names as `prev` the
  // whole-order card just before the repo's first and a move past the repo's last names as `next` the
  // whole-order card just after it, so a press never leaves the span between the repo's own cards. The
  // card lands as the flush puts it: just after `prev`, else just before `next`, past other repos' cards.
  // `{prev, next, order}` or null for a move that leaves the card where it is. Pure, for a test.
  AO.rankMoveScoped = function (order, own, id, how) {
    const i = own.indexOf(id); if (i < 0 || order.indexOf(id) < 0) return null;
    const rest = own.filter((x) => x !== id), whole = order.filter((x) => x !== id);
    let at;
    if (how === "top") at = 0;
    else if (how === "up") at = i - 1;
    else if (how === "down") at = i + 1;
    else {
      const j = rest.indexOf(how && (how.before || how.after)); if (j < 0) return null;
      at = how.before ? j : j + 1;
    }
    if (at < 0 || at > rest.length || at === i || !rest.length) return null;
    const prev = at > 0 ? rest[at - 1] : (whole[whole.indexOf(rest[0]) - 1] ?? null);
    const next = at < rest.length ? rest[at] : (whole[whole.indexOf(rest[rest.length - 1]) + 1] ?? null);
    const k = prev !== null ? whole.indexOf(prev) + 1 : next !== null ? whole.indexOf(next) : 0;
    return { prev, next, order: [...whole.slice(0, k), id, ...whole.slice(k)] };
  };

  // The Queue's cards wherever they are drawn (design §4.5a *Queue page: card*, *Queue page, Up next:
  // grip / ⤒ ↑ ↓*; the Queue page, TD-771, and the Repo page's Technical debt, TD-770): a press on a
  // card's header folds or opens it, which this browser remembers; an Up next card moves by its grip or
  // ⤒ ↑ ↓, at once on the page, and back with the home's reason in `#qwhy` when it refuses. The Up next
  // order is `#qcards`' `data-upnext`, the whole order whatever the page hides.
  AO.qcards = function (box) {
    const foldKey = "qfold";
    function applyFolds() {
      const folded = new Set(store.get(foldKey, []));
      $$(".qcard.hasrows", box).forEach((c) => {
        const f = folded.has(c.dataset.card); c.classList.toggle("folded", f);
        const h = $(".qhead", c); if (h) h.setAttribute("aria-expanded", f ? "false" : "true");
      });
    }
    function toggleFold(card) {
      const folded = new Set(store.get(foldKey, []));
      if (folded.has(card.dataset.card)) folded.delete(card.dataset.card); else folded.add(card.dataset.card);
      store.set(foldKey, [...folded]); applyFolds();
    }
    // the cards' box: the Queue's one `#qcards`, or on the Repo page's board the column the card is in (TD-903)
    const boxOf = (card) => (card && card.closest(".qcards")) || $("#qcards", box);
    function upnext(q) { try { return JSON.parse((q && q.dataset.upnext) || "[]"); } catch (e) { return []; } }
    function placeCards(order) {  // each box's Up next cards in `order`, after its In progress ones: every
      // column of the board, so a card drawn in two columns moves in both (TD-903)
      $$(".qcards", box).forEach((q) => {
        const ups = $$(".qcard[data-up]", q), at = (c) => order.indexOf(c.dataset.card);
        let after = ups.length ? ups[0].previousElementSibling : null;
        ups.sort((a, b) => at(a) - at(b)).forEach((c) => { if (after) after.after(c); else q.prepend(c); after = c; });
        q.dataset.upnext = JSON.stringify(order);
      });
    }
    async function moveCard(card, how) {
      // on a Repo page the neighbours are the repo's own (`data-scope`, TD-901) in the card's column (TD-903):
      // the Up next cards that column draws
      const q = boxOf(card), scope = (q && q.dataset.scope) || "", before = upnext(q);
      const drawn = new Set($$(".qcard[data-up]", q).map((c) => c.dataset.card));
      const own = scope ? before.filter((x) => drawn.has(x)) : null;
      const m = scope ? AO.rankMoveScoped(before, own, card.dataset.card, how) : AO.rankMove(before, card.dataset.card, how);
      if (!m) return;
      const why = $("#qwhy", box); if (why) why.hidden = true;
      placeCards(m.order);
      try {
        const r = await fetch("/api/rank/move", {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ ids: card.dataset.ids.split(" "), prev: m.prev, next: m.next, ...(scope ? { scope } : {}) }),
        });
        if (!r.ok) { let t = r.statusText; try { t = (await r.json()).detail || t; } catch (err) {} throw new Error(t); }
      } catch (err) {
        placeCards(before);
        if (why) { why.textContent = `${card.dataset.card.replace(/^.*#/, "")} stays where it was: ${err.message}`; why.hidden = false; }
      }
    }
    let dragged = null;
    box.addEventListener("dragstart", (e) => {
      const g = e.target.closest && e.target.closest(".qgrip[draggable]"); if (!g) return;
      dragged = g.closest(".qcard"); dragged.classList.add("dragging");
      try { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragged.dataset.card); e.dataTransfer.setDragImage(dragged, 12, 12); } catch (err) {}
    });
    const dropOf = (e) => {
      const c = dragged && e.target.closest && e.target.closest(".qcard[data-up]");
      if (!c || c === dragged || c.closest(".qcards") !== dragged.closest(".qcards")) return null;  // its own column
      const box2 = c.getBoundingClientRect();
      return { card: c, before: e.clientY < box2.top + box2.height / 2 };
    };
    const clearDrop = () => $$(".qcard.dropbefore, .qcard.dropafter", box).forEach((c) => c.classList.remove("dropbefore", "dropafter"));
    box.addEventListener("dragover", (e) => {
      const d = dropOf(e); clearDrop(); if (!d) return;
      e.preventDefault(); d.card.classList.add(d.before ? "dropbefore" : "dropafter");
    });
    box.addEventListener("drop", (e) => {
      const d = dropOf(e); clearDrop(); if (!d) return;
      e.preventDefault();
      moveCard(dragged, d.before ? { before: d.card.dataset.card } : { after: d.card.dataset.card });
    });
    box.addEventListener("dragend", () => { clearDrop(); if (dragged) dragged.classList.remove("dragging"); dragged = null; });
    box.addEventListener("click", (e) => {
      const mv = e.target.closest(".qmove[data-move]");
      if (mv) return moveCard(mv.closest(".qcard"), mv.dataset.move);
      // a card's header folds it; a link, a button, the grip or an Inbox item in it keeps its own press
      const head = e.target.closest(".qcard.hasrows > .qhead");
      if (head && !e.target.closest("a, button, .qgrip, .qmail, .qsec, details.qdots")) toggleFold(head.closest(".qcard"));
    });
    box.addEventListener("keydown", (e) => {  // a card's header is a button: Enter or Space folds it
      const head = (e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches(".qcard.hasrows > .qhead");
      if (head) { e.preventDefault(); toggleFold(e.target.closest(".qcard")); }
    });
    applyFolds();
    return { applyFolds, toggleFold };
  };

  // The Queue's picks, read in the browser as `ui.queue` reads them on the server (§4.5 screen 12 *Filters*,
  // §4.5a *Queue page: filters, find*; TD-829): `qPicks` is `queue_picks`, `qQuery` `picks_query`, `qWord` and
  // `qFinds` `_find_word` and `_finds`, `qRefs` the home's `refs`, and `qPass` the test `apply_picks` makes of a
  // card, a completed line or an *other work* line. A press answers with these and no request.
  const Q_FILTERS = ["needs-you"];
  AO.qRefs = (text) => {
    const seen = [];
    for (const m of String(text || "").matchAll(/(?<![\w-])(?:([\w.-]+)#)?TD-(\d+)\b/g)) {
      const ref = `${m[1] ? m[1] + "#" : ""}TD-${String(parseInt(m[2], 10)).padStart(3, "0")}`;
      if (!seen.includes(ref)) seen.push(ref);
    }
    return seen;
  };
  AO.qWord = (w) => {
    w = String(w).replace(/\btd-(?=\d)/gi, "TD-");
    const refs = /^(?:[\w.-]+#)?TD-\d+$/.test(w) ? AO.qRefs(w) : [];
    return (refs[0] || w).toLowerCase();
  };
  AO.qFinds = (w, text) => {
    if (/^(?:[\w.-]+#)?td-\d+$/.test(w)) return String(text).split(/\s+/).some((t) => t === w || t.endsWith("#" + w));
    return String(text).includes(w);
  };
  AO.qPicks = (search) => {
    const p = new URLSearchParams(search || "");
    const many = (k) => {
      const out = [];
      p.getAll(k).forEach((v) => String(v).split(",").forEach((w) => { w = w.trim(); if (w && !out.includes(w)) out.push(w); }));
      return out;
    };
    const last = (k) => p.getAll(k).pop() || "";  // a repeated key reads as the server's does: the last
    const f = last("filter");
    // the old `repo` and `kind` picks and `filter=steering` read as not picked (TD-1287)
    return { filter: Q_FILTERS.includes(f) ? f : "", team: many("team"), find: last("find").split(/\s+/).filter(Boolean).join(" ") };
  };
  AO.qQuery = (picks, change) => {
    const p = { filter: picks.filter || "", team: [...(picks.team || [])], find: picks.find || "" };
    Object.entries(change || {}).forEach(([k, v]) => {
      if (k === "team" && Array.isArray(v)) p.team = [...v];  // a list replaces: `team: []` is **All**
      else if (k === "team") p.team = p.team.includes(v) ? p.team.filter((x) => x !== v) : [...p.team, v];
      else if (k === "filter") p.filter = p.filter === v ? "" : v;
      else p[k] = v;
    });
    const parts = p.filter ? [`filter=${p.filter}`] : [];
    if (p.team.length) parts.push(`team=${encodeURIComponent(p.team.join(","))}`);
    if (p.find) parts.push(`find=${encodeURIComponent(p.find)}`);
    return "/queue" + (parts.length ? "?" + parts.join("&") : "");
  };
  // Recently completed's windows nest (§4.5 *Page loads*: *only what is shown*, TD-882): the page holds the
  // lines of the window it was sent (`data-loaded`), so a narrower pick answers at once and a wider one is the
  // window to read — "" when nothing is to be read
  AO.Q_WINDOWS = ["4h", "day", "week", "month"];
  AO.qWinFetch = (loaded, want) => {
    const at = (w) => AO.Q_WINDOWS.indexOf(w);
    return at(want) > at(loaded || "day") ? want : "";
  };
  // a card's find text, built here from its rows' ids and titles rather than sent (§4.5 *Page loads*: *Nothing
  // the page does not read*, TD-892): `_find_text`'s rule — each id whole and bare, every word lower-cased.
  // `rows`: [{qid, title}], the card's header first; `qCardRows` reads them off a drawn card
  AO.qFindText = (rows) => {
    const bits = [];
    (rows || []).forEach((r) => {
      const q = String(r.qid || "");
      bits.push(q);
      AO.qRefs(q).forEach((ref) => bits.push(ref, ref.replace(/^.*#/, "")));
      bits.push(String(r.title || ""));
    });
    return bits.join(" ").toLowerCase();
  };
  AO.qCardRows = (card) => $$(".qhead[data-qid], .qrows > .qrow[data-qid]", card)
    .map((el) => ({ qid: el.dataset.qid, title: ($(".qtitle", el) || {}).textContent || "" }));
  AO.qFiltered = (picks) => !!(picks.filter || picks.team.length || picks.find.split(/\s+/).filter(Boolean).length);
  // `item`: {kind: "card" | "line" | "other", status, repos, find}; `teams`: a team's name → its repo, and a
  // name no team holds is a repo — a repo chip's pick (TD-1287)
  AO.qPass = (item, picks, teams) => {
    let repos = null;
    if (picks.team.length) {
      const own = (t) => Object.prototype.hasOwnProperty.call(teams || {}, t);
      repos = new Set(picks.team.map((t) => (own(t) ? teams[t] : t)).filter(Boolean));
      if (!repos.size) repos = new Set(["\0"]);
    }
    const words = picks.find.split(/\s+/).filter(Boolean).map(AO.qWord);
    const statusPick = !!picks.filter;
    if (item.kind === "other") return !(statusPick || !!repos || words.length > 0);
    const byRepoFind = !(repos && !(item.repos || []).some((r) => repos.has(r))) && words.every((w) => AO.qFinds(w, item.find || ""));
    if (item.kind === "line") return !statusPick && byRepoFind;
    let ok = byRepoFind;
    if (picks.filter === "needs-you") ok = ok && item.status === "needs you";
    return ok;
  };

  // The Queue page (design §4.5 screen 12, §4.5a *Queue page*; TD-771): the cards (`AO.qcards`), the
  // Recently completed window picker — its choice remembered in this browser, *day* first — a completed
  // line that opens to what was done, `/queue#TD-n` opening the card that holds the entry, and the lists
  // re-read on the poll and on the `queue` event.
  // the Spend page (design §4.5 screen 13, §4.5a *Spend page*; TD-832): every pick is a link carried in the URL,
  // and a press re-reads the body (`part=1`) in place rather than the page; a failed read follows the link
  AO.spend = function () {
    const box = $("#spendpage"); if (!box) return;
    const body = $("#spendbody", box);
    let seq = 0;  // the newest press wins: an older read that lands after it is dropped
    async function go(href, push) {
      const u = new URL(href, location.href), mine = ++seq;
      u.searchParams.set("part", "1");
      try {
        const r = await fetch(u, { headers: { Accept: "text/html" } });
        if (!r.ok) throw new Error(String(r.status));
        const text = await r.text();
        if (mine !== seq) return;
        body.innerHTML = text;
        u.searchParams.delete("part");
        if (push) history.pushState({ spend: 1 }, "", u.pathname + u.search);
      } catch (err) { location.href = href; }
    }
    box.addEventListener("click", (ev) => {
      const a = ev.target.closest("a[data-spend]");
      if (!a || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button !== 0) return;
      ev.preventDefault();
      go(a.getAttribute("href"), true);
    });
    window.addEventListener("popstate", () => go(location.href, false));
  };

  AO.queue = function () {
    const box = $("#queuepage"); if (!box) return;
    const lists = $("#queuelists", box);
    const qc = AO.qcards(box);
    // a group's heading folds or opens it, remembered in this browser (§4.5a *Queue page: group heading*, TD-828);
    // a find opens the groups that hold what it found, without changing what is remembered
    const groupKey = "qgfold";
    function applyGroups() {
      const folded = new Set(store.get(groupKey, [])), finding = !!($("#qfindbox", box) || {}).value;
      $$(".qgroup", box).forEach((g) => {
        const found = finding && !!g.querySelector(".qcard:not(.qoff), .qdline:not(.qoff):not([hidden])");
        const f = folded.has(g.dataset.group) && !found;
        g.classList.toggle("qgfolded", f);
        const h = $(".qghead", g); if (h) h.setAttribute("aria-expanded", f ? "false" : "true");
      });
    }
    function toggleGroup(g, open) {
      const folded = new Set(store.get(groupKey, []));
      if (open === true || (open === undefined && folded.has(g.dataset.group))) folded.delete(g.dataset.group); else folded.add(g.dataset.group);
      store.set(groupKey, [...folded]); applyGroups();
    }
    // a card's *Answered for you* and *FYI* each carry Dismiss all over that section's rows on screen (TD-828)
    function wire() {
      $$(".qsec .qdismissall", lists).forEach((b) => {
        const sec = b.closest(".qsec"), which = sec.dataset.sec;
        AO.dismissOnScreen(b, () => $$(".mailrow", sec), which === "fyi" ? "nothing in this FYI to dismiss" : "no answers on screen to dismiss",
          AO.DISMISS_ASK[which], reread);
      });
    }
    // the picks (TD-829): the URL's, applied in the browser; a URL that carries any (but the find's words)
    // becomes the browser's memory (`qpicks`), which `base.html`'s head restores on a bare `/queue`
    let picks = AO.qPicks(location.search);
    const findbox = $("#qfindbox", box), filters = $("#qfilters", box);
    let teams = {};
    try { teams = JSON.parse((filters && filters.dataset.teams) || "{}") || {}; } catch (err) { teams = {}; }
    const remember = () => store.set("qpicks", AO.qQuery({ ...picks, find: "" }).slice("/queue".length));
    if (picks.filter || picks.team.length) remember();
    // each card's find text, built once per card drawn: at load, and for the cards a re-read swaps in (TD-892)
    const finds = new WeakMap();
    const cardFind = (el) => { if (!finds.has(el)) finds.set(el, AO.qFindText(AO.qCardRows(el))); return finds.get(el); };
    function applyPicks() {
      const filtered = AO.qFiltered(picks);
      const card = (el) => ({ kind: "card", status: el.dataset.status || "",
        repos: (el.dataset.repos || "").split(" ").filter(Boolean), find: cardFind(el) });
      $$(".qgroup .qcard", lists).forEach((el) => el.classList.toggle("qoff", !AO.qPass(card(el), picks, teams)));
      $$(".qdline", lists).forEach((el) => el.classList.toggle("qoff", !AO.qPass({ kind: "line", repos: [el.dataset.repo || ""], find: el.dataset.find || "" }, picks, teams)));
      $$(".qother", lists).forEach((el) => el.classList.toggle("qoff", !AO.qPass({ kind: "other" }, picks, teams)));
      // each group's share, *(n of m)* while anything is picked (§4.5 screen 12 *Groups*)
      const share = (el, shown) => { el.textContent = `(${filtered ? shown + " of " : ""}${el.dataset.of})`; };
      $$(".qgroup", lists).forEach((g) => {
        if (g.dataset.group === "completed") {
          $$(".qghead .qwinword", g).forEach((w) => {
            const s = $(".qshare", w); if (!s) return;
            share(s, $$(".qdline:not(.qoff)", g).filter((ln) => (ln.dataset.w || "").split(" ").includes(w.dataset.wv))
              .reduce((n, ln) => n + Number(ln.dataset.n || 1), 0));
          });
        } else {
          const s = $(".qghead .qshare", g); if (s) share(s, $$(".qcard:not(.qoff)", g).length);
        }
      });
      const none = $("#qnone", lists); if (none) none.hidden = !(filtered && !$(".qgroup .qcard:not(.qoff)", lists));
      const miss = $("#qfindmiss", lists); if (miss) miss.hidden = (miss.dataset.for || "") !== picks.find;
      if (filters) $$("a.qf[data-k]", filters).forEach((a) => {
        const k = a.dataset.k, v = a.dataset.v;
        const on = k === "all" ? !picks.team.length : k === "filter" ? picks.filter === v : (picks[k] || []).includes(v);
        a.setAttribute(k === "filter" ? "aria-checked" : "aria-pressed", on ? "true" : "false");  // the switch is checked
        a.setAttribute("href", AO.qQuery(picks, k === "all" ? { team: [] } : { [k]: v }));
      });
    }
    function setPicks(next, push) {
      picks = next;
      const url = AO.qQuery(picks);
      if (url !== location.pathname + location.search) history[push ? "pushState" : "replaceState"](null, "", url + location.hash);
      apply();
    }
    // an id the find names that no open card holds is asked of the server once, for the archive's line
    function held(ref) {
      return $$(".qgroup .qcard", lists).some((el) => AO.qRefs((el.dataset.ids || "").split(" ").join(" "))
        .some((r) => r === ref || r.replace(/^.*#/, "") === ref));
    }
    // the window of Recently completed's lines the page holds, and the wider one picked, if any (TD-882)
    const loaded = () => ($("#qcompleted", lists) || { dataset: {} }).dataset.loaded || "day";
    // a window a read answered without (an older home) is not asked again on every apply, only by the poll
    let short = "";
    const loading = () => { const w = AO.qWinFetch(loaded(), store.get("qwin", "day")); return w === short ? "" : w; };
    function apply() {
      qc.applyFolds();
      applyPicks();
      const win = store.get("qwin", "day");
      $$(".qwin", box).forEach((b) => b.setAttribute("aria-pressed", b.dataset.win === win ? "true" : "false"));
      $$(".qwinword", box).forEach((el) => (el.hidden = el.dataset.wv !== win));
      let shown = 0;
      $$(".qdline", box).forEach((el) => { el.hidden = !(el.dataset.w || "").split(" ").includes(win); if (!el.hidden) shown++; });
      const none = $(".qdnone", box); if (none) none.hidden = shown > 0;
      applyGroups();  // after the window hides its lines, so a find opens only a group it found something in
      // a window wider than the lines sent is read once, by the lists' read (TD-882); `base.html`'s head held
      // the lists back until the remembered window is drawn, never *day* first
      if (loading()) reread(); else delete document.documentElement.dataset.qpend;
    }
    function openLine(line) {
      const body = $(".qdbody", line), head = $(".qdhead", line); if (!body) return;
      body.hidden = !body.hidden; head.setAttribute("aria-expanded", body.hidden ? "false" : "true");
    }
    // an element on a card, opened and scrolled to: an entry's row or header by its id (`TD-n`, or
    // `<repo>#TD-n` where the page writes one bare), else an Inbox item drawn on a row by its id
    function onCard(id) {
      if (!id) return null;
      const el = document.getElementById(id) || document.getElementById(id.replace(/^.*#/, ""))
        || $(`.mailrow[data-msg="${CSS.escape(id)}"]`, box) || $(`[data-card="${CSS.escape(id)}"]`, box);
      return el && box.contains(el) ? el : null;
    }
    // a target a pick hides (`qoff`) is shown by the page without the picks, at the same address — dropped
    // in the browser (TD-829), so it is shown at once and the remembered picks stand
    function hidden(el, keep) {
      if (!el.closest(".qoff")) return false;
      picks = AO.qPicks(""); if (findbox) findbox.value = "";
      history.replaceState(null, "", `/queue${keep}${location.hash}`);
      apply();
      return false;
    }
    function reveal(el, ring) {
      const g = el.closest(".qgroup"); if (g && g.classList.contains("qgfolded")) toggleGroup(g, true);
      const card = el.closest(".qcard");
      if (card && card.classList.contains("folded")) qc.toggleFold(card);
      el.scrollIntoView({ block: "center" });
      if (ring) { $$(".qring", box).forEach((x) => x.classList.remove("qring")); el.classList.add("qring"); }
    }
    function showHash() {
      const el = onCard(AO.hashId(location.hash)); if (el && !hidden(el, "")) reveal(el, false);
    }
    // a TD item's address (§4.5 screen 12 *Addresses*, TD-771): `?card=<top id>&row=<TD-n>&item=<entry id>`
    // opens the card, scrolls to the row (the header for the top entry) and rings the item
    function showAddress() {
      const p = new URLSearchParams(location.search);
      const card = p.get("card"), row = p.get("row"), item = p.get("item");
      if (!card && !row && !item) return;
      const it = item && onCard(item), at = onCard(row) || onCard(card);
      const keep = new URLSearchParams(); [["card", card], ["row", row], ["item", item]].forEach(([k, v]) => { if (v) keep.set(k, v); });
      if ((it && hidden(it, `?${keep}`)) || (at && hidden(at, `?${keep}`))) return;
      if (at) reveal(at, !it);
      if (it) reveal(it, true);
    }
    box.addEventListener("click", (e) => {
      const f = e.target.closest("#qfilters a.qf[data-k]");
      if (f && !(e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1)) {
        e.preventDefault();
        // **All** clears the chips alone: the switch and the find keep their state (TD-1287)
        if (f.dataset.k === "all") { setPicks({ ...picks, team: [] }, true); return remember(); }
        setPicks(AO.qPicks(AO.qQuery(picks, { [f.dataset.k]: f.dataset.v }).slice("/queue".length)), true);
        return remember();
      }
      const w = e.target.closest(".qwin[data-win]");
      if (w) { store.set("qwin", w.dataset.win); return apply(); }
      const gh = e.target.closest(".qghead");
      if (gh) return toggleGroup(gh.closest(".qgroup"));
      // an item about another row says *on TD-n*: the link scrolls to that row and rings it (§4.5 screen 12)
      const on = e.target.closest("a.qon[data-on]");
      if (on) { const el = onCard(on.dataset.on); if (el) { e.preventDefault(); reveal(el, true); } return; }
      const head = e.target.closest(".qdline.opens > .qdhead");
      if (head && !e.target.closest("a, button")) openLine(head.parentElement);
    });
    // *after TD-n* lights the row it names while it is hovered or focused (§4.5 screen 12 *A card*, TD-1131)
    const lit = (on) => (e) => {
      const a = e.target.closest && e.target.closest(".qafter a.qon[data-on]");
      const el = a && onCard(a.dataset.on);
      if (el) el.classList.toggle("qlit", on);
    };
    box.addEventListener("mouseover", lit(true)); box.addEventListener("mouseout", lit(false));
    box.addEventListener("focusin", lit(true)); box.addEventListener("focusout", lit(false));
    box.addEventListener("keydown", (e) => {
      const key = (e.key === "Enter" || e.key === " ") && e.target.matches;
      if (key && e.target.matches(".qghead")) { e.preventDefault(); return toggleGroup(e.target.closest(".qgroup")); }
      const head = key && e.target.matches(".qdline.opens > .qdhead");
      if (head) { e.preventDefault(); return openLine(e.target.parentElement); }
      // Space toggles the Needs you switch as Enter does (a link answers Enter alone; TD-1287)
      if (e.key === " " && e.target.matches && e.target.matches("#qfilters .qswitch")) { e.preventDefault(); e.target.click(); }
    });
    window.addEventListener("hashchange", showHash);
    window.addEventListener("popstate", () => {
      picks = AO.qPicks(location.search); if (findbox) findbox.value = picks.find;
      if (picks.filter || picks.team.length) remember(); else store.set("qpicks", "");
      apply();
    });
    let typing = null;
    const typed = () => ({ ...picks, find: String(findbox.value || "").split(/\s+/).filter(Boolean).join(" ") });
    if (findbox) {
      findbox.addEventListener("input", () => {
        clearTimeout(typing);
        typing = setTimeout(() => { typing = null; setPicks(typed(), false); }, 150);
      });
      findbox.form.addEventListener("submit", (e) => {
        e.preventDefault(); clearTimeout(typing);
        setPicks(typed(), false);
        if (AO.qRefs(picks.find.replace(/\btd-(?=\d)/gi, "TD-")).some((r) => !held(r))) reread();
      });
    }
    let busy = false;
    async function reread() {
      if (busy || box.querySelector(".qcard.dragging")) return; busy = true;
      let read = false;
      // the lines of the window held, or of the picked one where it is wider (TD-882)
      const win = AO.qWinFetch(loaded(), store.get("qwin", "day")) || loaded();
      try {
        const q = new URLSearchParams(location.search); q.set("part", "1"); q.set("win", win);
        const res = await fetch(`/queue?${q}`);
        if (res.ok) {
          read = true;
          const opened = $$(".qdline .qdbody:not([hidden])", lists).map((el) => el.closest(".qdline").dataset.key);
          lists.innerHTML = await res.text();
          // the filter row stands outside the lists, so typed find words and its focus survive: its numbers follow
          const n = $("#qcounts", lists);
          if (n) {
            const a = $("#qfneedsn", box);
            if (a) a.textContent = n.dataset.needs || "0";
          }
          opened.forEach((k) => { const ln = k && $(`.qdline[data-key="${CSS.escape(k)}"]`, lists); if (ln) openLine(ln); });
          AO.reopenFolds(lists);  // a row's *details* the person opened, filled from what was kept (TD-891)
          apply();
          wire();
        }
      } catch (err) { /* the next poll tries again */ } finally {
        busy = false;
        // a wider window picked while this read was out: read once more, never again for the same window
        if (read && AO.qWinFetch(loaded(), win) === win) short = win;
        if (read && loading() && loading() !== win) setTimeout(reread, 0);
      }
    }
    apply();
    wire();
    showHash();
    showAddress();
    setInterval(reread, 30000);
    // an Inbox item drawn on a card opens its message page as the Inbox's does: Back returns here, and j / k
    // step through the items this page draws (§4.5 screen 6 *Where a row is drawn*)
    box.addEventListener("click", (e) => {
      const link = e.target.closest(".mailrow a.pagelink");
      const body = !link && e.target.closest(".mailrow[data-page] .body, .mailrow[data-page] > .subj");
      if (!link && !body) return;
      if (body && (e.target.closest("a, summary, button") || String(window.getSelection ? window.getSelection() : "").trim())) return;
      if (link && (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1)) return;
      e.preventDefault();
      AO.openEntry(e.target.closest(".mailrow").dataset.msg);
    });
    // a press on a row drawn here by the Inbox's renderer refreshes this page's lists (TD-771)
    if (typeof AO.refreshInboxPage !== "function") AO.refreshInboxPage = reread;
    let soon = null;
    connectEvents((ev) => {
      if (ev.event !== "queue") return;
      clearTimeout(soon);
      soon = setTimeout(() => { soon = null; reread(); }, 1500);
    });
    // …and on the mail a card carries (§4.5 screen 12, TD-771): the Inbox's counts moved, so a question
    // was asked or answered — read again, as the Inbox does
    let rev = null;
    document.addEventListener("ao:counts", (e) => {
      const r = e.detail && e.detail.rev;
      if (rev !== null && r !== rev) { clearTimeout(soon); soon = setTimeout(() => { soon = null; reread(); }, 1500); }
      rev = r === undefined ? rev : r;
    });
  };

  // the Repo page's windows, narrowest first: the rows of one hold every narrower window's (TD-882)
  AO.REPO_WINDOWS = ["day", "week", "month"];
  AO.TD_ID = /^[A-Za-z]+-\d+$/;  // an entry's id, as a ledger row carries it
  AO.repo = function () {
    const box = $("#repopage"); if (!box) return;
    const repo = box.dataset.repo, whoKey = "doingwho:" + repo, teamKey = "doingteam:" + repo;
    const lists = $("#repolists"), groups = $("#groups");
    // the facet's *closed* block carries its window (`?win=week#completed`, TD-604): the page's one picker takes it
    const carried = new URLSearchParams(location.search).get("win");
    if (["day", "week", "month"].includes(carried)) store.set("win", carried);
    function apply() {
      syncSummaries();
      applyFolds();
      // Recently completed follows the page's one window picker (§4.5 screen 11 item 3, TD-604)
      const win = store.get("win", "day");
      $$("#completed .wv", box).forEach((el) => (el.hidden = el.dataset.wv !== win));
      $$("#completed .bwin button", box).forEach((b) => b.setAttribute("aria-pressed", b.dataset.win === win ? "true" : "false"));
      // a window wider than the one sent is read once, by the lists' read (§4.5 *Page loads*, TD-882)
      if (loading()) reread();
      // a team pick and a doer pick AND (§4.5a *Repo page: doing filters*, TD-740); *all* is neither
      const who = store.get(whoKey, "");
      const picked = store.get(teamKey, ""), team = $$(".dchips .chip[data-team]", box).some((c) => c.dataset.team === picked) ? picked : "";
      $$(".dchips .chip", box).forEach((c) => {
        const on = c.dataset.team !== undefined ? c.dataset.team === team : c.dataset.who === who && (!!who || !team);
        c.setAttribute("aria-pressed", on ? "true" : "false");
      });
      $$("#doing .drow", box).forEach((r) => (r.hidden = (!!who && r.dataset.who !== who) || (!!team && r.dataset.team !== team)));
    }
    // Only what is shown (§4.5 *Page loads*, TD-882): a folded list's rows past its fold, and a Recently
    // completed window wider than the one sent (`data-loaded`), come by the lists' read — `win` the window,
    // `open` every list unfolded on this page view and an anchor's id not yet sent — and are kept by each read
    const opened = new Set();
    const sought = new Set();  // an anchor's id is asked for once: one in no list is not asked again
    let want = "", short = "", again = false;
    const loaded = () => ($("#completed", lists) || { dataset: {} }).dataset.loaded || "day";
    const wider = (a, b) => (AO.REPO_WINDOWS.indexOf(b) > AO.REPO_WINDOWS.indexOf(a) ? b : a);
    // the wider window picked, if any; one a read answered without (an older UI) is the poll's to ask again
    const loading = () => { const w = wider(loaded(), store.get("win", "day")); return w === loaded() || w === short ? "" : w; };
    let busy = false;
    let inflight = "";
    async function reread() {
      const win = wider(loaded(), store.get("win", "day")), asked = want;
      const q = new URLSearchParams({ part: "1", win });
      const ask = [...opened, ...(asked ? [asked] : [])];
      if (ask.length) q.set("open", ask.join(","));
      // a read already out for the same rows answers this one too; one for other rows is read after it
      if (busy) { if (String(q) !== inflight) again = true; return; }
      busy = true; inflight = String(q);
      let read = false;
      try {
        const res = await fetch(`/repo/${encodeURIComponent(repo)}?${q}`);
        if (res.ok) {
          read = true;
          const kept = AO.denyWhys(lists), open = $$(".secinfo:not([hidden])", lists).map((el) => el.id);
          lists.innerHTML = await res.text();
          // the title line and the seams come with the lists (`part=1`): swapped in place, above the cards
          const head = $("#repohead", lists), was = $("#repohead", box);
          if (head && was && was !== head) was.replaceWith(head);
          AO.restoreDenyWhys(lists, kept);
          AO.reopenFolds(lists);  // the board's *not shown* fold, opened for this page view (TD-220)
          open.forEach((id) => { const el = document.getElementById(id); if (el) el.hidden = false; });
          opened.forEach((k) => unfold(k, true));
          apply();
          if (asked && want === asked) { want = ""; showHash(); }  // the anchor's row, now sent
        }
      } catch (err) { /* the next poll tries again */ } finally {
        busy = false; inflight = "";
        if (!read) $$("[data-unsent][disabled]", lists).forEach((b) => (b.disabled = false));  // press again
        if (read && loaded() !== win) short = win;
        if (again) { again = false; setTimeout(reread, 0); }
      }
    }
    async function holdEntry(b) {
      const id = b.dataset.tdhold, release = !!b.dataset.release;
      b.disabled = true;
      const w = AO.toast(`${release ? "releasing" : "holding"} ${id}…`, false, "", true);
      try {
        const r = await fetch("/api/ledger/hold", {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ repo: b.dataset.repo, id, release }),
        });
        if (!r.ok) { let t = r.statusText; try { t = (await r.json()).detail || t; } catch (err) {} throw new Error(t); }
        w.settle(release ? `${id} released: pickable now` : AO.heldWords(id, await r.json().catch(() => ({}))), true);
        reread();
      } catch (err) {
        b.disabled = false;
        w.settle(`${id}: ${err.message}`);
      }
    }
    function unfold(key, read) {
      opened.add(key);
      const b = $(`[data-unfold="${CSS.escape(key)}"]`, box);
      // its rows come first; after a read that still lacks them (an older UI), the button stays to press again
      if (b && b.dataset.unsent !== undefined) { if (!read) { b.disabled = true; reread(); } return; }
      $$(`.rrow.folded[data-list="${CSS.escape(key)}"]`, box).forEach((r) => r.classList.remove("folded"));
      if (b) { b.hidden = true; b.dataset.unfolded = key; }
    }
    // The Technical debt cards (§4.5 screen 11 item 2, TD-770): the Queue's own, folded, opened and moved
    // as on the Queue page (`AO.qcards`)
    const qc = AO.qcards(box);
    const applyFolds = qc.applyFolds, toggleFold = qc.toggleFold;
    // A link to an entry (`/repo/<name>#TD-227`, the Inbox's team start row) names a row its list may
    // have folded, and a hidden row cannot be scrolled to: unfold that list, then go to the row. On the
    // cards, the card that holds the entry is opened first (§4.5a *Repo page: Technical debt cards*).
    function showHash() {
      const id = AO.hashId(location.hash), row = id && document.getElementById(id);
      // a row past its list's fold was not sent: the lists' read fetches its list, then lands on it (TD-882)
      if (!row && AO.TD_ID.test(id) && $("#board", lists) && !sought.has(id)) {
        sought.add(id); want = id; return reread();
      }
      if (!row || !box.contains(row)) return;
      const card = row.closest(".qcard");
      if (card && card.classList.contains("folded")) toggleFold(card);
      else if (!card && !row.dataset.list && !row.closest("#board")) return;
      else if (!card && row.dataset.list && row.classList.contains("folded")) unfold(row.dataset.list);
      const fold = row.closest("details.bfold"); if (fold) fold.open = true;  // For you's *no lane takes these*
      row.scrollIntoView({ block: "center" });
    }
    // the cards' own presses, as on the Org (TD-740); a card's team badge opens the Org filtered to that team
    wireGroups(groups);
    groups.addEventListener("click", (e) => {
      const b = e.target.closest(".badge.team[data-team]");
      if (b && b.dataset.team) { e.preventDefault(); location.href = "/?team=" + encodeURIComponent(b.dataset.team); }
    });
    box.addEventListener("click", (e) => {
      // a facet's selector: `wireGroups` picked it; the window picker moves Recently completed too
      if (e.target.closest(".tsum .seg[data-pick] button")) return apply();
      // Merged's own picker, the page's one window (§4.5 screen 11 *Merged*, TD-903)
      const wb = e.target.closest("#completed .bwin button[data-win]");
      if (wb) { store.set("win", wb.dataset.win); return apply(); }
      const chip = e.target.closest(".dchips .chip");
      if (chip && chip.dataset.team !== undefined) { store.set(teamKey, store.get(teamKey, "") === chip.dataset.team ? "" : chip.dataset.team); return apply(); }
      if (chip) { store.set(whoKey, chip.dataset.who); if (!chip.dataset.who) store.set(teamKey, ""); return apply(); }
      const more = e.target.closest("[data-unfold]");
      if (more) return unfold(more.dataset.unfold);
      // **Hold** / **Release** on an entry (§4.5a, TD-710, TD-736): the home's clock, no ledger edit
      const hold = e.target.closest("[data-tdhold]");
      if (hold && !hold.disabled) return holdEntry(hold);
      // a board row's team badge: here it opens the Org filtered to that team (in the Inbox it picks the rail)
      const badge = e.target.closest(".mailrow .badge.team[data-team]");
      if (badge && badge.dataset.team) { location.href = "/?team=" + encodeURIComponent(badge.dataset.team); return; }
      const i = e.target.closest(".rsec .imark");
      if (i) { const panel = document.getElementById(i.getAttribute("aria-controls")); if (panel) { panel.hidden = !panel.hidden; i.setAttribute("aria-expanded", panel.hidden ? "false" : "true"); } }
    });
    layout();  // the cards' order, the folds and the facets' faces, as the Org draws them
    apply();
    showHash();
    window.addEventListener("hashchange", showHash);
    setInterval(reread, 30000);  // the Inbox's poll; the events below are the fast path
    // the Org's stream, whole: the cards and headers take its deltas (TD-740), and a burst of
    // deltas is one re-read of the lists, a second and a half after the last
    // Only this repo's news re-reads the lists: its `repos` push, a doing call or a delta of a card on the
    // page — the full stream carries every repo's — and a burst waits at most five seconds (`first`)
    let soon = null, first = 0;
    const root = box.dataset.root || "";
    const mine = (ev) => (ev.event === "repos" ? String(ev.root || "") === root
      : ev.event === "doing" || ev.event === "queue" ? true
      : (ev.event === "session" || ev.event === "gone") && !!$(`#card-${CSS.escape(String(ev.id || ""))}`));
    connectEvents((ev) => {
      const ours = mine(ev);  // before the delta: a card that leaves is still on the page
      groupsEvent(ev, repo);
      if (!ours && !((ev.event === "session") && $(`#card-${CSS.escape(String(ev.id || ""))}`))) return;
      if (!soon) first = Date.now();
      clearTimeout(soon);
      soon = setTimeout(() => { soon = null; reread(); }, Math.max(0, Math.min(1500, first + 5000 - Date.now())));
    });
  };

  // The toast of a **Hold** (§4.5a *Repo page: Hold / Release on an entry*, TD-736): what the hold did,
  // from the reply's `told` (a reader among them, `readers`, is told to leave its PR unmerged) and
  // `untold`, each line *could not tell <name>: <why>*
  AO.heldWords = function (id, got) {
    const readers = new Set(got.readers || []);
    const told = (got.told || []).map((n) => `${n} told to ${readers.has(n) ? "leave its PR unmerged" : "drop it"}`);
    return [`${id} held`, ...told, ...(got.untold || [])].join(" · ");
  };

  // ---- New session: the anchor rule, shown before you press Start ----
  AO.newSession = function () {
    // the form's own Directory field: the top bar's Shell form carries a hidden `dir` of its own, first
    // in the page, which a bare `[name=dir]` found — so a Repo pick wrote there and Start posted the
    // field as the page drew it (found by TD-294 slice 2's browser check)
    const dir = $("form[action='/new'] [name=dir]"), here = $("[name=where][value=here]"), wt = $("[name=where][value=worktree]"), note = $("#occupancy");
    // Declared up here, not beside `nameCheck` below: the occupancy check calls it when it moves
    // the scope to a worktree, and a `const` read before its declaration is a ReferenceError.
    const nm = $("[name=name]"), start = $("button[type=submit]"), nnote = $("#namecheck");
    const herechoice = $("#herechoice"), inuse = $("#hereinuse"), profSel = $("#profile");
    // Profile is the one tool pick (§4.5a New session **the form**, TD-284): its last choice is the shell
    const isShell = () => !!profSel && !!profSel.selectedOptions[0] && profSel.selectedOptions[0].dataset.adapter === "shell";
    // the Host pick (TD-284 slice 3): every reading about a place is the picked host's (§4.4a *The New
    // session form on another host*, TD-294) — each read below carries it as `host`
    const hostSel = $("#host");
    const away = () => !!hostSel && hostSel.selectedIndex > 0;
    const hq = () => (away() ? `&host=${encodeURIComponent(hostSel.value)}` : "");
    // Start is refused by either check: a live holder of the name, or an occupied directory that is
    // not a git repo; each sets its own flag and the button follows both
    let nameBlocked = false, dirBlocked = false, missingDir = false, memberBlocked = false;
    // **Where** follows the Repo and the Profile until the person picks it, or the form came filled in
    let whereTouched = !!document.querySelector("form[data-prefilled]");
    // …or a host it cannot reach: a record's host with no live link stays picked and refuses Start
    const hostBlocked = () => !!hostSel && !!hostSel.selectedOptions[0] && hostSel.selectedOptions[0].disabled;
    const gate = () => {
      start.disabled = nameBlocked || dirBlocked || missingDir || hostBlocked() || memberBlocked;
      const hb = $("#hostblock");
      if (hb) hb.innerHTML = hostBlocked() ? `⚠ <b>${esc(hostSel.value)}</b>: ${esc(hostSel.selectedOptions[0].title || "not reachable")} — pick another host to start` : "";
    };
    // **Repo** (§4.5a New session **the form**, TD-284 slice 4): a registered checkout fills `dir`, which
    // is what Start posts; *another directory…* opens the typed path, checked that it is there
    const repoSel = $("#repo"), dirfield = $("#dirfield"), dnote = $("#dircheck");
    const other = () => !repoSel || !!(repoSel.selectedOptions[0] && repoSel.selectedOptions[0].dataset.other);
    let dseq = 0;
    // **Where** offers *Worktree <name> · new* for a git repo only (§4.5a New session **Where**): a typed
    // directory the check reads as no checkout has the choice hidden and *The checkout itself* picked
    // (TD-296 #3); a host that cannot say (`git: null`) leaves it offered
    function offerWorktree(yes) {
      const choice = wt && wt.closest("label"); if (!choice) return;
      choice.hidden = !yes;
      // the form's move, not the person's: no change event, so Where is not marked touched (review of #989)
      if (!yes && wt.checked && here) { here.checked = true; nameCheck(); }
    }
    async function dirCheck() {
      const v = dir.value.trim(), my = ++dseq;
      if (!other() || !v) { missingDir = false; if (dnote) dnote.textContent = ""; offerWorktree(true); gate(); return; }
      try {
        const o = await (await fetch(`/api/dir_check?dir=${encodeURIComponent(v)}${hq()}`)).json();
        if (my !== dseq) return;
        offerWorktree(o.git !== false);
        // a host that did not answer is said, never a refusal: the create's own refusal is Start's
        missingDir = o.exists === false;
        dnote.innerHTML = missingDir ? `⚠ <b>${esc(o.why)}</b>` : o.exists === null ? esc(o.why) : "";
      } catch (e) { missingDir = false; dnote.textContent = ""; }
      gate();
    }
    function applyRepo(fire) {
      if (!repoSel) return;
      dirfield.hidden = !other();
      applyMode();
      if (!other() && dir.value !== repoSel.value) { dir.value = repoSel.value; if (fire) dir.dispatchEvent(new Event("change")); }
      dirCheck();
    }
    // Team narrows the list to its checkouts (its change, or the directory's, re-reads it); a choice
    // it leaves out moves to the first kept. A Team's checkouts are its host's, which the Team pick sets.
    // There is no Project picker (§4.9 *Home and reach*, TD-722): the badge is the directory's repo's.
    function kept() {
      let keep = null;
      const t = teamSel && teamSel.selectedOptions[0];
      if (t && t.value) { try { keep = JSON.parse(t.dataset.dirs || "[]"); } catch (e) { keep = []; } }
      return { keep, names: null };
    }
    function narrowRepos() {
      if (!repoSel) return;
      const { keep: paths, names } = kept();
      for (const o of repoSel.options) {
        if (!o.dataset.other) o.hidden = (!!paths && !paths.includes(o.value)) || (!!names && !names.includes(o.dataset.name));
      }
      const cur = repoSel.selectedOptions[0];
      if (cur && cur.hidden) {
        const first = [...repoSel.options].find((o) => !o.hidden);
        repoSel.value = first ? first.value : "";
        applyRepo(true);
      }
    }
    // a directory set for the person (a Team's or Project's first checkout) is its Repo choice when one
    // is, and is checked as a typed one when not (review of #950)
    function syncRepo() {
      if (!repoSel) return;
      const hit = [...repoSel.options].find((o) => !o.dataset.other && !o.hidden && o.value === dir.value);
      repoSel.value = hit ? hit.value : "";
      applyRepo(false);
    }
    if (repoSel) repoSel.addEventListener("change", () => { applyRepo(true); loadWorktrees(); if (other()) dir.focus(); });
    dir.addEventListener("input", () => { clearTimeout(dir._d); dir._d = setTimeout(dirCheck, 250); });
    // **Where** is worktree-first (§4.5a New session **the form**, TD-284 slice 4): a new worktree for a
    // registered git checkout, the checkout itself for *another directory…* and a shell; Name names
    // the worktree, and the repo's worktrees nobody is in are chips whose press takes its name
    const wtIn = $("[name=worktree]"), chips = $("#wtchips"), chipList = $("#wtchiplist");
    let free = [];
    function defaultWhere(git) {
      if (whereTouched) return;
      const want = !other() && !isShell() && git ? wt : here;
      if (!want.checked && !want.disabled) { want.checked = true; nameCheck(); }
    }
    // the worktree a Name makes is the server's `naming.slug` of it (`[a-z0-9-]`, 32 at most), so the
    // line shows that and the reuse is read on it; a chip's or a Resume's own name goes as it is
    const slugOf = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32).replace(/-+$/, "") || "x";
    function wtName() {
      const n = (wtIn && wtIn.value.trim()) || (nm.value.trim() ? slugOf(nm.value.trim()) : "<name>");
      $$("#wtname, .wtn").forEach((el) => { el.textContent = n; });
      const reuse = free.some((w) => w.name === n);
      const line = $("#wtline");
      if (line) line.dataset.reuse = reuse ? "1" : "";
      const r = $("#wtreuse");
      if (r) r.remove();
      if (reuse && line) line.insertAdjacentHTML("beforeend", `<span id="wtreuse"> · reuses the worktree <code>${esc(n)}</code></span>`);
    }
    let wseq = 0;
    async function loadWorktrees() {
      const my = ++wseq;
      if (other() || !dir.value.trim()) { free = []; chips.hidden = true; wtName(); return; }
      try {
        const o = await (await fetch(`/api/worktrees?repo=${encodeURIComponent(dir.value.trim())}${hq()}`)).json();
        if (my !== wseq) return;
        free = o.worktrees || [];
      } catch (e) { free = []; }
      chipList.innerHTML = free.map((w) => `<button type="button" class="btn sm ghost mono" data-wt="${esc(w.name)}" title="${esc(w.path)}">${esc(w.name)}</button>`).join("");
      chips.hidden = !free.length;
      wtName();
    }
    if (chipList) chipList.addEventListener("click", (e) => {
      const b = e.target.closest("[data-wt]"); if (!b) return;
      nm.value = b.dataset.wt; if (wtIn) wtIn.value = b.dataset.wt;  // reused as it is named, never re-slugged
      wt.checked = true; whereTouched = true;
      nm.dispatchEvent(new Event("change"));
    });
    nm.addEventListener("input", () => { if (wtIn) wtIn.value = ""; wtName(); });
    nm.addEventListener("change", wtName);
    for (const r of document.querySelectorAll("[name=where]")) r.addEventListener("change", () => { whereTouched = true; });
    dir.addEventListener("change", loadWorktrees);
    // a shell has no role, lane or brief: picking it hides them, and the occupancy rule exempts it (§9)
    function applyShell() {
      const sh = isShell();
      for (const f of ["#rolefield", "#lanefield", "#newchips"]) { const el = $(f); if (el) el.hidden = sh; }
      applyMode();
    }
    if (profSel) profSel.addEventListener("change", () => { applyShell(); check(); });
    let seq = 0;
    async function check() {
      const v = dir.value.trim(); const my = ++seq;
      if (!v) { note.textContent = ""; here.disabled = false; herechoice.classList.remove("taken"); inuse.hidden = true; dirBlocked = false; gate(); return; }
      try {
        const r = await fetch(`/api/occupancy?dir=${encodeURIComponent(v)}${hq()}`); const o = await r.json();
        if (my !== seq) return;
        if (o.why) {  // the picked host did not answer: said in the note's place, Start left to the create
          note.textContent = o.why; here.disabled = false; herechoice.classList.remove("taken"); inuse.hidden = true;
          dirBlocked = false; gate(); return;
        }
        // an occupied checkout is the Where choice greyed with who is in it, never a warning (TD-277):
        // the form has already picked the worktree; ⚠ only where Start is refused — an occupied
        // directory that is not a git repo has no worktree to go to (shells are exempt, §9)
        // …and a shell may share it (§9: shells never hold the slot), so for one it is only said
        const held = !!(o.occupants && o.occupants.length), taken = held && !isShell();
        here.disabled = taken; herechoice.classList.toggle("taken", taken);
        inuse.hidden = !held; inuse.textContent = held ? (o.seat || `in use by ${o.occupants.join(", ")}`) : "";  // a seat says so (TD-387)
        if (taken && o.git) { wt.checked = true; nameCheck(); }  // the scope moved to the repo
        else defaultWhere(o.git);
        dirBlocked = taken && !o.git;
        if (dirBlocked) note.innerHTML = `⚠ <b>in use</b> by ${esc(o.occupants.join(", "))} and not a git repo, so there is no worktree to start in — one agent session per directory (§9)`;
        else note.textContent = taken ? "a git repo: a new worktree is selected" : held ? "a shell may share the checkout" : o.git ? "free · a git repo, so a worktree is available" : (o.dir ? "free" : "");
        gate();
      } catch (e) { note.textContent = ""; here.disabled = false; dirBlocked = false; gate(); }
    }
    dir.addEventListener("input", () => { clearTimeout(dir._t); dir._t = setTimeout(check, 250); });
    dir.addEventListener("change", check);

    // Role presets and the Controllers prefill follow the directory (design §4.5a, §4.8 "Defaults
    // fill membership at launch"): the repo's `.shiftlead.yml` may redefine a preset or add one, and
    // name who may act on a session started there. The list is rebuilt from /api/roles as the
    // directory changes; the picker's ticks come from the role's `controllers:` when it has any,
    // else the repo's, and a person's untick after that is a decision the form keeps.
    const role = $("#role"), rnote = $("#rolenote"), picker = $("#controllers"), grants = $("#grants");
    let rseq = 0;
    function tickControllers(names) {
      for (const c of picker.querySelectorAll("[name=controller]")) c.checked = names.includes(c.dataset.name) || names.includes(c.value);
    }
    // design §4.5a New session **Grants** checkboxes: the preset's grants used to apply unseen.
    // Ticked from the role, so a person sees the one power in the system before pressing Start —
    // and an untick after that is a decision the form keeps, exactly as Controllers works.
    function tickGrants(names) {
      if (grants) for (const g of grants.querySelectorAll("[name=grant]")) g.checked = names.includes(g.value);
    }
    function applyRole() {
      const o = role.selectedOptions[0]; if (!o) return;
      const own = (o.dataset.controllers || "").split(",").filter(Boolean);
      tickControllers(own.length ? own : (picker.dataset.default || "").split(",").filter(Boolean));
      tickTeamManager();  // a picked team's manager stays ticked through the role's ticks (TD-296 #8)
      tickGrants((o.dataset.grants || "").split(",").filter(Boolean));
      $("[name=lane]").placeholder = o.dataset.lane || "free-pick or design-first · owner:<word>";
      // §4.5a *New session* **prompt chips** (TD-170): the role's saved prompts, as text
      const chips = $("#newchips");
      if (chips) {
        let ps = [];
        try { ps = JSON.parse(o.dataset.prompts || "[]"); } catch (e) { ps = []; }
        chips.innerHTML = ps.map((p, i) => `<button type="button" class="btn sm chip" data-i="${i}" title="${esc(p.text)}">${esc(p.label)}</button>`).join("");
        $$(".chip", chips).forEach((b) => b.addEventListener("click", () => {
          const t = $("[name=prompt]"); if (t) { t.value = ps[Number(b.dataset.i)].text; t.focus(); }
        }));
      }
    }
    async function loadRoles() {
      const v = dir.value.trim(); const my = ++rseq;
      try {
        const o = await (await fetch(`/api/roles?dir=${encodeURIComponent(v)}${hq()}`)).json();
        if (my !== rseq) return;
        const keep = role.value;
        role.innerHTML = `<option value="" data-interactive="1">Interactive</option>`;
        for (const r of o.roles) {
          const opt = document.createElement("option");
          opt.value = r.name; opt.dataset.lane = r.lane.join(", "); opt.dataset.controllers = r.controllers.join(",");
          opt.dataset.grants = (r.grants || []).join(",");
          opt.dataset.prompts = JSON.stringify(r.prompts || []);
          opt.textContent = `${r.name} · unattended`;
          opt.title = `${r.source}` + (r.grants.length ? ` · grants ${r.grants.join(", ")}` : "");
          role.appendChild(opt);
        }
        role.value = [...role.options].some((x) => x.value === keep) ? keep : "";
        picker.dataset.default = (o.controllers || []).join(",");
        rnote.textContent = o.error ? `⚠ ${o.error}` : (o.file ? `roles from ${o.file}` : "a role fills the brief, lane, grants and profile it names; each can be edited before Start");
        teamRoles();
        applyRole();
        applyMode();
      } catch (e) { /* the built-ins rendered with the page still stand */ }
    }
    role.addEventListener("change", applyRole);
    // **Role** decides the mode (§4.5a New session **the form**, TD-284 slice 5): *Interactive* is the
    // person's own; a role runs unattended unless the person says *run it under me instead*; a role in
    // *another directory…* runs under you only, and a shell has neither. The posted `unattended` is
    // this, and At and Until are drawn only for an unattended pick.
    const unIn = $("[name=unattended]"), when = $("#whenfields"), rmode = $("#rolemode");
    let underMe = !!(unIn && unIn.dataset.under);
    function applyMode() {
      if (!unIn) return;
      const o = role.selectedOptions[0], interactive = !o || !o.value, shell = isShell(), outside = other();
      const un = !interactive && !shell && !outside && !underMe;
      unIn.value = un ? "on" : "";
      applyMember();
      // hidden, At and Until post nothing: a time typed before the pick moved is not a refusal (review of #952)
      if (when) { when.hidden = !un; for (const i of when.querySelectorAll("input")) i.disabled = !un; }
      if (!rmode) return;
      if (shell) rmode.textContent = "";
      else if (interactive) rmode.textContent = "yours: never paused, sent to, or killed by a policy";
      else if (outside) rmode.textContent = "runs under you: a directory outside a registered repo has no unattended mode";
      else if (memberLines().length && !underMe) rmode.innerHTML = `a member of ${esc(teamSel.value)}: runs unattended, policies apply — <a href="#" data-mode="me">run it under me instead</a>`;
      else rmode.innerHTML = underMe
        ? `runs under you — <a href="#" data-mode="un">make it unattended</a>`
        : `runs unattended: policies apply — <a href="#" data-mode="me">run it under me instead</a>`;
    }
    // New session's **member line** fill + **keep as a team member** (design §4.5a, §4.9 *A member started
    // from the form*, TD-1167): under a Team pick, a Role one of its member lines names fills the form from
    // that line as `ao team start` creates its next member (`/api/team_line`), and Start posts `line`, which
    // the server starts through `ao team add`'s road — a run-only member, or ticked, the line's **+**. A role
    // with two lines offers each by its name; a team not running refuses Start and offers the team's Start.
    const memberField = $("#memberfield"), linePick = $("#linepick"), lineIn = $("[name=line]");
    const keepIn = $("#keep"), mnote = $("#membernote");
    const laneIn = $("[name=lane]"), promptIn = $("[name=prompt]");
    let lineKey = "", lineGot = null, lseq = 0;
    function memberLines() {
      const o = teamSel && teamSel.selectedOptions[0];
      // *another directory…* runs under you only, and a Resume is its record's: neither starts a member
      const res = $("[name=resume]");
      if (!o || !o.value || !role.value || isShell() || other() || (res && res.value.trim())) return [];
      let ls = [];
      try { ls = JSON.parse(o.dataset.lines || "[]"); } catch (e) { ls = []; }
      return ls.filter((l) => l.role === role.value);
    }
    function lockLine(on) {
      // a kept member is the line's (§4.9): named and filled from it alone, so its fields are drawn locked
      for (const el of [nm, laneIn, promptIn]) if (el) el.readOnly = on;
      if (profSel) profSel.disabled = on;
    }
    function memberNote() {
      if (!mnote) return;
      const team = teamSel.value, why = lineGot ? (lineGot.why || lineGot.not_running) : "";
      memberBlocked = !!why;
      if (why) mnote.innerHTML = `⚠ <b>${esc(why)}</b>` + (lineGot.not_running && !lineGot.why ? ` <button type="button" class="btn sm" id="memberteamstart">Start ${esc(team)}</button>` : "");
      else if (keepIn && keepIn.checked) mnote.textContent = "a kept member is the line's: change the line in the definition";
      else if (lineGot) mnote.textContent = `the line's next member, for this run: it ends with ${team}'s run and is never replayed`;
      else mnote.textContent = "";
      gate();
    }
    async function loadLine(team, line) {
      const my = ++lseq;
      lineGot = null; memberNote(); memberBlocked = true; gate();  // Start waits for the line's reading
      let got = { why: `${team} did not answer` };
      try { got = await (await fetch(`/api/team_line?team=${encodeURIComponent(team)}&line=${encodeURIComponent(line)}`)).json(); } catch (e) { /* said below */ }
      if (my !== lseq) return;
      lineGot = got;
      if (!got.why) {
        nm.value = got.name || nm.value;
        if (profSel) profSel.value = [...profSel.options].some((x) => x.value === got.profile) ? got.profile : "";
        if (laneIn) laneIn.value = (got.lane || []).join(", ");
        if (promptIn) promptIn.value = got.prompt || "";
        tickGrants(got.grants || []);
        nm.dispatchEvent(new Event("change"));
      }
      memberNote();
    }
    function applyMember() {
      if (!memberField) return;
      const ls = underMe ? [] : memberLines();
      memberField.hidden = !ls.length;
      if (!ls.length) {
        lineIn.value = ""; lineKey = ""; lineGot = null; lseq++;
        lockLine(false); memberBlocked = false; gate();
        return;
      }
      const keep = [...linePick.options].map((x) => x.value).join(",") === ls.map((l) => l.line).join(",") ? linePick.value : ls[0].line;
      linePick.innerHTML = ls.map((l) => `<option value="${esc(l.line)}">${esc(l.role)} · ${esc(l.line)}</option>`).join("");
      linePick.value = keep; linePick.hidden = ls.length < 2;
      lineIn.value = linePick.value;
      lockLine(!!(keepIn && keepIn.checked));
      const key = `${teamSel.value}|${lineIn.value}`;
      if (key !== lineKey) { lineKey = key; loadLine(teamSel.value, lineIn.value); } else memberNote();
    }
    if (linePick) linePick.addEventListener("change", applyMember);
    if (keepIn) keepIn.addEventListener("change", applyMember);
    if (mnote) mnote.addEventListener("click", async (e) => {
      const b = e.target.closest("#memberteamstart"); if (!b) return;
      const team = teamSel.value; b.disabled = true;
      try {
        const r = await fetch(`/api/teams/${encodeURIComponent(team)}/start`, { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
        let o = {}; try { o = await r.json(); } catch (x) { o = {}; }
        if (!r.ok) { mnote.innerHTML = `⚠ <b>${esc(o.detail || r.statusText)}</b>`; return; }
        lineKey = ""; applyMember();  // the line read again: the team's run now holds the member
      } catch (x) { b.disabled = false; }
    });
    if (rmode) rmode.addEventListener("click", (e) => {
      const a = e.target.closest("[data-mode]"); if (!a) return;
      e.preventDefault(); underMe = a.dataset.mode === "me"; applyMode();
    });
    role.addEventListener("change", () => { if (teamSel && teamSel.value) underMe = !memberLines().length; applyMode(); });
    dir.addEventListener("change", loadRoles);
    dir.addEventListener("input", () => { clearTimeout(dir._r); dir._r = setTimeout(loadRoles, 400); });

    // One name, one session (design §4.1, §9 invariant 12): say what Start would do before it is
    // pressed — a live holder is a refusal, so offer Switch to instead; an exited one is replaced
    // and its run log kept. Same texts as `ao new` prints: the agent composes them (TD-030).
    let nseq = 0;
    async function nameCheck() {
      const mine = ++nseq, n = nm.value.trim(), d = dir.value.trim();
      const worktree = $("[name=where][value=worktree]").checked;
      if (!n || !d) { nnote.textContent = ""; nameBlocked = false; gate(); return; }
      try {
        const q = `dir=${encodeURIComponent(d)}&name=${encodeURIComponent(n)}&worktree=${worktree}`
          + (away() ? `&host=${encodeURIComponent(hostSel.value)}` : "");
        const o = await (await fetch(`/api/name_check?${q}`)).json();
        if (mine !== nseq) return;
        nameBlocked = o.verdict === "live"; gate();
        if (o.verdict === "live") {
          const to = o.holder_state === "unrecorded" ? "" : ` <a class="btn sm primary" href="/focus/${encodeURIComponent(o.holder)}">Switch to</a>`;
          nnote.innerHTML = `⚠ <b>${esc(o.message)}</b>${to}`;
        } else if (o.verdict === "suspended") {
          // design §4.8a *An alarm's answers* (TD-077 a2): **a person's create is the lift**, which
          // is why Start stays enabled here where a `live` holder disables it. The agent's own
          // sentence is printed as it wrote it — the why, the when and the two ways out are all in
          // it, and a page that recomposed them from parts is how two surfaces come to say
          // different things about one record. The frame is all this adds: what pressing Start does.
          nnote.innerHTML = `⚠ <b>${esc(o.message)}</b><br>Starting it here <b>lifts the suspension</b>`
            + ` — that is a person's act, and yours.${o.holder ? ` <a class="btn sm" href="/focus/${encodeURIComponent(o.holder)}">Look at it first</a>` : ""}`;
        } else nnote.innerHTML = o.verdict === "supersede" ? esc(o.message) : "";
      } catch (e) { nnote.textContent = ""; nameBlocked = false; gate(); }
    }
    nm.addEventListener("input", () => { clearTimeout(nm._t); nm._t = setTimeout(nameCheck, 250); });
    nm.addEventListener("change", nameCheck);
    dir.addEventListener("change", nameCheck);
    for (const r of document.querySelectorAll("[name=where]")) r.addEventListener("change", nameCheck);
    // a Host change re-reads every reading: the Repo list first — a Repo the new host does not list is
    // cleared to its first, or to *another directory…* — then all that follow the directory (TD-294)
    const rnoteRepo = $("#reponote");
    let hseq = 0;
    async function loadRepos() {
      if (!repoSel) return;
      const my = ++hseq, h = hostSel.value;
      let o = { repos: [], why: "" };
      try { o = await (await fetch(`/api/repos?host=${encodeURIComponent(h)}`)).json(); } catch (e) { o = { repos: [], why: `${h} did not answer` }; }
      if (my !== hseq) return;
      const last = [...repoSel.options].find((x) => x.dataset.other), cur = repoSel.value;
      for (const x of [...repoSel.options]) if (!x.dataset.other) x.remove();
      for (const r of o.repos) {
        const opt = document.createElement("option");
        opt.value = r.path; opt.dataset.name = r.name; opt.textContent = `${r.name} · ${r.path}`;
        repoSel.insertBefore(opt, last);
      }
      if (rnoteRepo) rnoteRepo.innerHTML = o.why ? `⚠ ${esc(o.why)}: type the directory`
        : o.repos.length ? `a registered checkout on ${esc(o.host || h)}. The list ends with <i>another directory…</i> — a typed path, for a shell or a directory outside any repo`
        : `no repo is registered on ${esc(o.host || h)}: type the directory`;
      // the choice kept is the one picked, else the directory set for the person (a Team's checkout)
      const want = [cur, dir.value.trim()].find((p) => p && o.repos.some((r) => r.path === p));
      // a typed directory stays typed: *another directory…* is kept rather than replaced by a repo
      const typed = !cur && !!dir.value.trim();
      repoSel.value = want || (typed || !o.repos.length ? "" : o.repos[0].path);
      narrowRepos();
      applyRepo(false);
      dir.dispatchEvent(new Event("change"));  // the occupancy, the roles, the chips, the name, the team line
    }
    if (hostSel) hostSel.addEventListener("change", () => { gate(); loadRepos(); });
    // The Directory list's suggestions: the registered repos and recent directories, which a Team pick
    // narrows to its checkouts and *none* restores
    const datalist = $("#recent");
    const allDirs = $$("option", datalist).map((o) => o.value);
    const options = (vals) => (datalist.innerHTML = vals.map((v) => `<option value="${esc(v)}">`).join(""));

    // The Team picker (design §4.5a New session **Team**, §4.9 *A person in the team*, TD-173):
    // the team's checkouts in the Directory list, Role narrowed to its roles plus `plain`, its live
    // manager ticked under Controllers, a role started under you, and the reader its held PRs get — the
    // one line /api/team_review answers for the team and the directory. "none" undoes all but the
    // ticks, which are the person's by then.
    const teamSel = $("#team"), tnote = $("#teamnote");
    const TNOTE = tnote ? tnote.textContent : "";
    let tseq = 0;
    function teamRoles() {
      const o = teamSel && teamSel.selectedOptions[0];
      const keep = o && o.value ? ["", "plain", ...(o.dataset.roles || "").split(",").filter(Boolean)] : null;
      for (const r of role.options) r.hidden = !!keep && !keep.includes(r.value);
      if (keep && !keep.includes(role.value)) { role.value = ""; applyRole(); applyMode(); }
    }
    async function teamLine() {
      const o = teamSel.selectedOptions[0]; const my = ++tseq;
      if (!o || !o.value) { tnote.textContent = TNOTE; return; }
      try {
        const got = await (await fetch(`/api/team_review?team=${encodeURIComponent(o.value)}&dir=${encodeURIComponent(dir.value.trim())}${hq()}`)).json();
        if (my === tseq) tnote.textContent = got.line || TNOTE;
      } catch (e) { /* the default note stands */ }
    }
    // the picked team's manager ticked under Controllers (§4.5a New session **Team**). `applyRole` calls
    // it too, since the roles a Team pick reloads re-tick the role's controllers after the pick
    // (TD-296 #8: the async `loadRoles` cleared the tick `applyTeam` had just set)
    function tickTeamManager() {
      const o = teamSel && teamSel.selectedOptions[0];
      if (o && o.value && o.dataset.manager) for (const c of picker.querySelectorAll("[name=controller]")) if (c.value === o.dataset.manager) c.checked = true;
    }
    function applyTeam() {
      if (!teamSel) return;
      const o = teamSel.selectedOptions[0];
      if (o && o.value) {
        let dirs = [];
        try { dirs = JSON.parse(o.dataset.dirs || "[]"); } catch (e) { dirs = []; }
        options(dirs); narrowRepos();
        if (!dirs.includes(dir.value.trim()) && dirs.length) { dir.value = dirs[0]; syncRepo(); check(); loadRoles(); nameCheck(); }
        tickTeamManager();
        // the team's host is the Host pick's (§4.5a New session **the form**), when it is one to pick
        if (hostSel && o.dataset.host && [...hostSel.options].some((x) => x.value === o.dataset.host && !x.disabled)) {
          if (hostSel.value !== o.dataset.host) { hostSel.value = o.dataset.host; gate(); loadRepos(); }
        }
        // a role a member line names starts a member (TD-1167); any other a person's own session in the team (§4.9)
        underMe = !memberLines().length; applyMode();
      } else { underMe = false; options(allDirs); narrowRepos(); applyMode(); }  // *none*: a role is presumed unattended again
      teamRoles();
      teamLine();
    }
    if (teamSel) { teamSel.addEventListener("change", applyTeam); dir.addEventListener("change", teamLine); }

    applyShell();  // a Resume with changes… of a shell lands with the shell picked
    applyRepo(false);  // the page drew the pick; the typed path is checked once if it is the one
    loadWorktrees();
    check();  // both once at load: a prefilled directory and a prefilled name are checked too
    nameCheck();
    applyRole();  // the ticks the page rendered are the repo's; a role picked later may narrow them
    if (teamSel && teamSel.value) applyTeam();  // a prefilled team (a Resume of a team's session)
  };

  // ---- Focus ----
  // The rail's glyphs (§4.5 *The panel put away*, TD-412): one per side card that has something to
  // say, in the panel's order — `card` is the `data-side` a press opens ("" for needs-you, whose
  // prompt is the identity line's, never the panel's), `title` the card's heading and its line.
  AO.railGlyphs = function (v, ready, inboxN, lines, editor) {
    const g = [], ln = lines || {};
    if (v.state === "needs-you") g.push({ card: "", text: "!", title: "Needs you — the prompt is on the identity line" });
    if (v.doing && v.doing.text) g.push({ card: "working", text: "✎", title: `Working — ${v.doing.text}` });
    const reports = (v.progress || []).length + (v.findings || []).length;
    if (reports) g.push({ card: "reports", text: String(reports), title: `Reports — ${ln.reports || reports}` });
    if (inboxN) g.push({ card: "inbox", text: String(inboxN), title: `Inbox — ${ln.inbox || inboxN}` });
    if (ready) g.push({ card: "ready", text: "✓", title: "Ready to close — every check passes" });
    // last, the editor button whenever the Session card draws it (TD-525): its press opens the
    // worktree as the button does, so it carries the button's `href` and brings no card back
    if (editor && editor.url) g.push({ card: "editor", text: "‹›", title: `${editor.label} — opens the worktree`, href: editor.url, label: editor.label });
    return g;
  };
  // …drawn: a button that opens its card, or for **‹›** the editor's link, opened by the `a.editor`
  // handler as the Session card's button is (TD-525)
  AO.railHtml = function (v, ready, inboxN, lines, editor) {
    return AO.railGlyphs(v, ready, inboxN, lines, editor)
      .map((x) => x.href
        ? `<a class="railbtn editor g-${x.card}" href="${esc(x.href)}" data-label="${esc(x.label)}" title="${esc(x.title)}">${esc(x.text)}</a>`
        : `<button class="railbtn g-${x.card || "needs"}" type="button" data-rail="${x.card}" title="${esc(x.title)}">${esc(x.text)}</button>`)
      .join("");
  };
  // **» put away** / **«** and the glyphs (§4.5a, TD-412): `side` gains `rail` and the choice is
  // remembered per browser as `focus.side`, the key the template's inline script reads before the
  // first paint; a glyph brings the panel back with its card open — `card(name)` finds the fold,
  // and opening it writes the fold's key as a click would.
  AO.wireRail = function ({ side, away, back, glyphs, card }) {
    const putAway = (on) => { side.classList.toggle("rail", on); store.set("focus.side", on ? "away" : null); };
    away.addEventListener("click", () => putAway(true));
    back.addEventListener("click", () => putAway(false));
    glyphs.addEventListener("click", (e) => {
      const b = e.target.closest("[data-rail]"); if (!b) return;
      putAway(false);
      const d = b.dataset.rail ? card(b.dataset.rail) : null;
      if (d) { d.open = true; d.scrollIntoView({ block: "nearest" }); }
    });
  };
  // **a URL is a link** (§4.6 *A URL in the pane is a link*, §4.5a, TD-422): the web-links addon
  // calls this on any click of a URL it underlined, so the modifier is the gate — a plain click
  // falls through to the selection — and only http and https open, whatever the addon's regex took.
  AO.paneLink = function (event, uri, open) {
    if (!(event && (event.ctrlKey || event.metaKey))) return false;
    let scheme;
    try { scheme = new URL(uri).protocol; } catch (e) { return false; }
    if (scheme !== "http:" && scheme !== "https:") return false;
    (open || window.open)(uri, "_blank", "noopener");
    return true;
  };
  // **a hyperlink is a link** (§4.6 *A hyperlink in the pane is a link*, §4.5a, TD-847): xterm's
  // OSC 8 provider hands a label's hidden target here, the bridge's attach having asked tmux for
  // `hyperlinks`. `activate` wraps `AO.paneLink`, which would take xterm's third argument (the
  // range) as its `open`; hover shows the target, since the label does not. The provider itself
  // drops any target that is not http or https (`allowNonHttpProtocols` stays unset), and
  // `AO.paneLink` checks again.
  AO.paneLinkHandler = function (el) {
    return {
      activate: (e, uri) => AO.paneLink(e, uri),
      hover: (e, uri) => { el.title = uri; },
      leave: () => { el.title = ""; },
    };
  };
  // **a path is a link** (§4.6 *A path in the pane is a link*, §4.5a, TD-501): the runs one row of
  // the pane names that could be a file — a run with a `/` in it, relative, `./`, `~/` or absolute,
  // with an optional `:line` or `:line:col`, the bracket or sentence stop at its tail cut off; a run
  // inside a URL is the URL's. A segment takes any letter, mark or digit and `_.@+-`; one after the
  // first `/` takes `#`, `,` and `=` too, so `--file=src/a.py` is still `src/a.py` (TD-1262). A run
  // holding one of those is followed by its pieces without them (`a/b.py,c/d.py`, `src/a.py#L12`), in
  // order of start, so the first the host resolves is the link. Each is `{run, path, line, col, start,
  // end}`, `start`/`end` the run's columns in the row's text (end exclusive). The shape only asks: the
  // host says which are files.
  AO.pathRuns = function (text) {
    const urls = [];
    for (const m of String(text).matchAll(/[A-Za-z][A-Za-z0-9+.-]*:\/\/\S+/g)) urls.push([m.index, m.index + m[0].length]);
    const seg = "[\\p{L}\\p{M}\\p{N}_.@+-]";
    const wide = new RegExp(`(?:~|\\.{1,2})?\\/?${seg}+(?:\\/[\\p{L}\\p{M}\\p{N}_.@+#,=-]+)+(?::\\d+(?::\\d+)?)?`, "gu");
    const narrow = new RegExp(`(?:~|\\.{1,2})?\\/?${seg}+(?:\\/${seg}+)+(?::\\d+(?::\\d+)?)?`, "gu");
    const scan = (s, re, base) => {
      const got = [];
      for (const m of s.matchAll(re)) {
        const start = base + m.index;
        let run = m[0];
        if (urls.some(([a, b]) => start < b && start + run.length > a)) continue;
        const lc = run.match(/:(\d+)(?::(\d+))?$/);
        let path = lc ? run.slice(0, lc.index) : run;
        if (!lc) { path = path.replace(/[.,;:)\]}'"]+$/, ""); run = path; }
        if (!path.includes("/") || /^\.*\/*$/.test(path) || path.length > 512) continue;  // the read's bound
        got.push({ run, path, line: lc ? +lc[1] : null, col: lc && lc[2] ? +lc[2] : null, start, end: start + run.length });
      }
      return got;
    };
    const out = [];
    for (const r of scan(String(text), wide, 0)) {
      out.push(r);
      if (!/[#,=]/.test(r.run)) continue;
      out.push(...scan(r.run, narrow, r.start).filter((p) => p.run !== r.run).map((p) => ({ ...p, piece: true })));
    }
    return out;
  };
  // …and the press, `AO.paneLink`'s shape: no modifier, nothing; else the editor's file form filled
  // with the host's resolved path, percent-encoded with `/` kept (§5, TD-011), and handed to the
  // protocol handler after the session's folder (`AO.openFile`, TD-535). On every `vscode` form — a `vscode://` URL that
  // ends at `{path}`: local, ssh-remote, container — the line rides after the path, `:line[:col]` as
  // printed and `:1` where none was, since VS Code opens a remote path as a file only when it ends in
  // `:digits` (TD-524, TD-526); a template's `{line}` takes the line (`1` where none was) and a
  // template without it is filled as it stands.
  AO.fileUrl = function (file, resolved, line, col) {
    const path = String(resolved).split("/").map(encodeURIComponent).join("/");
    const vscode = file.startsWith("vscode://") && file.endsWith("{path}");
    const at = vscode ? `:${line || 1}${line && col ? `:${col}` : ""}` : "";
    return file.replace("{path}", path + at).replaceAll("{line}", String(line || 1));
  };
  AO.pathLink = function (event, editor, resolved, line, col, open) {
    const file = editor && editor.file;
    if (!(event && (event.ctrlKey || event.metaKey)) || !file || !resolved) return false;
    AO.openFile(editor, AO.fileUrl(file, resolved, line, col), open);
    return true;
  };
  // **A path in a transcript is a link too** (§4.6, §4.5a *Transcript*, TD-691): the pane's shape
  // (`AO.pathRuns`) over a turn's text, a tool line's input and a tool result's text, the same `paths`
  // read, the same press. The asker keeps one ask in flight and each run's answer for the page's life,
  // eight runs at most per ask, so a path met twice is asked once; a failed ask, or a run the answer
  // leaves out, keeps nothing.
  AO.TRANSCRIPT_TEXT = ".ttext, .targ, .tbody";
  AO.pathsAsker = function (ask) {
    const known = new Map();
    let chain = Promise.resolve();
    const run = (paths) => {
      const want = [...new Set(paths)].filter((p) => !known.has(p));
      let step = Promise.resolve();
      for (let i = 0; i < want.length; i += 8) {
        const batch = want.slice(i, i + 8);
        step = step.then(() => ask(batch)).then((got) => {
          const ans = (got && got.paths) || {};
          batch.forEach((p) => { if (p in ans) known.set(p, ans[p] || null); });  // a run left out is asked again
        });
      }
      return step.catch(() => {}).then(() => Object.fromEntries(paths.filter((p) => known.get(p)).map((p) => [p, known.get(p)])));
    };
    return {
      resolve(paths) { const p = chain.then(() => run(paths)); chain = p; return p; },
      // what is known already, asking nothing: a row a poll redrew is relinked from it (TD-1108)
      cached(paths) { return Object.fromEntries(paths.filter((p) => known.get(p)).map((p) => [p, known.get(p)])); },
    };
  };
  // …a text with each resolved run an `a.editor` the click handler opens on Ctrl or Cmd alone
  // (`data-ctrl`), the session's folder first as the recent files' links, the rest escaped text
  AO.pathLinksHtml = function (text, paths, editor) {
    const s = String(text), label = editor.label || "the editor";
    const folder = editor.url ? ` data-folder="${esc(editor.url)}"${typeof editor.wait === "number" ? ` data-wait="${editor.wait}"` : ""}` : "";
    let out = "", at = 0;
    for (const r of AO.pathRuns(s)) {
      const to = paths[r.path];
      if (!to || r.start < at) continue;
      out += esc(s.slice(at, r.start)) + `<a class="editor tpath" data-ctrl href="${esc(AO.fileUrl(editor.file, to, r.line, r.col))}"${folder}`
        + ` data-label="${esc(label)}" title="${esc(`Ctrl+click: ${to} in ${label}`)}">${esc(r.run)}</a>`;
      at = r.end;
    }
    return out + esc(s.slice(at));
  };
  // …a turn block, on its first hover: asked once, whatever the answer; the texts holding a resolved run redrawn
  AO.transcriptBlock = function (block, asker, editor) {
    if (!block || block.dataset.paths) return null;
    block.dataset.paths = "asked";
    const els = [...block.querySelectorAll(AO.TRANSCRIPT_TEXT)];
    const runs = els.map((el) => AO.pathRuns(el.textContent));
    const paths = [...new Set(runs.flat().map((r) => r.path))];
    if (!paths.length) return null;
    return asker.resolve(paths).then((got) => {
      els.forEach((el, i) => { if (runs[i].some((r) => got[r.path])) el.innerHTML = AO.pathLinksHtml(el.textContent, got, editor); });
    });
  };
  // **A path in the Inbox and the Queue is a link too** (§4.6, §4.5a, TD-1108): the texts `AO.ITEM_TEXT` names
  // in a row the server gave a context (`data-paths-ctx`: `id:<record>`, `repo:<root>` or `home`), asked of
  // `POST /api/paths` on the row's first hover by one asker per context, kept for the page's life. A context
  // the route refused, or whose first answer has no file form, goes quiet: every later batch answers `null`
  // with no fetch. The answer's `file`, `label` and `wait` are kept from the first answer.
  AO.ITEM_TEXT = ".body, .boardreply";
  const itemAskers = new Map();
  AO.itemAsker = function (ctx) {
    if (itemAskers.has(ctx)) return itemAskers.get(ctx);
    const meta = { file: null, label: "", wait: undefined, answered: false, quiet: false };
    const asker = AO.pathsAsker(async (runs) => {
      if (meta.quiet) return { paths: Object.fromEntries(runs.map((r) => [r, null])) };
      const r = await fetch("/api/paths", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ runs, ctx }),
      });
      if (!r.ok) throw new Error(String(r.status));  // nothing cached: the next hover of a new row asks again
      const got = await r.json();
      if (!meta.answered) {
        meta.answered = true;
        Object.assign(meta, { file: got.file || null, label: got.label || "", wait: got.wait });
        if (!got.file) meta.quiet = true;
      }
      if (got.refused) meta.quiet = true;
      return got;
    });
    const one = { asker, meta };
    itemAskers.set(ctx, one);
    return one;
  };
  // …each answered run in an element's text nodes an `a.editor` the click handler opens on Ctrl or Cmd,
  // the node split around it, so `<code>`, `<b>` and links stay; nothing under an `a`, a `button` or a
  // `summary` (a Read line's plain click opens its item), and nothing redrawn from `textContent`
  AO.linkItemText = function (el, got, meta) {
    if (!el || !meta.file || (el.closest && el.closest("a, button, summary"))) return;
    const doc = el.ownerDocument || document, label = meta.label || "the editor";
    const split = (t) => {
      const s = String(t.nodeValue), parent = t.parentNode;
      let at = 0;
      for (const r of AO.pathRuns(s)) {
        const to = got[r.path];
        if (!to || r.start < at) continue;
        if (r.start > at) parent.insertBefore(doc.createTextNode(s.slice(at, r.start)), t);
        const a = doc.createElement("a");
        a.className = "editor tpath";
        a.setAttribute("data-ctrl", "");
        a.setAttribute("href", AO.fileUrl(meta.file, to.path, r.line, r.col));
        a.setAttribute("data-label", label);
        a.setAttribute("title", `Ctrl+click: ${to.path} in ${label}`);
        if (to.folder) {
          a.setAttribute("data-folder", to.folder);
          if (typeof meta.wait === "number") a.setAttribute("data-wait", String(meta.wait));
        }
        a.textContent = r.run;
        parent.insertBefore(a, t);
        at = r.end;
      }
      if (!at) return;
      if (at < s.length) parent.insertBefore(doc.createTextNode(s.slice(at)), t);
      parent.removeChild(t);
    };
    const walk = (n) => Array.from(n.childNodes || []).forEach((c) => {
      if (c.nodeType === 3) split(c);
      else if (c.nodeType === 1 && !/^(A|BUTTON|SUMMARY)$/i.test(c.nodeName)) walk(c);
    });
    walk(el);
  };
  // …the texts under `box` (a row, or a fold's body inside one), their runs asked — or, `cacheOnly`, read
  // from what the row's context already knows — and linked
  AO.linkItem = function (row, box, cacheOnly) {
    const ctx = row && row.dataset && row.dataset.pathsCtx;
    if (!ctx || (cacheOnly && !itemAskers.has(ctx))) return null;
    const els = [...(box || row).querySelectorAll(AO.ITEM_TEXT)];
    const paths = [...new Set(els.flatMap((el) => AO.pathRuns(el.textContent).map((r) => r.path)))];
    if (!paths.length) return null;
    const { asker, meta } = AO.itemAsker(ctx);
    const link = (got) => els.forEach((el) => AO.linkItemText(el, got, meta));
    if (cacheOnly) { link(asker.cached(paths)); return null; }
    return asker.resolve(paths).then(link);
  };
  // …a row's first hover asks, once, whatever the answer
  AO.askItem = function (row) {
    if (!row || !row.dataset || row.dataset.pathsAsked) return null;
    row.dataset.pathsAsked = "1";
    return AO.linkItem(row, row, false);
  };
  document.addEventListener?.("mouseover", (ev) => {
    const row = ev.target && ev.target.closest && ev.target.closest(".mailrow[data-paths-ctx]");
    if (row) AO.askItem(row);
  });
  // The Session card's **recent files** (§4.5 item 4, §4.5a, TD-525): the record's `files`, newest
  // first, each drawn relative to the session's directory (else its repo) with the absolute path and
  // its time on hover — the file's, or the commit's and its short sha (TD-538) — **M** before one
  // `git.files` holds (its porcelain lines, relative to the worktree), and a link by the editor's file
  // form at line 1 — the `a.editor` handler opens it on a
  // plain click, after the session's folder unless the person turned that off (`editor.first`, TD-536).
  // No file form, no links: the paths are text. "" when the work has changed nothing.
  AO.recentFiles = function (v, editor) {
    const files = v.files || [];
    if (!files.length) return "";
    const under = (p, root) => (root && p.startsWith(root.replace(/\/+$/, "") + "/") ? p.slice(root.replace(/\/+$/, "").length + 1) : null);
    // a porcelain path is relative to the worktree's root, which is the directory or above it
    const changed = ((v.git && v.git.files) || []).map((f) => String(f).slice(String(f).indexOf(" ") + 1));
    const dir = String(v.dir || "").replace(/\/+$/, "") + "/";
    const isChanged = (p) => changed.some((c) => p.endsWith("/" + c) && dir.startsWith(p.slice(0, p.length - c.length)));
    const file = editor && editor.file;
    const folder = editor && editor.url && editor.first !== false
      ? ` data-folder="${esc(editor.url)}"${typeof editor.wait === "number" ? ` data-wait="${editor.wait}"` : ""}` : "";
    return files.map((f) => {
      const p = String(f.path || ""), rel = under(p, v.dir) ?? under(p, v.repo) ?? p;
      const mark = v.dir && isChanged(p) ? '<span class="fmark" title="changed in the worktree">M</span> ' : "";
      // the time the file's own for one uncommitted, the commit's and its short sha for one committed (§4.5a)
      const when = f.at ? `${String(f.at).slice(0, 16).replace("T", " ")}Z` : "";
      const title = esc(`${p}${f.sha ? ` — committed ${String(f.sha).slice(0, 7)} ${when}` : when ? ` — edited ${when}` : ""}`);
      const name = file
        ? `<a class="editor" href="${esc(AO.fileUrl(file, p, 1))}"${folder} data-label="${esc(editor.label || "the editor")}" title="${title}">${esc(rel)}</a>`
        : `<span title="${title}">${esc(rel)}</span>`;
      return `<div>${mark}${name}</div>`;
    }).join("");
  };
  // The Git card's **changed files** (§4.5a *Focus side panel, Git card: changed files*, TD-627, built
  // by TD-628): `git.files`' lines in their order, the status code as text and the path a link by the
  // recent files' form — the porcelain path joined to the worktree's top level (`root`, which the page
  // was served; the directory where it was not), no line. A deletion (a code ending in `D`) and a new
  // directory (`dir/`) stay text, with why on hover; no file form, every line text. "clean" for none.
  AO.gitFiles = function (v, editor, root) {
    const lines = (v.git && v.git.files) || [];
    if (!lines.length) return '<div class="muted">clean</div>';
    const file = editor && editor.file;
    const folder = editor && editor.url && editor.first !== false
      ? ` data-folder="${esc(editor.url)}"${typeof editor.wait === "number" ? ` data-wait="${editor.wait}"` : ""}` : "";
    const top = String(root || v.dir || "").replace(/\/+$/, "");
    return lines.map((f) => {
      const line = String(f), at = line.indexOf(" ");
      const code = at < 0 ? "" : line.slice(0, at), p = at < 0 ? line : line.slice(at + 1);
      const why = code.endsWith("D") ? "deleted in the worktree"
        : p.endsWith("/") ? "a new directory: open it from the worktree's window" : "";
      if (!file || !top || why) return `<div>${esc(code)} <span${why && file ? ` title="${esc(why)}"` : ""}>${esc(p)}</span></div>`;
      const full = `${top}/${p}`;
      return `<div>${esc(code)} <a class="editor" href="${esc(AO.fileUrl(file, full))}"${folder} data-label="${esc(editor.label || "the editor")}" title="${esc(full)}">${esc(p)}</a></div>`;
    }).join("");
  };
  // The Git card's **pick** (§4.5a *Focus side panel, Git card: the pick · ↑ · ↓*, §4.2 *The Git card's
  // pick*, TD-856, built by TD-862): the select's entries in order — `tree`, the ten commits' shas, `session`
  // — and its options, each commit *HEAD · 1a2b3c4 · subject* cut at forty, whole on hover.
  AO.gitPickEntries = (commits) => ["tree", ...(commits || []).map((c) => c.sha), "session"];
  AO.gitPickOptions = function (commits, pick) {
    const opt = (value, text, title) =>
      `<option value="${esc(value)}"${value === pick ? " selected" : ""}${title ? ` title="${esc(title)}"` : ""}>${esc(text)}</option>`;
    return opt("tree", "Working tree") + (commits || []).map((c) => {
      const subject = String(c.subject || ""), cut = subject.length > 40 ? `${subject.slice(0, 40)}…` : subject;
      return opt(c.sha, `${c.ref} · ${String(c.sha).slice(0, 7)} · ${cut}`, subject);
    }).join("") + opt("session", "Session");
  };
  // A held pick after the commits were read again: a sha still among the ten keeps its lines (relabelled by
  // the options), one gone — a rebase, an amend, ten commits more — goes back to Working tree.
  AO.gitPickHeld = (commits, pick) => (AO.gitPickEntries(commits).includes(pick) ? pick : "tree");
  // ↑ newer, ↓ older, each stopping at its end: what is listed steps, never a line in the list.
  AO.gitPickStep = function (commits, pick, by) {
    const all = AO.gitPickEntries(commits), at = Math.max(0, all.indexOf(pick));
    return all[Math.min(all.length - 1, Math.max(0, at + by))];
  };
  // A commit's naming line: short sha, subject and age, the full subject and the author on hover.
  AO.gitPickNaming = function (c) {
    if (!c) return "";
    const title = `${c.subject || ""}${c.author ? ` — ${c.author}` : ""}`;
    return `<span title="${esc(title)}">${esc(String(c.sha).slice(0, 7))} · ${esc(c.subject || "")}${c.at ? ` · ${esc(fmtAge(c.at))} ago` : ""}</span>`;
  };
  // A commit's or Session's lines, `{code, path, gone}` from the read: git's letter and the path, a link by
  // *changed files*' form where that row draws one; text where there is nothing to open — a `D` and a path
  // the read marks `gone` — with why on hover; Session's *n more* past the hundred.
  AO.gitPickLines = function (answer, pick, editor, root) {
    const files = (answer && answer.files) || [];
    const more = pick === "session" && answer && answer.more ? `<div class="muted">${answer.more} more</div>` : "";
    if (!files.length) return (more || '<div class="muted">nothing</div>');
    const file = editor && editor.file;
    const folder = editor && editor.url && editor.first !== false
      ? ` data-folder="${esc(editor.url)}"${typeof editor.wait === "number" ? ` data-wait="${editor.wait}"` : ""}` : "";
    const top = String(root || "").replace(/\/+$/, "");
    return files.map((f) => {
      const code = String(f.code || ""), p = String(f.path || "");
      const why = code === "D" ? (pick === "session" ? "deleted since the base" : "deleted by this commit")
        : f.gone ? "not in the worktree now" : "";
      if (!file || !top || why) return `<div>${esc(code)} <span${why ? ` title="${esc(why)}"` : ""}>${esc(p)}</span></div>`;
      const full = `${top}/${p}`;
      return `<div>${esc(code)} <a class="editor" href="${esc(AO.fileUrl(file, full))}"${folder} data-label="${esc(editor.label || "the editor")}" title="${esc(full)}">${esc(p)}</a></div>`;
    }).join("") + more;
  };
  // The card's glue: the commits read on load and again when `git.oid` moves; a commit's lines on its pick;
  // Session's on its pick and again when the oid or the porcelain changes; Working tree drawn from the
  // record as *changed files* is. A failed read keeps the pick and says so in place of the lines. Nothing
  // is kept across a load. `read(pick)` answers the route's JSON or rejects with why.
  AO.gitPick = function (els, read) {
    const st = { commits: [], pick: "tree", answer: null, oid: null, porcelain: null, v: null, editor: null, root: "", asked: 0,
      options: null };
    const paint = () => {
      const { sel, up, down, line, files } = els;
      const options = AO.gitPickOptions(st.commits, st.pick);
      if (options !== st.options) { sel.innerHTML = options; st.options = options; }  // an open select stays open
      sel.value = st.pick;
      const all = AO.gitPickEntries(st.commits), at = all.indexOf(st.pick);
      up.disabled = at <= 0; down.disabled = at >= all.length - 1;
      const commit = st.commits.find((c) => c.sha === st.pick);
      line.innerHTML = commit ? AO.gitPickNaming(commit) : "";
      line.classList.toggle("hidden", !commit);
      if (st.pick === "tree") { if (st.v) files.innerHTML = AO.gitFiles(st.v, st.editor, st.root); return; }
      if (st.answer && st.answer.error) files.innerHTML = `<div class="muted">could not read: ${esc(st.answer.error)}</div>`;
      else if (st.answer) files.innerHTML = AO.gitPickLines(st.answer, st.pick, st.editor, st.root);
    };
    const ask = (pick) => {
      const n = ++st.asked;
      return read(pick).then((a) => {
        if (n !== st.asked) return;  // a later pick's answer is the one drawn
        st.commits = a.commits || [];
        st.pick = AO.gitPickHeld(st.commits, st.pick);
        if (st.pick === pick && pick !== "tree") st.answer = a;
        paint();
      }, (why) => {
        if (n !== st.asked) return;
        const error = String((why && why.message) || why).replace(/^git_files: /, "");
        // a held sha the host no longer counts among the ten: back to Working tree, the commits read again
        if (pick !== "tree" && pick !== "session" && /not among the last ten commits/.test(error)) {
          st.pick = "tree"; st.answer = null; paint();
          return ask("tree");
        }
        if (pick !== "tree") st.answer = { error };
        paint();
      });
    };
    const choose = (pick) => {
      if (pick === st.pick) return;
      st.pick = pick; st.answer = null;
      if (pick !== "tree") els.files.innerHTML = '<div class="muted">reading…</div>';
      paint();
      ask(pick);
    };
    els.sel.addEventListener("change", () => choose(els.sel.value));
    els.up.addEventListener("click", () => choose(AO.gitPickStep(st.commits, st.pick, -1)));
    els.down.addEventListener("click", () => choose(AO.gitPickStep(st.commits, st.pick, 1)));
    return {
      state: st,
      update(v, editor, root) {
        st.v = v; st.editor = editor; st.root = root;
        const oid = (v.git && v.git.oid) || "", porcelain = JSON.stringify((v.git && v.git.files) || []);
        const moved = st.oid !== null && oid !== st.oid, first = st.oid === null;
        const changed = st.porcelain !== null && porcelain !== st.porcelain;
        st.oid = oid; st.porcelain = porcelain;
        paint();
        if (first || moved) ask(st.pick);
        else if (st.pick === "session" && changed) ask("session");
      },
    };
  };
  // …painted into the Session card's row and its term from the view and each delta: shown with
  // the work's first change, hidden while it has none
  AO.paintRecent = function (v, editor, row, dt) {
    const rf = AO.recentFiles(v, editor);
    row.innerHTML = rf;
    row.classList.toggle("hidden", !rf); dt.classList.toggle("hidden", !rf);
  };
  // The Session card's **recent links** (§4.5 item 4, §4.5a, TD-543): the record's `links`, the URLs the
  // session printed, newest first, each drawn as its host and path (the scheme dropped, the middle elided
  // past forty-eight characters), a GitHub pull request or issue as *owner/repo#n*; the full URL and the
  // time it was printed on hover; a plain click opens it in a new tab, `noopener`, as the pane's Ctrl+click
  // does. Nothing is fetched for it. "" when the record holds none.
  AO.shortLink = function (url) {
    const gh = /^https?:\/\/github\.com\/([^/]+)\/([^/]+)\/(?:pull|issues)\/(\d+)(?:[/?#]|$)/.exec(url);
    if (gh) return `${gh[1]}/${gh[2]}#${gh[3]}`;
    const bare = url.replace(/^https?:\/\//, "");
    return bare.length > 48 ? `${bare.slice(0, 30)}…${bare.slice(-17)}` : bare;
  };
  AO.recentLinks = function (v) {
    const links = v.links || [];
    return links.map((k) => {
      const url = String(k.url || "");
      if (!/^https?:\/\//.test(url)) return "";
      const title = esc(`${url}${k.at ? ` — printed ${String(k.at).slice(0, 16).replace("T", " ")}Z` : ""}`);
      return `<div><a href="${esc(url)}" target="_blank" rel="noopener" title="${title}">${esc(AO.shortLink(url))}</a></div>`;
    }).join("");
  };
  // …painted into its row and term from the view and each delta: shown with the first URL, hidden with none
  AO.paintLinks = function (v, row, dt) {
    const rl = AO.recentLinks(v);
    row.innerHTML = rl;
    row.classList.toggle("hidden", !rl); dt.classList.toggle("hidden", !rl);
  };
  // The provider the page registers beside the web-links addon when the Session card has an editor button:
  // a row with candidates asks the `paths` route once — the answer kept by the row's text until
  // `clear` (a re-attach) — and the runs the host resolved are links; a failed ask is no link and is
  // remembered nowhere, so the next hover asks again. **A path that wraps is one link** (§4.6, TD-1259):
  // the row is read in its logical line, through `AO.cutRows`' view so a row the program cut at the width
  // joins as it does for the addon — back while a row is wrapped, forward while the next is, as far as
  // `AO.PATH_JOIN` characters — and a run of the joined text on this row is a link whose range spans the
  // rows; the runs of the row alone are asked beside them, so a joined row that runs two words together
  // takes no link a row had before.
  AO.PATH_JOIN = 2048;
  AO.pathProvider = function (term, id, editor, fetchPaths) {
    const known = new Map();
    let era = 0;  // an answer that lands after a `clear` belongs to the attach before it
    const ask = fetchPaths || ((runs) => fetch(`/api/sessions/${encodeURIComponent(id)}/paths`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ runs }),
    }).then((r) => (r.ok ? r.json() : Promise.reject(r.status))));
    return {
      clear: () => { known.clear(); era += 1; },
      provideLinks(y, callback) {
        const buf = AO.cutRows(term).buffer.active;
        const line = (i) => (i >= 0 ? buf.getLine(i) : undefined);
        const own = line(y - 1) ? line(y - 1).translateToString(true) : "";
        let top = y - 1, bottom = y - 1, size = own.length;
        while (top > 0 && line(top) && line(top).isWrapped && size < AO.PATH_JOIN) {
          top -= 1; size += line(top).translateToString(false).length;
        }
        while (line(bottom + 1) && line(bottom + 1).isWrapped && size < AO.PATH_JOIN) {
          bottom += 1; size += line(bottom).translateToString(true).length;
        }
        // each character of the joined text as its row and cell: a wide character is one character over two cells
        let text = "", off = 0;
        const at = [];
        for (let i = top; i <= bottom && line(i); i++) {
          const row = line(i), t = row.translateToString(i === bottom), cellOf = [];
          if (i === y - 1) off = text.length;
          if (row.getCell) {
            for (let x = 0; x < row.length; x++) {
              const c = row.getCell(x);
              if (!c || c.getWidth() === 0) continue;
              for (let k = 0; k < (c.getChars() || " ").length; k++) cellOf.push(x);
            }
          }
          for (let k = 0; k < t.length; k++) at.push({ x: (k < cellOf.length ? cellOf[k] : k) + 1, y: i + 1 });
          text += t;
        }
        const joined = AO.pathRuns(text).filter((r) => at[r.start].y <= y && y <= at[r.end - 1].y);
        const alone = AO.pathRuns(own).map((r) => ({ ...r, start: r.start + off, end: r.end + off }))
          .filter((r) => !joined.some((j) => j.start === r.start && j.end === r.end));
        // eight runs, each with its pieces (TD-1262), asked eight paths at a time
        let whole = 0;
        const runs = [...joined, ...alone].filter((r) => (r.piece ? whole <= 8 : ++whole <= 8));
        if (!runs.length) { callback(undefined); return; }
        // a joined run the host resolved wins over a run of the row alone it covers
        const links = (paths) => runs.filter((r) => paths[r.path]).filter((r, i, ok) =>
          !ok.slice(0, i).some((k) => r.start < k.end && k.start < r.end)).map((r) => ({
          range: { start: at[r.start], end: at[r.end - 1] },
          text: r.run,
          decorations: { underline: true, pointerCursor: true },
          activate: (event) => AO.pathLink(event, editor, paths[r.path], r.line, r.col),
        }));
        const key = `${off}|${text}`;
        if (known.has(key)) { const l = links(known.get(key)); callback(l.length ? l : undefined); return; }
        const asked = era;
        const want = [...new Set(runs.map((r) => r.path))], batches = [];
        for (let i = 0; i < want.length; i += 8) batches.push(want.slice(i, i + 8));
        Promise.all(batches.map((b) => ask(b))).then((all) => {
          const paths = Object.assign({}, ...all.map((got) => (got && got.paths) || {}));
          if (asked === era) known.set(key, paths);
          const l = links(paths); callback(l.length ? l : undefined);
        }, () => callback(undefined));
      },
    };
  };
  // **a cut row is one line** (§4.6, TD-494): a program that breaks its own lines at the width prints
  // rows with no wrap mark, so the addon would read a URL wider than the pane as a cut URL and rows
  // that are no link.
  // The addon reads the screen through this view, where a row reads as wrapped when the row above
  // is full to its last column and it begins with a URL character that starts no `scheme://` of
  // its own; the addon's regex still decides what a link is, and its range spans the rows.
  AO.cutRows = function (term) {
    const scheme = /^[A-Za-z][A-Za-z0-9+.-]*:\/\//, urlChar = /^[^\s"'!*(){}|\\^<>`]/;
    const cut = (buf, y, line) => {
      const prev = y > 0 && buf.getLine(y - 1);
      if (!prev || !prev.length) return false;
      const last = prev.getCell(prev.length - 1), tail = last ? last.getChars() : "";
      const head = line.translateToString(true);
      return tail !== "" && !/\s/.test(tail) && urlChar.test(head) && !scheme.test(head);
    };
    const view = (buf) => ({
      getNullCell: () => buf.getNullCell(),
      getLine: (y) => {
        const line = buf.getLine(y);
        if (!line || line.isWrapped || !cut(buf, y, line)) return line;
        return { isWrapped: true, length: line.length, getCell: (x, c) => line.getCell(x, c),
          translateToString: (t, a, b) => line.translateToString(t, a, b) };
      },
    });
    return {
      registerLinkProvider: (p) => term.registerLinkProvider(p),
      buffer: { get active() { return view(term.buffer.active); } },
    };
  };
  // ---- the Prompts card (design §4.5 *The Prompts card*, §4.6 *A jump to a prompt*, TD-977) ----
  // Who sent a row, drawn before its text where it is not the person: *the brief*, *the policy* for the
  // home's own fixed lines, else a session's name as the view gives it (`from_name`). Pure, for a test.
  AO.promptSender = function (p) {
    const f = (p && p.from) || "person";
    if (f === "person") return "";
    if (f === "brief") return "the brief";
    if (f === "system") return "the policy";
    return String(p.from_name || f);
  };
  // What a press on row `i` sends (§4.6): the drawn openings and their `whole` marks of the card's
  // prompts from the newest down to the pressed one, those without one left out; null when the pressed
  // one has none — a miss at the page, and nothing is sent. Pure, for a test.
  AO.jumpOpenings = function (prompts, i) {
    const has = (x) => !!x && typeof x.drawn === "string" && x.drawn !== "";
    const list = prompts || [];
    if (!has(list[i])) return null;
    return list.slice(0, i + 1).filter(has).map((x) => ({ drawn: x.drawn, whole: !!x.whole }));
  };
  AO.JUMP_WAIT = 7000;  // the bridge's `JUMP_WITHIN` and two seconds more (§4.6 *The answer*)
  // One press pending at a time (§4.6 *The answer*): `send(openings)` puts the jump on the socket and
  // answers false when it cannot. `press` resolves true on `{jumped: true}`; false on `{jumped: false}`,
  // on no frame within `JUMP_WAIT`, on a socket that closed first (`closed`) or on one that was not open;
  // and returns null for a press while one waits, which is ignored. A frame with no press pending is
  // dropped. Pure, for a test: `timers` stands in for setTimeout.
  AO.jumper = function (send, timers) {
    const t = timers || { set: (f, ms) => setTimeout(f, ms), clear: (h) => clearTimeout(h) };
    let pending = null;
    const settle = (ok) => {
      if (!pending) return;
      const p = pending; pending = null;
      if (p.timer != null) t.clear(p.timer);
      p.resolve(ok);
    };
    return {
      press(openings) {
        if (pending) return null;
        return new Promise((resolve) => {
          pending = { resolve, timer: null };
          let sent = false;
          try { sent = send(openings); } catch (e) { sent = false; }  // a socket closing under the send
          if (!sent) { settle(false); return; }
          if (pending) pending.timer = t.set(() => settle(false), AO.JUMP_WAIT);
        });
      },
      frame(c) { settle(!!(c && c.jumped)); },
      closed() { settle(false); },
      busy() { return !!pending; },
    };
  };
  // The card's rows (§4.5a *Focus side panel* **Prompts**): each one press, its time (age and date on
  // hover), the sender where it is not the person, the prompt's first line, and under it in grey the
  // reply's first line; the press's hover the prompt's opening. A row in `missed` (its `at`) says *not in
  // the terminal's history* with **Transcript** opened at it; with `gone` (no pane) every row is the
  // Transcript alone. Pure, for a test.
  AO.promptsHtml = function (prompts, id, missed, gone) {
    const pad = (n) => String(n).padStart(2, "0");
    return (prompts || []).map((p, i) => {
      const at = String(p.at || ""), d = new Date(Date.parse(at));
      const time = isNaN(d) ? "" : `${pad(d.getHours())}:${pad(d.getMinutes())}`;
      const hover = isNaN(d) ? at : `${AO.fmtShortAge(at)} ago · ${d.toLocaleString()}`;
      const who = AO.promptSender(p), first = String(p.text || "").split("\n")[0];
      const reply = String(p.reply || "").split("\n")[0];
      const href = `/transcript/${encodeURIComponent(id)}?at=${encodeURIComponent(at)}`;
      const link = `<a href="${esc(href)}" target="_blank" rel="noopener">Transcript</a>`;
      const miss = gone ? `<div class="prmiss meta">${link}</div>`
        : missed && missed.has(at) ? `<div class="prmiss meta">not in the terminal's history · ${link}</div>` : "";
      return `<div class="prow"><button class="prbtn" type="button" data-i="${i}" title="${esc(p.text || "")}"${gone ? " disabled" : ""}>`
        + `<span class="prline"><span class="meta prtime" title="${esc(hover)}">${esc(time)}</span>`
        + `${who ? `<span class="prfrom">${esc(who)}</span>` : ""}<span class="prtext">${esc(first)}</span></span>`
        + `${reply ? `<span class="prreply">${esc(reply)}</span>` : ""}</button>${miss}</div>`;
    }).join("");
  };
  // …its summary, grey: *n · last <age>* (§4.5 *The Prompts card*)
  AO.promptsSummary = function (prompts) {
    const list = prompts || [];
    if (!list.length) return "";
    const age = AO.fmtShortAge(list[0].at);
    return age ? `${list.length} · last ${age} ago` : String(list.length);
  };
  AO.focus = function (s, popped) {
    const id = s.id;
    // §4.5a *Git card: the pick · ↑ · ↓* (TD-856, built by TD-862): read through the page's `git_files` route
    const gitPick = $("#gitpicksel") ? AO.gitPick(
      { sel: $("#gitpicksel"), up: $("#gitup"), down: $("#gitdown"), line: $("#gitpickline"), files: $("#gitfiles") },
      (pick) => fetch(`/api/sessions/${encodeURIComponent(id)}/git_files?pick=${encodeURIComponent(pick)}`)
        .then((r) => r.json().then((j) => (r.ok && !j.error ? j : Promise.reject(new Error(j.error || j.detail || r.status))))),
    ) : null;
    document.title = AO.focusTitle(s);
    AO.focusIcon(s);
    // §4.5a **Reports** (TD-150): the heading's **i** mark opens its paragraph in place, as the
    // Inbox's do; it sits in the panel's `<summary>`, so the press must not also fold the panel
    const imark = $("#i-reports"), info = $("#info-reports");
    if (imark && info) imark.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
      info.hidden = !info.hidden; imark.setAttribute("aria-expanded", info.hidden ? "false" : "true");
    });
    if (popped) {
      // design §4.5 *Pop out* (TD-046): say so to this browser's other tabs, and keep the size and
      // position the person gives the window, per session, as a team's fold is kept.
      AO.poppedId = id;
      if (popChan()) popChan().postMessage({ open: id });
      const keep = () => store.set(`win.${id}`, { w: window.outerWidth, h: window.outerHeight, x: window.screenX, y: window.screenY });
      let t = null;
      window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(keep, 500); });
      window.addEventListener("pagehide", () => { keep(); if (popChan()) popChan().postMessage({ closed: id }); });
    }
    // scrollback: 0 — tmux owns the history (TD-022), and the mouse is the browser's (TD-174): the
    // attach sets no mouse option, so tmux asks for no tracking, a plain drag selects here and
    // Shift+click grows it. The wheel and Shift+PageUp/PageDown reach tmux's history by scroll
    // messages (below); a local buffer would only ever hold stale repaints.
    if (s.state === "scheduled") {
      // §6 *Start time*: no pane yet, so no terminal — the banner stands, and the page looks again
      // while it waits, so the session's terminal appears once the agent has started it
      // — but never under a person's hands: an open dialog (a Message… being written) or a field
      // with the focus puts the look off until they are done
      const busy = () => !!document.querySelector("dialog[open]") || ["INPUT", "TEXTAREA"].includes((document.activeElement || {}).tagName);
      setInterval(() => { if (!busy()) location.reload(); }, 20000);
      return;
    }
    const term = new Terminal({ ...AO.TERM_OPTS, theme: { ...AO.TERM_THEME }, scrollback: 0, linkHandler: AO.paneLinkHandler($("#term")) });
    const fit = new FitAddon.FitAddon(); term.loadAddon(fit);
    const links = new WebLinksAddon.WebLinksAddon((e, uri) => AO.paneLink(e, uri));  // on a read-only Focus too
    term.loadAddon({ activate: (t) => links.activate(AO.cutRows(t)), dispose: () => links.dispose() });
    // **a path is a link** (TD-501): only where the Session card draws its editor button
    const pathLinks = s.editor && s.editor.file ? AO.pathProvider(term, id, s.editor) : null;
    if (pathLinks) term.registerLinkProvider(pathLinks);
    term.open($("#term")); fit.fit();
    AO.termRenderer(term);
    AO.termFont(term, fit);
    AO.terms.push({ term, fit });
    let ws, delay = 500, paneGone = false;
    const sendGrid = AO.resizeSender((grid) => !!(ws && ws.readyState === 1) && (ws.send(JSON.stringify({ resize: grid })), true));
    // The terminal mark's state (`AO.termMark`, above), redrawn each second and on each change
    const mk = { retryAt: null, clients: 0, window: null, grid: null, open: false, state: s.state, lastByte: null };
    const markEl = $("#ftermmark");
    // the soft-key row (§4.5a, TD-990): dimmed while the attach cannot take its keys — cosmetic, since a
    // press reads the same two things itself
    const softEl = $("#softkeys");
    const tlog = (...a) => console.info("[shiftlead] terminal", ...a, new Date().toISOString());
    // The disconnect card (`AO.dropCard`, above): drawn with the mark while it reads *reconnecting…*,
    // gone with it on the first pane byte; never over the pane, and the retry line is the terminal's.
    const dropEl = $("#fdrop");
    let dropShown = false;
    const drawDrop = (on) => {
      if (!dropEl || (!on && !dropShown)) return;
      dropShown = on;
      dropEl.classList.toggle("hidden", !on);
      if (!on) return;
      const c = AO.dropCard(AO.dropHeld(id), id, s.team || "", Date.now());
      const node = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
      const head = node("div", "dchead");
      head.append(node("b", "", "Disconnected — reconnecting"), node("span", "dim", "the spend this page last held"));
      const kids = [head];
      const fig = (says, word) => {
        const span = node("span", "dcfig");
        if (!says) { span.append(node("span", "dim", "no reading"), ` ${word}`); return span; }
        const tok = node("span", "", says.tok); tok.title = says.kinds;
        span.append(says.money, node("span", "dim", " · "), tok, ` ${word}`);
        return span;
      };
      for (const r of c.rows) {
        const val = node("div", "dcval");
        val.append(fig(r.day, "today"), node("span", "dim", " · "), fig(r.week, "this week"));
        kids.push(node("div", "dclab", r.label), val);
      }
      const wins = node("div", "dcwin");
      for (const w of c.windows) wins.append(node("span", "", w));
      if (c.windows.length) kids.push(wins);
      kids.push(node("div", "dcfoot dim", c.asof ? `as of ${c.asof}` : "as of — no reading"));
      dropEl.replaceChildren(...kids);
    };
    const drawMark = () => {
      if (softEl) softEl.classList.toggle("dim", !(ws && ws.readyState === 1) || readOnly);
      if (!markEl) return;
      mk.grid = [term.cols, term.rows];
      const m = AO.termMark(mk, Date.now());
      markEl.classList.toggle("hidden", !m);
      if (m && (markEl.textContent !== m.text || markEl.title !== m.title)) { markEl.textContent = m.text; markEl.title = m.title; }
      if (!!(m && m.kind === "reconnecting") !== dropShown) drawDrop(!!(m && m.kind === "reconnecting"));
    };
    AO.focusUsage = () => AO.dropUsage(id);
    setInterval(drawMark, 1000);
    // design §4.5 *Focus watches* (TD-096): an unattended session's attach is read-only. The server
    // decides and drops the keys (§4.6); the page learns it from the attach's first frame and only
    // says so — `mode` is the record's as last seen, and a change to it re-attaches.
    let readOnly = false, mode = !!s.unattended, hinted = 0;
    // a press on a Prompts row goes to this window's terminal socket (§4.6 *A jump to a prompt*); one not
    // open is a miss at the page
    const jumper = AO.jumper((ops) => !!(ws && ws.readyState === 1) && (ws.send(JSON.stringify({ jump: ops })), true));
    const roLine = document.getElementById("termro");
    // The pane is gone for good: end the terminal and stop reconnecting. The events push says so
    // before any reconnect could, and the server's 4404 says so too (TD-029).
    function endTerm(text) {
      paneGone = true;
      jumper.closed();
      if (ws) { try { ws.onclose = null; ws.close(); } catch (e) { /* already closing */ } }
      mk.retryAt = null; mk.open = false; drawMark();
      if (softEl) softEl.classList.add("hidden");  // no terminal, no keys
      term.write(`\r\n\x1b[90m[shiftlead] ${text}\x1b[0m\r\n`);
    }
    function openTerm() {
      if (paneGone) return;
      readOnly = false;  // until this attach says otherwise, in its first frame
      if (roLine) roLine.classList.add("hidden");
      const cols = Number.isFinite(term.cols) && term.cols > 0 ? term.cols : 120, rows = Number.isFinite(term.rows) && term.rows > 0 ? term.rows : 32;
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/term/${encodeURIComponent(id)}?cols=${cols}&rows=${rows}`);
      ws.binaryType = "arraybuffer";
      // the grid as it is now, not as it was at the dial: a refit while connecting sends nothing (TD-288)
      ws.onopen = () => {
        const grid = [term.cols > 0 ? term.cols : cols, term.rows > 0 ? term.rows : rows];
        ws.send(JSON.stringify({ resize: grid }));
        sendGrid.mark(...grid);
        mk.open = true; mk.lastByte = Date.now(); tlog("open"); drawMark();
        AO.dropRead(id, s.team || "");  // the disconnect card's reading, at load and at each reconnect
        if (pathLinks) pathLinks.clear();  // a re-attach asks the host again (TD-501)
      };
      // The backoff resets on pane output, never on open (TD-029): a connection the server accepts
      // and then ends is not a working terminal, and resetting there retried twice a second forever.
      ws.onmessage = (m) => {
        if (typeof m.data === "string" && m.data.startsWith("{")) {
          // The attach's own word, not pane output: it does not reset the backoff (TD-029).
          let c = null; try { c = JSON.parse(m.data); } catch (e) { c = null; }
          if (c && "read_only" in c) {
            readOnly = !!c.read_only;
            if (roLine) roLine.classList.toggle("hidden", !readOnly);
            if (readOnly && softEl) softEl.classList.add("hidden");
            drawMark();
            return;
          }
          // the bridge's reading of tmux's clients and window (§4.6), sent when it changes
          // a jump's answer (§4.6): the pending press's, never pane output
          if (c && "jumped" in c) { jumper.frame(c); return; }
          if (c && "clients" in c) {
            mk.clients = Number(c.clients) || 0; mk.window = Array.isArray(c.window) ? c.window : null;
            tlog("clients", mk.clients, "window", mk.window, "grid", [term.cols, term.rows]); drawMark();
            return;
          }
        }
        const t = Date.now();
        if (mk.lastByte != null && t - mk.lastByte >= AO.TERM_SILENT) tlog(`output after ${Math.floor((t - mk.lastByte) / 1000)}s`);
        mk.lastByte = t;
        if (mk.retryAt != null) { mk.retryAt = null; drawMark(); }
        delay = 500; term.write(typeof m.data === "string" ? m.data : new Uint8Array(m.data));
      };
      let opened = false;
      ws.addEventListener("open", () => { opened = true; });
      ws.onclose = (e) => {
        jumper.closed();
        if (paneGone) return;  // the push already ended it
        mk.open = false; drawMark();
        tlog("closed", e.code, e.reason || "");
        // The rule is `AO.termClose` (above), so a test can reach it; this is what acts on it.
        const v = AO.termClose(e.code, opened, delay, e.reason);
        if (v.final) { endTerm(v.why); return; }
        term.write(`\r\n\x1b[90m[shiftlead] terminal ${v.why} — retrying in ${Math.round(delay / 1000) || 1}s\x1b[0m\r\n`);
        if (mk.retryAt == null) mk.retryAt = Date.now();  // held across retries until a pane byte
        setTimeout(openTerm, delay); delay = v.delay;
      };
    }
    // A mode change seen in the feed: end this attach without the retry path and open a new one,
    // which reads the mode afresh (§4.6).
    function reattach() {
      if (paneGone) return;
      jumper.closed();
      if (ws) { try { ws.onclose = null; ws.close(); } catch (e) { /* already closing */ } }
      delay = 500; openTerm();
    }
    if (AO.paneIsGone(s)) { paneGone = true; term.write("\x1b[90m[shiftlead] this session's pane is gone (killed, closed, or the tmux server restarted).\x1b[0m\r\n"); }
    else openTerm();
    term.onData((d) => {
      if (!ws || ws.readyState !== 1) return;
      // A read-only attach drops every key, server-side (the wheel is a scroll message, below);
      // the page only spares the round trip.
      if (readOnly) return;
      ws.send(d);
    });
    // ...and says why nothing happened, on a key the person pressed: `onData` also carries xterm's
    // own replies to the pane's queries, which fired the toast on load (TD-296 #11).
    term.onKey(() => {
      if (readOnly && Date.now() - hinted > 5000) { hinted = Date.now(); AO.toast("watching: the terminal is read-only — Take over to type"); }
    });
    // Copy / paste: Ctrl+C with a selection copies (no ^C), Ctrl+Shift+C copies, Ctrl+Shift+V and
    // right-click paste; the header buttons do the same for discoverability. Clipboard access
    // needs a secure context (https or localhost) — ssh -L to 127.0.0.1 qualifies.
    // A copy carries §4.6's notes (TD-1267): `edge` comes from a release alone, and whether the header draws
    // **Transcript** is read at the copy, from `#ftranscript` (absent counts as hidden).
    const copyState = { firstFree: true };
    const hasTranscript = () => { const tr = $("#ftranscript"); return !!tr && !tr.classList.contains("hidden"); };
    const copySel = (edge) => {
      const t = term.getSelection();
      if (t) AO.copyWith({ text: t, edge, transcript: hasTranscript(), state: copyState, toast: AO.toast,
        write: (x) => navigator.clipboard.writeText(x) });
      return !!t;
    };
    // A screenshot (a file and no text) takes the attach road whether or not the composer is open, and
    // its path is pasted here — a bracketed paste, so it lands in the tool's input unsent (TD-479)
    let attachFiles = null;
    const live = () => ws && ws.readyState === 1;
    const pasteText = (t) => { if (live()) term.paste(t); };
    const pasteFile = (f) => attachFiles && attachFiles([f], (path) => { if (live()) term.paste(path); });
    // the menu's Paste and right-click have no paste event: they read the clipboard by script
    const pasteClip = () => {
      if (readOnly) { AO.toast("watching: paste is off — Take over to type"); return; }
      AO.clipPaste(navigator.clipboard, { text: pasteText, file: pasteFile, toast: AO.toast });
    };
    // the keys' paste: the browser's own event, read where it lands (TD-523)
    AO.wireTermPaste($("#term"), { readOnly: () => readOnly, text: pasteText, file: pasteFile, toast: AO.toast });
    term.attachCustomKeyEventHandler((e) => {
      if (e.type !== "keydown") return true;
      if (e.ctrlKey && e.shiftKey && (e.key === "C" || e.key === "c")) { copySel(); return false; }
      if (e.ctrlKey && !e.shiftKey && (e.key === "c" || e.key === "C") && term.hasSelection()) { copySel(); term.clearSelection(); return false; }
      // Plain Ctrl+V pastes too, as Ctrl+Shift+V and Shift+Insert do: passed through, Claude Code
      // reads ^V as "paste an image from the clipboard", which over ssh only produces a "try scp"
      // message (first-use finding). The paste itself is the browser's event (`AO.wireTermPaste`).
      if (AO.pasteKey(e)) return false;
      if (e.shiftKey && (e.key === "PageUp" || e.key === "PageDown")) { ws && ws.readyState === 1 && ws.send(JSON.stringify({ scroll: e.key === "PageUp" ? "up" : "down" })); return false; }
      return true;
    });
    // A long press fires `contextmenu` too, and it is no right-click (§4.6 *A touch does not select*,
    // TD-989): the browser's menu is still prevented, but a paste follows only a mouse's or a pen's. The
    // last `pointerdown` on the terminal says which, each replacing the last (a hybrid device's mouse after a
    // touch right-clicks as before); pointer events fire for a touch whose `touchstart` is prevented.
    let touchPointer = false;
    $("#term").addEventListener("pointerdown", (e) => { touchPointer = e.pointerType === "touch"; }, { capture: true });
    $("#term").addEventListener("contextmenu", (e) => { e.preventDefault(); if (!touchPointer) pasteClip(); });
    $("#tcopy").addEventListener("click", () => { if (!copySel()) AO.toast("select text in the terminal first (drag; Shift+click grows it)"); });
    // The wheel scrolls tmux's history (§4.6, TD-174): caught before xterm.js sees it — with no
    // mouse tracking it would turn a notch into arrow keys for the pane — and sent as lines, the
    // notches of one animation frame in one message. A read-only attach passes it, as every scroll.
    let wheelAcc = 0, wheelFrame = 0;
    let touch = null;  // the finger on the terminal, below
    const cellH = () => (term.rows ? $("#term").clientHeight / term.rows : 16) || 16;
    // a touch's travel not yet taken goes into the accumulator first: one step per frame, and one at its end
    const touchTake = () => {
      if (!touch || !touch.scrolling) return;
      const { add, sent } = AO.touchStep(touch.total, touch.sent);
      touch.sent = sent;
      wheelAcc -= add / cellH();
    };
    const scrollFrame = () => {
      if (wheelFrame) return;
      wheelFrame = requestAnimationFrame(() => {
        wheelFrame = 0;
        touchTake();
        const { msg, rest } = AO.wheelStep(wheelAcc);
        wheelAcc = rest;
        if (msg && ws && ws.readyState === 1) ws.send(JSON.stringify(msg));
      });
    };
    $("#term").addEventListener("wheel", (e) => {
      e.preventDefault(); e.stopPropagation();
      wheelAcc += e.deltaMode === 1 ? e.deltaY : e.deltaMode === 2 ? e.deltaY * (term.rows || 24) : e.deltaY / cellH();
      scrollFrame();
    }, { capture: true, passive: false });
    // A finger's drag scrolls it too (§4.6, TD-989): a touch screen sends no `wheel`, so a one-finger touch's
    // vertical travel becomes the wheel's message, caught in the capture phase before xterm.js's own touch
    // listeners. Under the slop it stays the browser's tap (it focuses the terminal); past it the touch is a
    // scroll until it lifts, its default prevented so no tap or emulated mouse follows. Two fingers put down
    // together are the browser's (a pinch); a second finger joining a scroll ends it, and the touch is inert
    // (`dead`) until every finger lifts. `touch-action: pinch-zoom` (app.css) keeps the page from scrolling.
    const termEl = $("#term");
    // the fingers counted are the terminal's (`targetTouches`): one resting elsewhere on the page is not a
    // second finger, and its lift, which the terminal never hears, cannot leave the touch inert
    termEl.addEventListener("touchstart", (e) => {
      if (touch && touch.dead && e.targetTouches.length > 1) { if (touch.scrolled) e.preventDefault(); return; }
      if (e.targetTouches.length !== 1) {
        if (touch && touch.scrolling) { touchTake(); scrollFrame(); e.preventDefault(); }
        touch = { dead: true, scrolled: !!(touch && touch.scrolling) };
        return;
      }
      const t = e.targetTouches[0];
      touch = { id: t.identifier, y0: t.clientY, total: 0, sent: 0, scrolling: false, dead: false };
    }, { capture: true, passive: false });
    termEl.addEventListener("touchmove", (e) => {
      if (!touch) return;
      if (touch.dead) { if (touch.scrolled) e.preventDefault(); return; }
      const t = Array.from(e.targetTouches).find((x) => x.identifier === touch.id);
      if (!t) return;
      touch.total = t.clientY - touch.y0;
      if (!touch.scrolling && Math.abs(touch.total) >= AO.TOUCH_SLOP) touch.scrolling = true;
      if (!touch.scrolling) return;
      e.preventDefault(); e.stopPropagation();
      scrollFrame();
    }, { capture: true, passive: false });
    const touchEnd = (e) => {
      if (!touch) return;
      if ((touch.scrolling || touch.scrolled) && e.cancelable) e.preventDefault();
      if (!touch.dead && touch.scrolling) { touchTake(); scrollFrame(); }
      if (e.targetTouches.length === 0) touch = null;
      else if (!touch.dead) touch = { dead: true, scrolled: touch.scrolling };
    };
    termEl.addEventListener("touchend", touchEnd, { capture: true, passive: false });
    termEl.addEventListener("touchcancel", touchEnd, { capture: true, passive: false });
    // The soft-key row (§4.5a **Focus pane: soft-key row**, TD-990): a press types the key's bytes through the
    // terminal, as xterm.js's own keys do (`onData`, the socket), and moves no focus, so the phone's keyboard
    // stays as it is. The pointer is captured, so its `pointerup` reaches the key whatever it is, and the key is
    // sent only when that `pointerup` is still over it; a pan of the row ends in `pointercancel` and sends nothing.
    if (softEl) {
      const keyOf = (e) => e.target.closest && e.target.closest("button[data-key]");
      const up = (k) => k && k.classList.remove("down");
      softEl.addEventListener("pointerdown", (e) => {
        const k = keyOf(e); if (!k) return;
        e.preventDefault();
        try { k.setPointerCapture(e.pointerId); } catch (_) { /* a pointer already gone */ }
        k.classList.add("down");
      });
      // WebKit moves focus on the emulated mousedown a prevented pointerdown does not stop
      softEl.addEventListener("mousedown", (e) => { if (keyOf(e)) e.preventDefault(); });
      softEl.addEventListener("pointerup", (e) => {
        const k = keyOf(e); if (!k) return;
        up(k);
        const at = document.elementFromPoint(e.clientX, e.clientY);
        if (!at || at.closest("button[data-key]") !== k) return;
        if (!live() || readOnly) return;  // read at the press: the dim is only what it looks like
        const bytes = AO.softKey(k.dataset.key, !!term.modes.applicationCursorKeysMode);
        if (bytes) term.input(bytes, true);
      });
      softEl.addEventListener("pointercancel", (e) => up(keyOf(e)));
      softEl.addEventListener("lostpointercapture", (e) => up(keyOf(e)));
    }
    // Copy on select (§4.5a, TD-174): the person's, in settings.yml, on by default. A selection ended —
    // the mouse released, which a Shift+click is too — is copied when it is on, and says so with
    // Copy's own toast, *copied* or *clipboard blocked* (TD-273: a silent copy could not be told from
    // a selection); Ctrl+C and Copy are unchanged either way. It needs the secure context the clipboard needs.
    // A drag held past the screen's top or bottom (§4.6 *A selection is one screen*, TD-1267) marks its edge
    // (`AO.edgeMark`); the release reads the mark, and draws the edge's note when the selection then touches that
    // row — on the copy's toast, or alone, not green, when copy on select is off or disabled.
    const cos = $("#tcopysel");
    let selMoved = false, mark = null;
    term.onSelectionChange(() => { selMoved = true; });
    $("#term").addEventListener("mousedown", (e) => {
      mark = AO.edgeMark(mark, { type: "down", shift: e.shiftKey || e.button !== 0 }).mark;
    }, { capture: true });
    document.addEventListener("mousemove", (e) => {
      if (!mark || !mark.drag) return;
      const scr = document.querySelector("#term .xterm-screen");
      if (scr) mark = AO.edgeMark(mark, { type: "move", edge: AO.pastEdge(e.clientY, scr.getBoundingClientRect(), cellH()) }).mark;
    });
    document.addEventListener("mouseup", () => {  // the page's: a drag may end outside the pane
      const moved = selMoved;
      selMoved = false;
      const up = AO.edgeMark(mark, { type: "up", moved });
      mark = up.mark;
      if (!moved) return;
      const t = term.getSelection(), pos = t && term.getSelectionPosition();
      const edge = pos && (up.fire === "top" ? pos.start.y === 0 : up.fire === "bottom" && pos.end.y === term.rows - 1)
        ? up.fire : null;
      if (cos && cos.checked && !cos.disabled) { if (t) copySel(edge); }
      else if (edge) AO.toast(AO.copyNote({ edge, transcript: hasTranscript() }), false, undefined, undefined, undefined, 7000);
    });
    if (cos) {
      if (!window.isSecureContext) {
        cos.disabled = true;
        cos.closest("label").classList.add("off");
        cos.closest("label").title = "copy on select needs a secure context (https or localhost), as Copy does";
      }
      cos.addEventListener("change", () => AO.setCopyOnSelect(cos));
    }
    $("#tpaste").addEventListener("click", pasteClip);
    // tmux is told the grid whatever changed it: the pane's box (the observer) or the person's
    // face and size from Settings (`AO.setTermLook`, which refits) — TD-288: the second resized the
    // grid here and left the pane drawing at the old width; one send per gesture (`AO.resizeSender`, TD-794)
    term.onResize(({ cols, rows }) => sendGrid(cols, rows));
    new ResizeObserver(() => fit.fit()).observe($("#term"));
    term.focus();

    const compose = $("#compose");
    // design §4.5a *Focus composer* **the bar** (TD-491, built by TD-500): folded, the composer opens over
    // the terminal's foot and folds back on Esc and on Send; `open` (person.composer) has no bar
    const cbar = $("#composerbar") ? AO.wireComposerBar({
      bar: $("#composerbar"), text: $("#cbtext"), send: $("#cbsend"), composer: $("#composer"), compose,
      sendBtn: $("#send"), hint: $("#composehint"), term,
    }) : null;
    compose.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { if (cbar) cbar.fold(); else term.focus(); }
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("#send").click();
    });
    // The terminal filled to the bar (§4.5a **the bar**): the header's bottom to the bar's top, the 360px
    // floor kept; the popped-out window and the narrow mode keep their own heights. Measured again
    // whenever what stands above it or the bar changes size, never on an open or a fold.
    const wrap = $("#termwrap");
    const fill = () => {
      if (!wrap || !wrap.classList.contains("cfold")) return;
      const bar = $("#composerbar"), barH = bar && !bar.classList.contains("hidden") ? bar.offsetHeight + 10 : 0;
      wrap.style.setProperty("--cbarh", `${barH}px`);  // the open composer takes the bar's place
      if (document.body.classList.contains("popped") || matchMedia("(max-width: 720px)").matches) { wrap.style.removeProperty("--termh"); return; }
      const softH = parseFloat(wrap.style.getPropertyValue("--softh")) || 0;  // the soft-key row's, unset as 0
      wrap.style.setProperty("--termh", `${AO.termFill(window.innerHeight, $("#term").getBoundingClientRect().top + window.scrollY, barH + softH + 16)}px`);
    };
    if (wrap && wrap.classList.contains("cfold")) {
      const ro = new ResizeObserver(fill);
      for (let el = wrap.previousElementSibling; el; el = el.previousElementSibling) ro.observe(el);
      if ($("#composerbar")) ro.observe($("#composerbar"));
      window.addEventListener("resize", fill);
      fill();
    }
    // the soft-key row's height is one variable (`--softh` on the wrap, 0 while it is hidden), which `fill()`
    // adds to the bar's and the composer and a popped-out terminal read; registered folded or not
    if (softEl && wrap) new ResizeObserver(() => { wrap.style.setProperty("--softh", `${softEl.offsetHeight}px`); fill(); }).observe(softEl);
    // a draft (§4.5a **Open a session**, TD-219; **the bar**, TD-500): kept in this browser as the person
    // writes it and dropped once it is sent. The Add entry form's is opened on load, filled, focused and
    // not sent; one the person folded waits on the bar, named there
    const draft = (() => { try { return localStorage.getItem(AO.draftKey(id)); } catch (_) { return null; } })();
    const handed = (() => { try { const v = sessionStorage.getItem("ao.draft.open") === id; if (v) sessionStorage.removeItem("ao.draft.open"); return v; } catch (_) { return false; } })();
    if (draft !== null && !compose.value) {
      compose.value = draft;
      if (!cbar || handed) { if (cbar) cbar.open(); compose.focus(); } else cbar.redraw();
    }
    compose.addEventListener("input", () => { try { if (compose.value) localStorage.setItem(AO.draftKey(id), compose.value); else localStorage.removeItem(AO.draftKey(id)); } catch (_) { /* no storage */ } });
    // **One press, one send** (§4.5a *Focus composer* **Send**, TD-806): the press's key and the text it
    // sent are held until the send answers; the box keeps what was typed since, and the bar folds only
    // once the box is empty
    const sender = AO.wireComposerSend({
      sendBtn: $("#send"), compose, hint: $("#composehint"),
      post: (body) => act(id, "send", body),
      draft: (v) => { try { if (v) localStorage.setItem(AO.draftKey(id), v); else localStorage.removeItem(AO.draftKey(id)); } catch (_) { /* no storage */ } },
      sent: (empty) => { if (empty) { if (cbar) cbar.fold(); else term.focus(); } },
      fail: (e) => banner(`Send failed: ${e.message}`),
      redraw: () => { if (cbar) cbar.redraw(); },
    });
    // design §4.5a *Focus composer* **prompt chips** (§4.8 *A role has saved prompts*, TD-170): a
    // press is **Send** with the chip's text — the same `send`, its confirmation and its refusals —
    // and Shift+press fills the composer for editing instead. The text is the definition's, carried
    // on the chip, never a session's words. Each press carries its own key, and the chip is disabled
    // until its send answers; the composer's box is not touched (TD-806).
    $$("#promptchips .chip").forEach((b) => AO.wireChip(b, {
      compose, post: (body) => act(id, "send", body), sent: () => term.focus(),
      closed: () => banner($("#composehint").textContent || "nothing can be sent now"),
      fail: (err) => banner(`Send failed: ${err.message}`),
    }));
    // design §4.5a *Focus composer* **Attach** / drop / paste (§4.4 *Attachment drop*, TD-002): each
    // file goes to the host agent through `/api/sessions/<id>/attach`, and the path it answers is
    // inserted at the composer's caret — Claude Code reads a path in a prompt — and nothing is sent
    // until Send. A drop on the terminal or the composer and an image pasted into the composer take
    // the same road; a paste that carries text is the text's, as before. Not while the composer is
    // closed: an unattended session takes nothing typed (§4.5 screen 2 *Focus watches*). A screenshot
    // pasted on the terminal takes it too, its path pasted there (`pasteClip` above, TD-479).
    attachFiles = AO.wireAttach({
      button: $("#attach"), input: $("#attachfile"), composer: $("#composer"), compose,
      targets: [$("#term"), compose, ...($("#composerbar") ? [$("#composerbar")] : [])],
      fail: banner, cancel: $("#attachcancel"),
      unfold: cbar ? cbar.open : null, mirror: cbar ? { button: $("#cbattach"), cancel: $("#cbcancel") } : null,
      upload: AO.attachUpload(id, Number($("#attach").dataset.piece)),
    });

    function banner(text) { const b = $("#fbanner"); b.textContent = text; b.classList.remove("hidden"); setTimeout(() => b.classList.add("hidden"), 7000); }
    // the **Prompts** card (§4.5 *The Prompts card*, TD-977): drawn from the delta while the record holds
    // a prompt; a press scrolls this window's terminal back to it, and a miss offers the Transcript
    let promptsV = [], promptsGone = false;
    const promptsMissed = new Set();
    function renderPrompts(v) {
      const pc = $("#promptscard"); if (!pc) return;
      promptsV = Array.isArray(v.prompts) ? v.prompts : [];
      pc.classList.toggle("hidden", !promptsV.length);
      $("#promptscount").textContent = AO.promptsSummary(promptsV);
      promptsGone = paneGone || AO.paneIsGone(v);
      $("#promptlist").innerHTML = AO.promptsHtml(promptsV, id, promptsMissed, promptsGone);
    }
    const plist = $("#promptlist");
    if (plist) plist.addEventListener("click", async (e) => {
      const b = e.target.closest("button.prbtn"); if (!b || b.disabled || jumper.busy()) return;
      const p = promptsV[+b.dataset.i]; if (!p) return;
      const ops = AO.jumpOpenings(promptsV, +b.dataset.i);
      const landed = ops ? await jumper.press(ops) : false;
      if (landed === null) return;
      if (landed) promptsMissed.delete(String(p.at || "")); else promptsMissed.add(String(p.at || ""));
      $("#promptlist").innerHTML = AO.promptsHtml(promptsV, id, promptsMissed, promptsGone || paneGone);
    });
    function render(v) {
      document.title = AO.focusTitle(v);
      AO.focusIcon(v);
      // the chips go with the composer on a session nothing can be sent to (§4.5a, TD-170)
      const pc = $("#promptchips");
      if (pc) pc.classList.toggle("hidden", ["exited", "closed", "limited", "unreachable"].includes(v.state));
      const readyNow = !!((v.ready || []).length && (v.ready || []).every(([, ok]) => ok));
      const cls = v.state_class, scraped = v.scraped ? " scraped" : "";
      // the pill's hover (§4.5a **state pill hover**, TD-490): the card's one text, from the view
      let head = `<span class="pill s-${cls}${scraped}" title="${esc(v.pill_title || "")}"><span class="dot"></span>${v.state_label}</span>`;
      const p = v.pending;
      // a subagent's prompt names its asker, and says the pane draws nothing until the deadline (§4.2,
      // §4.5a **Allow / Deny**, TD-950): `held_line.html`'s words, the deadline in the reader's clock
      const heldSpan = (h) => h ? ` <span class="meta held">from the ${esc(h.name)} subagent${h.deadline ? ` · the pane shows nothing until <span class="localtime" data-at="${esc(h.deadline)}" title="${esc(h.deadline)}">${esc(h.deadline)}</span>` : ""}</span>` : "";
      const held = heldSpan(v.state === "needs-you" ? v.held : null);
      // the open prompts beneath the newest, each answerable on its own line (§4.2 *Every entry is
      // answerable where it is drawn*, TD-950): `held_line.html`'s `prompt_line`, its buttons naming the call
      const others = v.state === "needs-you" ? (v.others || []).map((o) => `<div class="row gap wrap pline"><span class="meta">${esc(o.text)}</span>${o.answerable
        ? ` <span class="meta countdown" data-deadline="${esc(o.deadline)}"></span> <button class="btn sm" data-act="allow" data-id="${id}" data-call="${esc(o.call)}" data-line>Allow</button> <button class="btn sm" data-act="deny" data-id="${id}" data-call="${esc(o.call)}" data-line>Deny</button> <input class="denywhy" type="text" maxlength="200" data-id="${id}" placeholder="why? (optional)" aria-label="reason for Deny, optional: the session reads it">`
        : ""}${heldSpan(o.held)}</div>`).join("") : "";
      // Allow / Deny only for a tool with a permission channel (§4.3, §4.5a, TD-785): else the terminal's
      if (v.state === "needs-you" && p && p.kind === "permission" && v.permission_channel !== false) {
        head += ` <button class="btn sm primary" data-act="allow" data-id="${id}" data-call="${esc(p.tool_use_id || "")}">Allow</button> <button class="btn sm" data-act="deny" data-id="${id}" data-call="${esc(p.tool_use_id || "")}">Deny</button> <input class="denywhy" type="text" maxlength="200" data-id="${id}" placeholder="why? (optional)" aria-label="reason for Deny, optional: the session reads it"> <span class="meta">${esc(p.text)}</span> <span class="meta countdown" data-deadline="${p.deadline || ""}"></span>${held}${others}`;
        compose.disabled = true; $("#composehint").textContent = "a permission is pending: answer above";
      } else if (v.state === "needs-you" && p) {
        head += ` <span class="meta">${esc(p.kind)}: ${esc(p.text)}</span>${held}${others}`;
        compose.disabled = true; $("#composehint").textContent = "answer in the terminal above";
      } else if (v.state === "unreachable" && p && p.host_unreachable) {
        // design §4.4a: the hook still blocks on its node, and an answer from here cannot reach it
        head += ` <span class="meta">${esc(p.kind)}: ${esc(p.text)} — host unreachable: answer it at ${esc(v.host)}, in the tool's own dialog</span>`;
        compose.disabled = true; $("#composehint").textContent = "the host agent cannot be reached: nothing can be sent until it is back";
      } else if (v.state === "exited" || v.state === "closed" || v.state === "unreachable") {
        // There is no turn to start or steer: the pane is dead or out of reach. The composer used
        // to sit enabled here and say nothing, which was merely useless; saying "starts a new
        // turn" at a dead session would be a lie, so the state that made the hint necessary is
        // the state that has to be excluded from it. The exited banner below offers the two real
        // next steps (Resume, New session here). TD-047.
        compose.disabled = true;
        // The banner below offers **Resume** only on a record that holds a tool session id — an
        // `exited` or a `closed` one, from TD-081 step 2 — so the hint must not promise it where
        // there is none (a `shell`, a command run).
        $("#composehint").textContent = v.state === "unreachable"
          ? "the host agent cannot be reached: nothing can be sent until it is back"
          : (v.state === "exited" || v.state === "closed") && v.adapter_id
            ? "this session's process has ended: resume it under its own name, or start a new one, below"
            : "this session's process has ended: start a new session here, below";
      } else {
        // design §4.3: one button, two jobs. A message to an `idle` session starts a turn; a
        // message to a `working` one steers the turn in flight. Both are the same paste and the
        // same Enter — only the person's intent differs, so it is said in the label and the hint
        // rather than in a second control (§4.5a still governs what controls exist). TD-047.
        compose.disabled = false;
        // `stalled?` is a `working` session that stopped producing output (§4.2) — a turn already
        // in flight, not an idle one — so it steers too, and the hint says the state is uncertain
        // rather than pretending otherwise. `limited` is its own case: §4.2 says nothing the
        // person does unblocks a cap, so it must not claim a turn starts now; the paste lands and
        // waits, and §4.5a's controls for it are Switch profile and Wait.
        compose.disabled = false;
        // a record with no agent (§4.5a *A record with no agent*, TD-666): no turn to steer — Send
        // always types the line and presses Enter, into the running command while one runs
        const agent = v.agent !== false;
        const steering = agent && (v.state === "working" || v.state === "stalled?");
        // a send that waits keeps *Sending…* and its *not confirmed* hint over a view event (TD-806)
        sender.label(steering ? "→ Steer" : "→ Send");
        $("#composehint").textContent = sender.hint(
          !agent ? (v.state === "working" || v.state === "stalled?" ? "types the line and presses Enter — into the command that is running" : "types the line and presses Enter")
          : v.state === "limited" ? "the profile is at its cap: what you send waits until the window resets"
          : v.state === "stalled?" ? "steers the turn in flight — this session looks stalled, so it may not be read until it moves"
          : steering ? "steers the turn in flight — this session is working, and Claude Code queues what you type"
          : "starts a new turn");
      }
      const kept = AO.denyWhys($("#fstate"));
      $("#fstate").innerHTML = head;
      AO.restoreDenyWhys($("#fstate"), kept);
      // The mode toggle, named for what it does, and what it governs (design §4.5a, TD-096): the
      // composer is closed on an unattended session — it types, and typing is the disruption.
      // …**Take over** on the acts line as the next act, **Hand back** / *Switch to unattended* in
      // more ▾ (§4.5 *The Focus screen's anatomy*, TD-156). Both read `mode_act`, and the one that
      // applies is the one shown. Until 2026-09-25 a card-era line below rewrote every mode
      // button's text to the bare mode word, so the header read *unattended* where the design
      // said *Take over* (seen on Paul's screenshot for TD-156).
      for (const el of [$("#fmodeact"), $("#fmodemenu")]) {
        if (!el || !v.mode_act) continue;
        el.textContent = v.mode_act; el.title = v.mode_title || "";
        el.dataset.unattended = v.unattended ? "1" : "0";
      }
      const ma = $("#fmodeact"); if (ma) ma.classList.toggle("hidden", !v.unattended);
      // one outlined act (§4.5 *The card's anatomy*, row 6): Close session outranks Take over,
      // which is drawn plain beside it while the checklist passes
      if (ma) { ma.classList.toggle("next", !(readyNow && v.own)); ma.classList.toggle("link", !!(readyNow && v.own)); }
      renderPrompts(v);
      // the **Working** card (TD-156): the session's own words, and their age, from the delta
      const wc = $("#workingcard");
      if (wc) {
        const dg = v.doing;
        wc.classList.toggle("hidden", !dg);
        $("#workingtext").textContent = (dg && dg.text) || "";
        $("#workingage").textContent = dg && dg.age ? `says · ${dg.age} ago` : "";
      }
      const mm = $("#fmodemenu"); if (mm) mm.hidden = !!v.unattended;
      const fm = $("#fmode"); if (fm) fm.textContent = v.unattended ? "unattended" : "interactive";
      const cp = $("#composer"); if (cp) cp.classList.toggle("hidden", !!v.unattended);
      // the bar goes with the composer on an unattended session, and says why nothing can be sent (TD-500)
      const cb = $("#composerbar");
      if (cb) { const was = cb.classList.contains("hidden"); cb.classList.toggle("hidden", !!v.unattended); if (was !== !!v.unattended) fill(); }
      if (cbar) cbar.redraw();
      const tp = $("#tpaste");
      if (tp) tp.title = "paste the clipboard into the terminal (Ctrl+V, Ctrl+Shift+V, Shift+Insert, or right-click)" + (v.unattended ? " — not while you are watching: Take over first" : "");
      // §4.8a (TD-077 a2): the **suspended** mark rides the pushed delta like the state does. It
      // is drawn server-side at load and lives *outside* `#fstate` — a suspension is not a state —
      // so without this a person watching the very session that is suspended from somewhere else
      // would see the state change and not the mark, and the mark is the suspension's only record
      // (review of PR #306). Always in the page, hidden until it is true, as the banners are.
      // …and the two report-line marks that stand beside it, for the same reason (review of PR
      // #323): *out of work* and *restart wanted* are declared by the session while a person may
      // be watching it, and a chip drawn only at load would show neither the declaration nor the
      // claim that clears it. The words are the template's; this keeps them current.
      const oow = $("#foow");
      if (oow) {
        const o = v.out_of_work;
        oow.classList.toggle("hidden", !o);
        oow.title = (o && o.why) || "no reason recorded";
        oow.textContent = "out of work" + (o && o.age ? ` ${o.age}` : "");
      }
      const wait = $("#fwait");  // §4.5a **waiting** mark (TD-274): the view's words, its hover
      if (wait) {
        wait.classList.toggle("hidden", !v.waiting);
        wait.title = (v.waiting && v.waiting.full) || "";
        wait.textContent = (v.waiting && v.waiting.text) || "";
      }
      const rw = $("#frw");
      if (rw) {
        const r = v.restart_wanted, early = !!(r && r.early);
        rw.classList.toggle("hidden", !r);
        rw.classList.toggle("early", early);
        rw.title = ((r && r.why) || "no reason recorded")
          + (early ? ` — ${r.decided || "early"}, so a controller does not act on it: this one is for a person (design §4.9a)` : "");
        rw.textContent = "restart wanted" + (early ? (r.repeat ? ` · repeats ${r.repeat}` : " · early") : "")
          + (r && r.age ? ` ${r.age}` : "");
      }
      const bc = $("#fbc");
      if (bc) {
        bc.classList.toggle("hidden", !v.brief_changed);
        bc.title = (v.brief_changed && v.brief_changed.full) || "";
      }
      const rs = $("#frestarted");  // §4.5a **restarted** chip (TD-487): the view's words, its hover
      if (rs) {
        rs.classList.toggle("hidden", !v.restarted);
        rs.title = (v.restarted && v.restarted.hover) || "";
        rs.textContent = (v.restarted && v.restarted.text) || "";
        rs.dataset.until = (v.restarted && v.restarted.until) || "";
      }
      // …and the usage gate's pause (§4.5a **paused · usage**, TD-100): written and cleared by the
      // host agent's tick while a person may be watching, so it rides the delta too.
      const gt = $("#fgated");
      if (gt) {
        gt.classList.toggle("hidden", !v.gated);
        gt.title = (v.gated && v.gated.full) || "";
        gt.textContent = (v.gated && v.gated.text) || "paused · usage";
      }
      // …and a brief the composer did not take (§4.5a **brief not sent**, TD-339): the next prompt clears it
      const bu = $("#fbrief");
      if (bu) {
        bu.classList.toggle("hidden", !v.brief_unsent);
        bu.title = (v.brief_unsent && v.brief_unsent.full) || "";
        bu.textContent = (v.brief_unsent && v.brief_unsent.text) || "brief not sent";
      }
      const susp = $("#fsuspended");
      if (susp) {
        susp.classList.toggle("hidden", !v.suspended_note);
        susp.title = v.suspended_note || "";
      }
      // An exited session keeps its dead pane on purpose (exit code, last lines, run log); say so
      // and offer the two useful next steps instead of leaving tmux's "Pane is dead" to explain it.
      const ex = $("#fexited");
      if (v.state === "exited" || v.state === "closed") {
        const code = v.exit_code == null ? "" : ` (exit code ${v.exit_code})`;
        const q = `dir=${encodeURIComponent(v.dir || "")}&adapter=${encodeURIComponent(v.adapter || "claude-code")}`;
        const kept = v.state === "exited" && v.pane !== false;  // a kill/close destroys the pane (TD-023)
        // …and, where the header draws **Transcript** (§4.5a, TD-166), *or read its transcript*
        const read = v.adapter_id ? ` — or <a href="/transcript/${id}" target="_blank" rel="noopener">read its transcript</a>` : "";
        // the first line is the ending in the card's words and its time (§4.5a **state pill hover**, TD-490)
        const ending = v.ending_text ? `<div class="endwords"><b>${esc(v.ending_text)}</b></div>` : "";
        ex.innerHTML = `${ending}This session's process has ${esc(v.state)}${esc(code)}. ${kept ? `The pane is kept so its last screen and run log stay readable${read}.` : `Its pane is gone (killed, or the tmux server restarted); the run log stays readable${read}.`} `
          // design §4.5a **Focus (exited / closed)** (TD-081 step 2, Paul: *a resume option that
          // requires no input from me*): **Resume** is one press and no form — the same name, so
          // the record is replaced in place and keeps its mail — and **Resume with changes…** is
          // that same create as a filled-in form. A `closed` record resumes too: §4.5a says
          // *`exited` or `closed` holding a tool session id*, and the link that stood here
          // offered neither, which is how a resume became a second record beside the first.
          + (v.adapter_id && (v.state === "exited" || v.state === "closed")
            ? `<button class="btn sm primary" data-act="resume" data-id="${id}">Resume</button> `
              + `<button class="btn sm" data-act="resume-form" data-id="${id}">Resume with changes…</button> `
            : "")
          + `<a class="btn sm" href="/new?${q}">New session here</a> <button class="btn sm ghost" data-act="remove" data-id="${id}">Forget</button>`
          // how long a closed record stays, beside its Forget (§4.5 row 6, TD-266): the view's fixed words
          + (v.closed_keep ? ` <span class="meta">${esc(v.closed_keep)}</span>` : "");
        // §4.5a *The help text* (TD-167): Resume's and Forget's titles and the banner's *i* mark, all
        // from the page's own fixed text (`#help-exited`, `#exitedmark`), never composed here
        const hp = $("#help-exited");
        if (hp) {
          $$('[data-act="resume"]', ex).forEach((b) => { b.title = hp.dataset.titleResume || ""; });
          $$('[data-act="remove"]', ex).forEach((b) => { b.title = hp.dataset.titleForget || ""; });
        }
        // design §4.9a *One member back, today* (TD-172, TD-250): a team's member comes back into
        // its team's run by Restart — Resume alone starts it attended — so the banner says so
        if (v.team) ex.insertAdjacentHTML("beforeend", `<div class="note memberback">To put it back in ${esc(v.team)}'s run: <b>Restart</b> in its card's <b>more ▾</b>, or <code>ao restart</code> — Resume alone starts it attended. With no launch record: <b>Resume with changes…</b> and tick <b>Unattended</b>.</div>`);
        const mk = $("#exitedmark");
        if (mk) { ex.appendChild(mk.content.cloneNode(true)); AO.applyHelpMarks(ex); }
        ex.classList.remove("hidden");
      } else ex.classList.add("hidden");
      // the soft-key row (§4.5a, TD-990): gone with the ending, back on its other side while the page has a
      // terminal, and with the record's mode — Hand back hides it before its re-attach, Take over shows it
      if (softEl) softEl.classList.toggle("hidden", !AO.softShown(v, paneGone));
      const aid = $("#adapter_id"); if (aid) aid.textContent = v.adapter_id || "—";
      const tr = $("#ftranscript");
      if (tr) tr.classList.toggle("hidden", !v.adapter_id);
      // §4.5a Focus header **‹› VS Code** (TD-578): the transcript's link lands with the hook's file
      const te = $("#ftranscript_editor");
      // a file link (§4.6, TD-689): `href` and `data-label` alone — the transcript is one launch, so never `data-folder`
      if (te) { te.classList.toggle("hidden", !v.transcript_editor); if (v.transcript_editor) { te.href = v.transcript_editor.url; te.dataset.label = v.transcript_editor.label; } }
      $("#last_output").textContent = v.last_output ? fmtAge(v.last_output) + " ago" : "—";
      if (v.git && $("#gitline")) {  // a reaped record draws no Git card (§4.1, TD-979)
        // the one measure first (design §4.2, TD-080: *only on this machine*), then `ahead`, which
        // is *unmerged* and a different question — the template renders the same three parts
        const unpushed = v.git.unpushed ? ` · ${v.git.unpushed} unpushed${v.git.pushed_against ? ` vs ${v.git.pushed_against}` : ""}` : "";
        $("#gitline").textContent = v.git.branch + unpushed + (v.git.ahead ? ` · ${v.git.ahead} ahead` : "") + (v.git.behind ? ` · ${v.git.behind} behind` : "");
        // §4.5a *Git card: changed files* (TD-628): each path a link by the recent files' form, joined
        // to the worktree's top level the page was served (`s.git_root`), the same on load and each delta
        // …under the pick (TD-862): Working tree draws them; a commit or Session reads `git_files`
        if (gitPick) gitPick.update(v, s.editor, s.git_root);
        else $("#gitfiles").innerHTML = AO.gitFiles(v, s.editor, s.git_root);
      }
      const gp = $("#gitpick"); if (gp) gp.classList.toggle("hidden", !v.git);
      // the person's `file_link` read again with each view (§4.5a *Settings page: You, file link*: *read by the
      // next file link, no reload*; TD-536) — in place, since the pane's link provider holds this object
      if (s.editor && v.editor) { s.editor.first = v.editor.first; s.editor.wait = v.editor.wait; }
      AO.paintRecent(v, s.editor, $("#frecent"), $("#frecentdt"));
      AO.paintLinks(v, $("#flinks"), $("#flinksdt"));
      // a record with no agent draws no Reports, Inbox or grants (§4.5a *A record with no agent*, TD-666):
      // nothing is derived for it and nothing reads its inbox — the template leaves the cards out
      if (v.agent !== false) { renderReports(v); renderInbox(v); }
      renderGrants(v);
      renderStop(v);
      renderMembership(v);
      if (v.agent === false) {
        // …and no checklist: Close session on any state Close is, its confirm the shell's (TD-666)
        const now = v.pane !== false && !["closed", "scheduled"].includes(v.state);
        const cm = $("#fclosemenu"); if (cm) cm.disabled = !now;
        $("#fclose").classList.toggle("hidden", !now);
        renderRail(v, false);
        return;
      }
      const checks = v.ready || [];
      $("#checks").innerHTML = checks.map(([n, ok]) => `<div class="${ok ? "ok" : "bad"}">${ok ? "✓" : "✗"} ${esc(n)}</div>`).join("");
      // design §4.5a Focus header **Close session** (TD-156): the checklist passing on an idle or
      // exited session puts *ready to close ✓* on the identity line, in the card's words, and the
      // outlined Close session on the acts line; the side card's small Close is the same act.
      // the agent's own state is the checklist's first row (TD-679): one test, not a second one here
      const ready = !!(checks.length && checks.every(([, ok]) => ok));
      $("#closebtn").disabled = !ready;
      $("#closebtn").classList.toggle("hidden", !v.own);  // a member's checklist has no button: its Close is more ▾'s
      // more ▾'s Close also on the person's own session whose only failing row is a shell past SHELL_WAIT,
      // its confirm naming the shell (§4.5a *Close session*, TD-761: `shell_close`, the card's reading)
      const cm = $("#fclosemenu");
      if (cm) {
        cm.disabled = !(ready || v.shell_close);
        cm.dataset.confirm = v.shell_close || v.close_confirm || cm.dataset.confirm;
      }
      // …and the next act only on the person's own session (`own`): a team member runs itself
      $("#fready").classList.toggle("hidden", !(ready && v.own));
      $("#fclose").classList.toggle("hidden", !(ready && v.own));
      renderRail(v, ready);
    }
    // **» put away** / **«** (§4.5 *The panel put away*, §4.5a, TD-412): the panel to a 28px rail,
    // the terminal taking the width (the fit's observer on `#term` refits it and the pty hears the
    // new columns as a window resize). Remembered per browser (`focus.side`), read by the template
    // before the first paint; the folds inside are untouched. The rail's glyphs are drawn from the
    // same delta the cards are, so it is as current as the panel: one per card with something to say.
    let railV = s, railReady = false, inboxN = 0;
    function renderRail(v, ready) {
      if (v) { railV = v; railReady = !!ready; }
      const txt = (el) => (el ? el.textContent : "");  // a record with no agent has neither card (TD-666)
      const lines = { reports: txt($("#reportscount")), inbox: txt($("#inboxcount")) };
      const html = AO.railHtml(railV, railReady, inboxN, lines, s.editor);
      const el = $("#railglyphs");
      if (el && el.innerHTML !== html) el.innerHTML = html;
    }
    AO.wireRail({
      side: $("#side"), away: $("#sideaway"), back: $("#sideback"), glyphs: $("#railglyphs"),
      card: (name) => $(`details.side[data-side="${name}"]`),
    });
    // design §4.5a **Reports** / **grants** chip (§4.8, TD-028 step 4). The lists come from the
    // pushed record, so a `progress` or `finding` call from anywhere shows up here without a reload.
    // the per-repo PR marks (§4.4 *Per-session views*, TD-617): the page's first load, kept by `repos`
    let prMarks = {}, reportsV = null;
    try { prMarks = JSON.parse(($("#reportscard") || {dataset: {}}).dataset.prMarks || "{}") || {}; } catch (e) { prMarks = {}; }
    function renderReports(v) {
      const progress = v.progress || [], findings = v.findings || [];
      const card = $("#reportscard");
      card.classList.toggle("hidden", !(progress.length || findings.length));
      $("#reportscount").textContent = [progress.length ? `${progress.length} progress` : "", findings.length ? `${findings.length} filed` : ""].filter(Boolean).join(" · ");
      const base = card.dataset.prBase || "", name = card.dataset.name || v.name || "this session";
      // the PR number as a link from a structured field — never from text a session wrote — and
      // **the PR's mark** after it, *merged* or *closed*, from the record's repo's map (`pr_repo`), which
      // the page's load and each `repos` push carry (§4.5a card **report line**, TD-193; §4.4, TD-617);
      // an open or unknown PR has none
      reportsV = v;
      const marks = prMarks[v.pr_repo || ""] || {};
      const prLink = (n) => (base ? `<a class="ref" href="${esc(base)}/pull/${encodeURIComponent(n)}" target="_blank" rel="noopener">#${esc(n)}</a>` : `#${esc(n)}`)
        + (marks[String(n)] ? ` <span class="st prmark">${esc(marks[String(n)])}</span>` : "");
      const row = (p) => {
        const derived = (p.source || "declared") !== "declared";
        // a reference is shown once (§4.5a **report line**, TD-095): an entry whose reference is
        // its PR never reads `#359 → #359` — the rule `report_line` follows for the card
        const st = p.review_pr
          ? `<span class="st claimed">claimed · in review ${prLink(p.review_pr)}</span>`
          : `<span class="st ${esc(p.status)}">${esc(p.status)}</span>`
            + (p.pr && String(p.ref) !== `#${p.pr}` ? ` <span class="st">→ ${prLink(p.pr)}</span>` : "");
        // the merged PRs of a claim still held (§4.8, TD-325): *claimed · slices #1025, #1027*,
        // each a link from the field, as `review_pr`'s is
        const sl = (p.status === "claimed" && p.slices) ? p.slices.filter((x) => x && x.pr) : [];
        const slices = sl.length ? ` <span class="st slices">· slices ${sl.map((x) => prLink(x.pr)).join(", ")}</span>` : "";
        const why = p.why ? ` <span class="st">${esc(p.why)}</span>` : "";
        return `<div class="rep${derived ? " derived" : ""}"><span class="ref" title="${derived ? "derived by the agent" : "declared by the session"}">${esc(p.ref)}</span>`
          + `${st}${slices}${why}<span class="grow"></span><span class="st age" data-since="${esc(p.at || "")}">${fmtAge(p.at)}</span></div>`;
      };
      const g = AO.reportGroups(progress);
      const heads = { progress: "in progress", review: "in review", done: "done", dropped: "dropped" };
      $("#progresslist").innerHTML = Object.keys(heads).filter((k) => g[k].length)
        .map((k) => `<div class="st repgroup">${heads[k]}</div>` + g[k].map(row).join("")).join("");
      // Drop, behind more ▾, on a declared in-progress claim only: a claim with a PR is in review,
      // and letting go of it is not what a person reading the panel means (TD-143)
      const drops = g.progress.filter((p) => p.status === "claimed" && (p.source || "declared") === "declared");
      // a declared entry carries no branch, and the session's checked-out one may be another
      // claim's (review of PR #586), so the confirm names none
      $("#reportsmenu").innerHTML = drops.map((p) => {
        const confirmText = `Let go of ${p.ref}'s claim? The lease ends and another session may take it; `
          + `its branch and any work on it stay; only ${name} can claim it again.`;
        return `<button data-act="drop" data-id="${id}" data-ref="${esc(p.ref)}" data-confirm="${esc(confirmText)}">Drop ${esc(p.ref)}…</button>`;
      }).join("");
      $("#reportsmore").hidden = !drops.length;
      $("#findinglist").innerHTML = findings.map((f) => {
        const derived = (f.source || "declared") !== "declared";
        const pri = f.priority ? ` <span class="st">${esc(f.priority)}</span>` : "";
        return `<div class="rep${derived ? " derived" : ""}"><span class="ref">${esc(f.ref)}</span><span class="st">filed</span>${pri}`
          + `<span class="grow"></span><span class="st age" data-since="${esc(f.at || "")}">${fmtAge(f.at)}</span></div>`;
      }).join("");
    }
    // design §4.5a Focus side panel **Inbox** (§4.10). Bodies never ride the pushed record ("A
    // bounded body"): the record carries `unread` and the `mail` marks, and when those change the
    // panel fetches the entries again through the `inbox` RPC — a person's read, which marks nothing.
    let inboxSig = null, inboxSoon = null, inboxFirst = true;
    function renderInbox(v) {
      const sig = JSON.stringify([v.unread || 0, v.mail || {}]);
      if (sig === inboxSig) return;
      inboxSig = sig; refreshInbox();
    }
    AO.refreshInbox = refreshInbox;
    function refreshInbox() {
      if (!$("#inboxcard")) return;  // a record with no agent: nothing reads its inbox (TD-666)
      clearTimeout(inboxSoon);
      inboxSoon = setTimeout(async () => {
        let got;
        try {
          const r = await fetch(`/api/sessions/${encodeURIComponent(id)}/inbox`);
          if (!r.ok) return;
          got = await r.json();
        } catch (e) { return; }
        const es = got.entries || [];
        $("#inboxcard").classList.toggle("hidden", !es.length);
        $("#inboxcount").textContent = es.length ? `${got.unread} unread · ${es.length}` : "";
        inboxN = es.length; renderRail();
        $("#inboxlist").innerHTML = es.slice().reverse().map((e) => AO.mailEntry(e, id)).join("");
        AO.reopenFolds($("#inboxlist"));
        if (inboxFirst && location.hash === "#inbox" && es.length) $("#inboxcard").scrollIntoView({ block: "nearest" });
        inboxFirst = false;
      }, 150);
    }
    // design §4.5a controllers chip + Members list (§4.8, TD-036). Both are membership, which is
    // read *across* records: a change on another session (a controller renamed, removed, or gone; a
    // member's state, lane or report) comes to this page as this session's own delta again, which
    // the server sends from the fleet it keeps (§4.4 *Per-session views*, TD-617) — so the page
    // reads no `/api/sessions`, and the chip never keeps saying who controlled it at page load.
    function renderMembership(v) {
      const el = $("#fcontrollers");
      if (el) {
        const cs = v.under || [];
        el.innerHTML = (cs.length
          ? "under " + cs.map((c) => `<button class="badge controller${c.gone ? " scraped" : ""}" data-act="uncontrol" data-id="${esc(id)}" data-who="${esc(c.id)}" title="${esc(c.id)} — click to remove it as a controller${c.gone ? " (its session is gone)" : ""}">${esc(c.name)} ×</button>`).join("")
          : `<span class="note">none — nobody may act on this session</span>`)
          + ` <button class="btn sm ghost" data-act="control-add" data-id="${esc(id)}" title="add a controller">+</button>`;
      }
      const box = $("#members"); if (!box) return;
      const ms = v.members || [];
      const mc = $("#memberscount"); if (mc) mc.textContent = String(ms.length);
      box.innerHTML = (ms.length
          ? ms.map((m) => `<div class="row gap"><a class="name" href="/focus/${encodeURIComponent(m.id)}">${esc(m.name)}</a>`
              + `<span class="meta">${esc(m.state || "")}</span>`
              + (m.lane ? `<span class="meta">${esc(m.lane)}</span>` : "") + `<span class="grow"></span>`
              + (m.report ? `<span class="meta">${esc(m.report)}</span>` : "") + `</div>`).join("")
          : `<div class="note">no members yet — <code>ao control ${esc(v.name || "")} add &lt;session&gt;</code>, or the controllers chip in a session's Session card</div>`)
        + `<div class="note">The sessions this one may act on. It needs both the grant and a place in each session's controllers (design §4.8).</div>`;
    }
    // design §4.5a Focus header **stops** badge (§6, TD-026): the one place a stop time can be
    // changed after the session started. The agent parses the time and refuses an interactive
    // session, so this only asks — the same division as the grants and controllers chips.
    // Two places, one control (TD-156): the Session card's row, always — *none — set* until one
    // is — and the identity line's note, drawn only while a stop time is set, as the reminder.
    function renderStop(v) {
      const el = $("#fstop"), row = $("#fstopset");
      if (el) {
        el.classList.toggle("hidden", !v.unattended || !v.stop_note);  // a flip to interactive takes the control away, not just the time
        el.textContent = v.stop_note || "no stop time";
        el.dataset.until = v.run_until || "";  // the record's own value: what the edit box is filled from
      }
      if (row) {
        row.hidden = !v.unattended;
        row.textContent = v.stop_note || "none — set";
        row.classList.toggle("off", !v.stop_note);
        row.dataset.until = v.run_until || "";
      }
    }
    function renderGrants(v) {
      const el = $("#fgrants"); if (!el) return;
      const all = (el.dataset.grants || "").split(",").filter(Boolean), held = v.capabilities || [];
      el.innerHTML = all.map((g) => {
        const on = held.includes(g);
        const title = on ? `revoke ${g} — it lets this session act on other sessions` : `grant ${g}: this session could send to, kill and close other sessions`;
        return `<button class="badge${on ? "" : " off"}" data-act="grants" data-id="${id}" data-grant="${esc(g)}" title="${esc(title)}"`
          + `${on ? ` data-confirm="Revoke ${esc(g)} from this session?"` : ` data-confirm="Grant ${esc(g)}? It lets this session send to, kill and close other sessions."`}>${esc(g)}</button>`;
      }).join("");
    }
    // The side panel's folds (design §4.5 *The Focus screen's anatomy*, TD-156): every card a
    // `<details>`, the template's `open` its default, this browser's choice remembered per card as
    // a team's fold is. A button in a card's summary (Ready to close's Close) must not also fold it.
    $$("details.side").forEach((d) => {
      const key = `focus.side.${d.dataset.side}`;
      d.open = store.get(key, d.open);
      d.addEventListener("toggle", () => store.set(key, d.open));
    });
    document.addEventListener("click", (e) => { if (e.target.closest("details.side > summary button")) e.preventDefault(); });
    render(s);
    const looked = AO.unseenLook(document, () => act(id, "seen", {}).catch(() => {}));
    looked(s);
    connectEvents((ev) => {
      if (ev.event === "session" && ev.id === id) {
        // The pushed delta is authoritative and arrives before any reconnect (TD-029): a closed or
        // pane-less session ends the terminal here, rather than letting it discover it by retrying.
        if (!paneGone && AO.paneIsGone(ev.session)) {
          endTerm("this session's pane is gone (see the banner).");
        }
        render(ev.session);
        if (ev.session.state && ev.session.state !== mk.state) {
          // silence is counted from when the session began working, not from a quiet idle before it
          if (ev.session.state === "working" && mk.lastByte != null) mk.lastByte = Date.now();
          mk.state = ev.session.state; drawMark();
        }
        if (!!ev.session.unattended !== mode) { mode = !!ev.session.unattended; reattach(); drawMark(); }
        // a visible Focus is the look, so a turn ending here is seen the moment it happens (TD-017, TD-1228)
        looked(ev.session);
      } else if (ev.event === "repos" && ev.root) {
        // a repo's PRs moved: its marks replace what the page held, and the Reports panel redraws (TD-617);
        // a light stream sends the marks alone, `null` for a repo dropped (TD-670)
        if (ev.pr_marks) prMarks[ev.root] = ev.pr_marks; else delete prMarks[ev.root];
        if (reportsV && reportsV.pr_repo === ev.root) renderReports(reportsV);
      }
      if (ev.event === "gone" && ev.id === id) {
        // A window never closes itself: closing what a person opened is the person's act (§4.5
        // *Pop out*). A popped one keeps saying why it is empty; a tab's banner fades as it did.
        if (!popped) banner("session removed");
        else {
          const b = $("#fbanner");
          b.textContent = "This session was forgotten: its record is gone. Close this window when you are done with it.";
          b.classList.remove("hidden");
          document.title = `${s.name} · forgotten`;
          AO.focusIcon({ state_class: "exited" });
        }
      }
    }, `light=1&focus=${encodeURIComponent(id)}`);
  };
  // ---- keys (design §4.5a **keys** and **?** overlay, §4.5 *Keys on every page*, TD-124) ----
  // One table of (keys, page, control), read by one `keydown` handler and by the `?` overlay, so
  // the two cannot drift. A key is a name for a control the page already draws: it presses that
  // control's element — the same click handler — and does nothing where the control is absent.
  // `sel` finds the control (inside the ringed card or row when `ring`), `text` narrows it to the
  // button whose label is one of those words; `move`, `g`, `focus` and `help` are the few keys
  // that press nothing: moving the ring, the team jump, the filter box, and this list.
  AO.KEYS = [
    { keys: ["1"], page: "all", control: "Sessions", sel: '.topbar .tab[href="/"]' },
    { keys: ["2"], page: "all", control: "Inbox", sel: "#personinbox" },
    { keys: ["3"], page: "all", control: "Queue", sel: "#queuetab" },
    { keys: ["n"], page: "all", control: "New session", sel: '.topbar a[href="/new"]' },
    { keys: ["/"], page: "all", control: "the filter box (Esc leaves it)", sel: "#filter, #ifilter", focus: true },
    { keys: ["?"], page: "all", control: "this list (? or Esc closes it)", help: true },
    // the side panel put away and brought back (§4.5 *The panel put away*, TD-412): whichever is drawn
    { keys: ["s"], page: "focus", control: "put the side panel away / bring it back", sel: ".side:not(.rail) #sideaway, .side.rail #sideback" },
    // the composer's bar (§4.5a *Focus composer* **the bar**, TD-500): opens it, where a bar is drawn
    { keys: ["c"], page: "focus", control: "open the composer", sel: "#composerbar:not(.hidden) #cbtext" },
    { keys: ["j", "ArrowDown"], page: "org", control: "ring the next card", move: 1 },
    { keys: ["k", "ArrowUp"], page: "org", control: "ring the previous card", move: -1 },
    { keys: ["g"], page: "org", control: "then a team's initial, or a group's number 1–9: jump to that team", g: true },
    // a team's + card (TD-379) is pressed by the same keys: its link is no session's, so it carries
    // no `data-focus` — `markPopped` would relabel it and the pop-out click would claim it
    { keys: ["Enter", "o"], page: "org", ring: true, control: "Focus (Details, or Focus window); on a team's + card, New session on that team", sel: "a[data-focus], a.plusgo" },
    { keys: ["Shift+Enter"], page: "org", ring: true, control: "Pop out", sel: '[data-act="popout"]' },
    { keys: ["a"], page: "org", ring: true, control: "Allow its permission", sel: '[data-act="allow"]:not([data-line])' },
    { keys: ["d"], page: "org", ring: true, control: "Deny its permission", sel: '[data-act="deny"]:not([data-line])' },
    // the fold (§4.5a *team card: fold*, TD-194): on a card it folds the card's team and the ring
    // goes to the header; on a folded team's header, as `Enter` there, it opens it
    { keys: ["f"], page: "org", ring: true, control: "fold its team (on a folded team's header, open it)", sel: "[data-fold]", fold: true },
    { keys: ["j", "ArrowDown"], page: "inbox", control: "ring the next row", move: 1 },
    { keys: ["k", "ArrowUp"], page: "inbox", control: "ring the previous row", move: -1 },
    // `Enter` is the ringed row's page where it has one — a mail row — else Open; `o` is Open always
    { keys: ["Enter"], page: "inbox", ring: true, control: "the row's page (else Open, Open board)", sel: "a.pagelink", alt: { sel: "a.btn", text: ["Open", "Open board"] } },
    { keys: ["o"], page: "inbox", ring: true, control: "Open (Open board)", sel: "a.btn", text: ["Open", "Open board"] },
    // the message page (§4.5 screen 6 *The message page*, TD-136): Back, the list's next and
    // previous entry as it was filtered, and the entry's own controls
    { keys: ["Escape"], page: "msg", control: "Back to the list, at this entry", sel: "#msgback" },
    { keys: ["j", "ArrowDown"], page: "msg", control: "the next entry of the list", step: 1 },
    { keys: ["k", "ArrowUp"], page: "msg", control: "the previous entry of the list", step: -1 },
    { keys: ["r"], page: "msg", ring: true, control: "Reply", sel: '[data-act="reply"]', text: ["Reply", "Overrule"] },
    { keys: ["s"], page: "msg", ring: true, control: "Snooze ▾ (opens the menu)", sel: "details.more > summary", text: ["Snooze"] },
    { keys: ["x"], page: "msg", ring: true, control: "Dismiss or Done", sel: "button", text: ["Dismiss", "Done"] },
    { keys: ["a"], page: "inbox", ring: true, control: "Allow", sel: '[data-act="allow"]' },
    { keys: ["d"], page: "inbox", ring: true, control: "Deny", sel: '[data-act="deny"]' },
    // a board row's Reply is `board_reply` (TD-280): `r` opens it as it opens a message's
    { keys: ["r"], page: "inbox", ring: true, control: "Reply", sel: '[data-act="reply"], [data-act="board_reply"]', text: ["Reply"] },
    { keys: ["s"], page: "inbox", ring: true, control: "Snooze ▾ (opens the menu)", sel: "details.more > summary", text: ["Snooze"] },
    { keys: ["x"], page: "inbox", ring: true, control: "Dismiss or Done", sel: "button", text: ["Dismiss", "Done"] },
    // **Go with it** on a `steer` row and on a board row with a default; and a row's answer buttons
    // — an `ask`'s suggested answers, a board item's answers — in the order written (TD-254, TD-255).
    // `1` and `2` are the page's on any row without them: `AO.keyAnswers` is where they yield.
    { keys: ["g"], page: "inbox", ring: true, control: "Go with it", sel: "button", text: ["Go with it", "Go with it: Works"] },
    { keys: ["1", "2", "3", "4"], page: "inbox", ring: true, control: "its answers, in the order written (a row without any: 1 Sessions, 2 Inbox, 3 Queue)", sel: ".btn.answer", nth: true },
  ];
  AO.keyPage = (path) => (path === "/" ? "org" : path === "/inbox" ? "inbox" : path.startsWith("/inbox/") ? "msg" : path.startsWith("/focus/") ? "focus" : "other");
  // the message page's one row is its entry: its keys press that row's controls, never a thread's
  // A folded team's header takes its cards' place in the Org's ring (TD-194): the cards are hidden,
  // so `shown` skips them, and the header is found in the page's order where they were.
  const RINGS = { org: "#groups .rline, #groups .sc, #groups .tgroup.folded:not(.filtering) > .ghead", inbox: ".inboxpage .mailrow", msg: ".msgentry" };
  // The event's name in the table, or null when the page must not take it: focus in anything
  // editable (a composer, the filter, a reply box, the *why?* box, the terminal's own textarea), or
  // a modifier other than Shift held — those keys are the browser's and the terminal's.
  AO.keyName = function (ev) {
    if (ev.ctrlKey || ev.altKey || ev.metaKey) return null;
    const t = ev.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || "") || (t.closest && t.closest(".xterm")))) return null;
    return ev.key === "Enter" && ev.shiftKey ? "Shift+Enter" : ev.key;
  };
  // `answers`: the ringed row has answer buttons, so a digit is the row's (`nth`) and not the page's
  AO.keyEntry = (page, name, answers) => AO.KEYS.find((k) => (k.page === "all" || k.page === page) && k.keys.includes(name) && (!answers || k.nth || !/^[1-4]$/.test(name))) || null;
  // A row's own answer buttons, in the order written — never those of a row drawn inside it
  AO.keyAnswers = (row) => (row ? $$(".btn.answer", row).filter((el) => el.closest(RINGS.inbox) === row) : []);
  const shown = (el) => el.getClientRects().length > 0;
  const ringables = (page) => (RINGS[page] ? $$(RINGS[page]).filter(shown) : []);
  const ringed = (page) => (RINGS[page] && document.activeElement && document.activeElement.closest ? document.activeElement.closest(RINGS[page]) : null);
  // a team header that holds the ring after it was opened, where the ring stays (TD-194)
  const ringedHead = () => (document.activeElement && document.activeElement.closest ? document.activeElement.closest("#groups .tgroup > .ghead") : null);
  const ringTo = (el) => { if (!el) return; el.focus({ preventScroll: true }); el.scrollIntoView({ block: "nearest" }); };
  // A ringed card or row that is about to leave the page hands the ring to its neighbour.
  AO.handRing = function (el) {
    const page = AO.keyPage(location.pathname);
    if (!el || !RINGS[page] || !el.contains(document.activeElement)) return;
    const all = ringables(page), i = all.indexOf(el);
    const next = all[i + 1] || all[i - 1];
    if (next && next !== el) ringTo(next);
  };
  // The ringed thing's own control, or nothing: a key does nothing where the button is absent.
  // `label` is the button's words without its icon or ▾; `within` keeps a row's control its own,
  // never one of a row drawn inside it.
  AO.keyLabel = (t) => (t || "").replace(/[▾\s]+$/, "").replace(/^[^A-Za-z]+/, "");
  AO.keyControl = function (root, k, within) {
    return $$(k.sel, root).find((el) => !el.disabled
      && (!within || el.closest(within) === root)
      && (!k.text || k.text.includes(AO.keyLabel(el.textContent))));
  };
  function keyHelp() {
    const dlg = $("#keyhelp"); if (!dlg) return;
    if (dlg.open) { dlg.close(); return; }
    const page = AO.keyPage(location.pathname);
    const show = (k) => k.replace("ArrowDown", "↓").replace("ArrowUp", "↑");
    const rows = AO.KEYS.filter((k) => (k.page === "all" || k.page === page) && (!k.sel || k.ring || k.help || $(k.sel)));
    $("#keyrows").innerHTML = rows.map((k) => `<tr><td>${k.keys.map((x) => `<kbd>${esc(show(x))}</kbd>`).join(" ")}</td><td>${esc(k.control)}${k.ring ? ' <span class="dim">— on the ringed ' + (page === "org" ? "card" : "row") + "</span>" : ""}</td></tr>`).join("");
    $("#keynote").hidden = !RINGS[page];
    const back = document.activeElement;  // focus returns to where it was (§4.5a **?** overlay)
    dlg.addEventListener("close", () => { if (back && back.focus && document.contains(back)) back.focus({ preventScroll: true }); }, { once: true });
    dlg.showModal();
  }
  const helpBtn = $("#keyhelpbtn"); if (helpBtn) helpBtn.addEventListener("click", keyHelp);
  let gUntil = 0;
  function jumpTeam(key) {
    const secs = sections().filter((s) => !s.hidden);
    let dest = null;
    if (/^[1-9]$/.test(key)) dest = secs[+key - 1];
    else if (/^[a-z]$/i.test(key)) {
      const cur = ringed("org"), at = cur ? secs.indexOf(cur.closest(".tgroup")) : -1;
      const hit = (s) => (s.dataset.team || "").toLowerCase().startsWith(key.toLowerCase());
      dest = secs.slice(at + 1).find(hit) || secs.slice(0, at + 1).find(hit);
    }
    if (!dest) return;
    const card = $$(".sc", dest).find(shown);
    const head = dest.matches(".folded:not(.filtering)") ? $(".ghead", dest) : null;
    if (card) ringTo(card);
    else if (head) ringTo(head);  // a folded team: its header is the stop (TD-194)
    else { const b = $(".ghead button", dest); if (b) b.focus(); dest.scrollIntoView({ block: "nearest" }); }
  }
  document.addEventListener("keydown", (ev) => {
    const help = $("#keyhelp");
    if (help && help.open) { if (ev.key === "?") { ev.preventDefault(); help.close(); } return; }  // Esc: the dialog's own
    if (document.querySelector("dialog[open]")) return;  // the mail composer: nothing behind it takes a key
    const page = AO.keyPage(location.pathname);
    if (ev.key === "Escape" && ev.target && ev.target.matches && ev.target.matches("#filter, #ifilter")) { ev.target.blur(); return; }
    const name = AO.keyName(ev);
    if (name === null) return;
    if (gUntil) {
      const live = Date.now() < gUntil; gUntil = 0;
      if (live && page === "org" && name.length === 1) { ev.preventDefault(); jumpTeam(name); return; }
    }
    // Enter on a focused button or link is that button's own press, never the ringed card's
    if ((name === "Enter" || name === "Shift+Enter") && ev.target && ev.target.closest && ev.target.closest("button, a, summary")) return;
    // the digits yield to a ringed row that has answer buttons (§4.5a **keys**: the ring, TD-255)
    const answers = page === "inbox" && /^[1-4]$/.test(name) ? AO.keyAnswers(ringed(page)) : [];
    const k = AO.keyEntry(page, name, answers.length > 0);
    if (!k || (k.nth && !answers.length)) return;  // a digit on a row without answers is nobody's
    ev.preventDefault();
    if (k.nth) { const a = answers[Number(name) - 1]; if (a && !a.disabled) a.click(); return; }
    if (k.help) return keyHelp();
    if (k.g) { gUntil = Date.now() + 2000; return; }
    if (k.step) return AO.entryStep(k.step);
    if (k.move) {
      const all = ringables(page), cur = ringed(page), i = all.indexOf(cur);
      if (i < 0 && page === "org") {
        // the ring on a header just opened is no longer a stop: move from where it stands
        const at = document.activeElement && document.activeElement.closest && document.activeElement.closest("#groups .ghead");
        if (at) {
          const after = (el) => at.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING;
          return ringTo(k.move > 0 ? all.find(after) : all.filter((el) => !after(el)).pop());
        }
      }
      return ringTo(i < 0 ? all[0] : all[Math.min(Math.max(i + k.move, 0), all.length - 1)]);
    }
    let root = document;
    if (k.ring) { root = page === "msg" ? $(".msgentry") : ringed(page) || (k.fold && ringedHead()); if (!root) return; }
    // a team's fold by key (TD-194): `f` on a card folds its team and rings the header; `f` or
    // `Enter` on a ringed header opens or folds it, the ring staying on the header
    if (page === "org" && (k.fold || name === "Enter") && root.matches && root.matches(".ghead")) {
      toggleFold(root.parentElement); root.focus({ preventScroll: true }); return;
    }
    if (k.fold) {
      const sec = root.closest(".tgroup"), head = sec && $(".ghead", sec);
      if (!head || !$(".fold", head)) return;
      toggleFold(sec); ringTo(head); return;
    }
    let el = k.ring ? AO.keyControl(root, k, RINGS[page]) || (k.alt && AO.keyControl(root, k.alt, RINGS[page])) : $(k.sel);
    // a compact card's permission is answered in its team's facet (§4.5a *card: compact*, TD-176):
    // `a` / `d` on the ringed card press that facet's Allow / Deny for it
    if (!el && k.ring && page === "org" && root && root.classList.contains("compact") && /data-act="(allow|deny)"/.test(k.sel)) {
      const sec = root.closest(".tgroup");
      el = sec && $$(`.tsum ${k.sel}`, sec).find((b) => b.dataset.id === root.dataset.id && !b.disabled);
    }
    if (!el) return;
    if (k.focus) { el.focus(); return; }
    el.click();
    // Snooze ▾ opens its menu; the choice is a second press, so the focus goes to its first entry
    const menu = el.tagName === "SUMMARY" && el.parentElement;
    if (menu && menu.open) { const first = $(".menu button", menu); if (first) first.focus(); }
  });

  // The top bar is on every page and its chips are rendered server-side, so the fit is set up here
  // rather than in any one page's init (the script tag is at the end of the body: the DOM is up).
  window.addEventListener?.("resize", fitUsage);  // `?.`: the node probe of test_ui_inbox has no real window
  fitUsage();
  AO.holdBar();
  // design §4.5a the ***i*** mark (TD-157, built by TD-167): the team card's, the Focus header's and
  // the exited banner's. One delegated press for all of them — a header or a banner is redrawn by
  // the stream, which would drop a listener bound to the button — and which are open is this
  // browser's memory, as the Inbox's marks are; a redraw puts it back (`applyHelpMarks`).
  const HELP_OPEN = (id) => "helpmark:" + id;
  AO.applyHelpMarks = function (root) {
    $$(".helpmark", root || document).forEach((b) => {
      const p = document.getElementById(b.dataset.info); if (!p) return;
      const on = !!store.get(HELP_OPEN(b.dataset.info), false);
      p.hidden = !on; b.setAttribute("aria-expanded", on ? "true" : "false");
    });
  };
  document.addEventListener?.("click", (e) => {
    const b = e.target.closest && e.target.closest(".helpmark"); if (!b) return;
    e.preventDefault(); e.stopPropagation();
    const p = document.getElementById(b.dataset.info); if (!p) return;
    const on = p.hidden;
    p.hidden = !on; b.setAttribute("aria-expanded", on ? "true" : "false");
    store.set(HELP_OPEN(b.dataset.info), on);
  });
  AO.applyHelpMarks();
  // ---- the Settings page (design §4.5 screen 8, §4.5a *Settings page*; TD-148) ----
  // A reserve's line before the press lands, by the gate's own arithmetic (§6 *Usage gate*,
  // `sessionorc.settings.line`): `100 − n`, or `100 − n × days left` for `n/day`, days left counted
  // up to the window's reset. Pure, so the tests hold it to the server's cases.
  AO.reserveLine = function (text, resets, now) {
    const t = String(text || "").trim();
    if (!t) return { line: null, says: "no line" };
    const m = /^(\d+)\s*(\/day)?$/.exec(t);
    if (!m) return { error: "a reserve is a whole percent (30) or a percent per day (10/day)" };
    const n = Number(m[1]);
    if (n > 100) return { error: "a reserve is a whole percent from 0 to 100" };
    if (!m[2]) return { line: Math.max(0, 100 - n), says: `→ line ${Math.max(0, 100 - n)}%` };
    const at = resets ? Date.parse(resets) : NaN;
    if (!Number.isFinite(at)) return { line: null, says: "no line — the window reports no reset" };
    const left = Math.max(1, Math.ceil((at - (now || Date.now())) / 86400000));
    const line = Math.max(0, Math.min(100, 100 - n * left));
    return { line, says: `→ line ${line}% · ${left} day${left === 1 ? "" : "s"} left` };
  };
  // A metered card's field (§4.5a *Settings page: Usage*): an amount, `$5` or `20M tok`, or empty to
  // clear it; a percent is refused by naming the billing, as `set_settings` refuses it. The spend
  // beside the field stays until the press lands.
  AO.amountSays = function (text) {
    const t = String(text || "").trim();
    if (!t) return { says: "no amount" };
    if (/^\$\s*[\d,]*\.?\d+$/.test(t) || /^\d*\.?\d+\s*[Mm]?\s*tok$/.test(t)) return { says: `→ amount ${t}` };
    return { error: "a metered profile's reserve is an amount ($5, 20M tok), not a percent" };
  };
  // **board items shown** (§4.5a, TD-220 slice 4): the pick and its number as `person.inbox.board_show`
  // — `next:<n>`, `due`, `<n>d`, `all`; a number left empty is the one drawn until typed (10, 7), and
  // one out of range goes to `set_settings`, whose refusal is said in place
  AO.boardShow = function (mode, next, days) {
    const n = (v, dflt) => (String(v || "").trim() === "" ? dflt : String(v).trim());
    if (mode === "next") return `next:${n(next, 10)}`;
    if (mode === "days") return `${n(days, 7)}d`;
    return mode === "due" || mode === "all" ? mode : "next:10";
  };
  AO.settings = function () {
    const page = $("#setpage"); if (!page) return;
    const post = async (section, body) => {
      const r = await fetch(`/api/settings/${section}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      if (!r.ok) { let t = r.statusText; try { t = (await r.json()).detail || t; } catch (e) {} throw new Error(t); }
      return r.json();
    };
    // the refusal, or the *applies on the next tick*, in place on the card (§4.5a: refusals are the RPC's words in place)
    const say = (form, text, bad) => {
      const el = $(".setsaid", form); if (!el) return AO.toast(text, !bad);
      el.textContent = text; el.classList.toggle("warn", !!bad);
    };
    $$(".setcard[data-section='usage'] .setin", page).forEach((inp) => {
      const out = inp.parentElement.querySelector(".setline");
      inp.addEventListener("input", () => {
        const got = inp.dataset.metered ? AO.amountSays(inp.value) : AO.reserveLine(inp.value, inp.dataset.resets);
        out.textContent = got.error || (inp.value.trim() === (inp.defaultValue || "").trim() ? out.dataset.was : got.says);
        out.classList.toggle("warn", !!got.error);
      });
    });
    // the days choice reads *due this week* at 7 and *due within n days* otherwise; typing a number picks its choice
    $$(".setboard input[type=number]", page).forEach((inp) => inp.addEventListener("input", () => {
      const row = inp.closest(".setboard"), pick = inp.closest("label").querySelector("input[type=radio]");
      if (pick) pick.checked = true;
      if (inp.name === "board_days") { const d = inp.value.trim() || "7"; $(".setdayswords", row).textContent = d === "7" ? "due this week" : `due within ${d} days`; }
    }));
    // **balance** (§4.5a): turned on with nothing drawn, the fields start at 10, 2d and ticked; off, they are not the person's to type in
    $$(".setbalance", page).forEach((row) => {
      const f = row.closest("form"), on = f.elements.balance_on, parts = [f.elements.balance_prs, f.elements.balance_oldest, f.elements.balance_review];
      on.addEventListener("change", () => {
        parts.forEach((p) => { p.disabled = !on.checked; });
        if (on.checked && !parts[0].value.trim() && !parts[1].value.trim() && !parts[2].checked) { parts[0].value = "10"; parts[1].value = "2d"; parts[2].checked = true; }
      });
    });
    // the form's balance as `set_settings` takes it, keys in the file's order: null off, a whole number where prs is one
    AO.balanceOf = (f) => {
      if (!f.elements.balance_on.checked) return null;
      const bal = {}, prs = f.elements.balance_prs.value.trim(), oldest = f.elements.balance_oldest.value.trim();
      if (prs) bal.prs = /^[0-9]+$/.test(prs) ? Number(prs) : prs;
      if (oldest) bal.oldest = oldest;
      if (f.elements.balance_review.checked) bal.review = true;
      return bal;
    };
    const forms = {
      usage: (f) => ["usage", { profile: f.dataset.profile, reserves: Object.fromEntries($$(".setin", f).map((i) => [i.name, i.value.trim()])) }],
      max_age: (f) => ["max_age", { max_age: f.elements.max_age.value.trim() }],  // **trust a reading for** (TD-233)
      settle: (f) => ["settle", { settle: f.elements.settle.value.trim() }],  // **settle** (§4.5a, TD-710)
      teams: (f) => {
        const body = { team: f.dataset.team, reserve: f.elements.reserve.value.trim() };
        if (f.elements.until.value.trim()) body.until = f.elements.until.value.trim();
        // **when work appears** (§6 rule 8): written only when the pick moved, so *ask me (default)* leaves the key absent
        const ow = f.elements.on_work; if (ow && ow.value !== ow.dataset.was) body.on_work = ow.value;
        // **balance** (§6 *Balance*): the lines whole, written only when they moved; off is null, an empty field no line
        const row = $(".setbalance", f);
        if (row) { const bal = AO.balanceOf(f); if (JSON.stringify(bal) !== row.dataset.was) body.balance = bal; }
        // **flow** (§4.9c): written only when the pick moved, and nothing more (TD-356)
        const fl = f.elements.flow; if (fl && fl.value !== fl.dataset.was) body.flow = fl.value;
        return ["teams", body];
      },
      you: (f) => {
        const mode = f.elements.open_in.value;
        const open_in = mode === "template" ? { label: f.elements.label.value.trim(), url: f.elements.url.value.trim() } : mode;
        // a template's **file** (TD-536): sent only when written, so an empty field leaves the url's road
        if (mode === "template" && f.elements.file && f.elements.file.value.trim()) open_in.file = f.elements.file.value.trim();
        // **file link** (§4.5a, §5 `person.file_link`, TD-536): the switch and the wait, read by the next file link
        const file_link = f.elements.folder_first ? { folder_first: f.elements.folder_first.checked, wait: f.elements.wait.value === "" ? null : Number(f.elements.wait.value) } : undefined;
        const terminal = { size: f.elements.size.value ? Number(f.elements.size.value) : null, face: f.elements.face.value.trim() || null, copy_on_select: f.elements.copy_on_select.checked };
        // **attachment bound** (TD-478): an empty field clears `person.attach.max`, back to its default
        const attach = { max: f.elements.attach_max ? f.elements.attach_max.value.trim() || null : null };
        // **composer** (§4.5a *Focus composer* **the bar**, TD-500): folded or open, read on the next Focus load
        const composer = f.elements.composer ? f.elements.composer.value : undefined;
        return ["you", { open_in, file_link, terminal, attach, composer, inbox: { board_show: AO.boardShow(f.elements.board_show.value, f.elements.board_next.value, f.elements.board_days.value) } }];
      },
      // **Telegram** (§4.5a **You**, §4.10; TD-319): the three fields whole, an empty one cleared by the route
      // **weights** (§4.5a *Settings page: Usage*, TD-832): the rows whole; the route sends what differs from the default
      spend: (f) => ["spend", { as_of: f.elements.as_of.value.trim(), rows: $$(".setwrows .setweight", f).map((r) => Object.fromEntries($$("input", r).map((i) => [i.name, i.value.trim()]))) }],
      notify: (f) => ["notify", { telegram: { on: f.elements.tg_on.checked, secrets: f.elements.tg_secrets.value.trim(), link: f.elements.tg_link.value.trim() } }],
      // **Sweep** (§4.5a, §4.9b *The switch*, TD-1091): the three fields whole, an empty one cleared by the route
      sweep: (f) => ["sweep", { on: f.elements.sweep_on.checked, every: f.elements.sweep_every.value.trim(), profile: f.elements.sweep_profile.value }],
    };
    // **Save** and **Cancel** (§4.5a *Settings page*, TD-286): Save is pressable, and Cancel shown, only
    // while a field differs from what was drawn; Cancel puts the drawn values back, and a Save makes
    // what was saved the drawn values. A form's `reset()` is exactly *what was drawn*: the defaults.
    const state = (f) => JSON.stringify([...f.elements].filter((el) => el.name).map((el) => (el.type === "checkbox" || el.type === "radio" ? el.checked : el.value)));
    const settle = (f) => {
      const dirty = state(f) !== f.dataset.drawn, save = $(".setsave", f), cancel = $(".setcancel", f);
      if (save) save.disabled = !dirty;
      if (cancel) cancel.hidden = !dirty;
      // **Send a test** sends the saved values, so not while the card holds others (§4.5a **You**: **Telegram**)
      const test = $(".settgtest", f); if (test) { test.disabled = dirty; test.title = dirty ? "save first: a test sends the saved values" : test.dataset.title || test.title; }
    };
    const drawn = (f) => {
      for (const el of f.elements) {
        if (el.type === "checkbox" || el.type === "radio") el.defaultChecked = el.checked;
        else if (el.tagName === "SELECT") for (const o of el.options) o.defaultSelected = o.selected;
        else if ("defaultValue" in el) el.defaultValue = el.value;
      }
      // the line beside a saved field is the saved value's now
      $$(".setline", f).forEach((out) => { if (!out.classList.contains("warn")) out.dataset.was = out.textContent; });
      f.dataset.drawn = state(f); settle(f);
    };
    // **weights**' **+ model** and **×** (TD-832): rows come and go, so Cancel puts back the rows as drawn
    const wrows = $("#setweights .setwrows", page);
    if (wrows) {
      wrows.dataset.drawn = wrows.innerHTML;
      const wf = wrows.closest("form");
      $(".setwadd", wf).addEventListener("click", () => {
        wrows.append($("#setwrow", wf).content.cloneNode(true));
        $$(".setweight", wrows).at(-1).querySelector("input").focus(); settle(wf);
      });
      wf.addEventListener("click", (e) => { const x = e.target.closest(".setwx"); if (x) { x.closest(".setweight").remove(); settle(wf); } });
    }
    $$("form.setcard", page).forEach((f) => {
      f.dataset.drawn = state(f); settle(f);
      const said = $(".setsaid", f); if (said) said.dataset.was = said.textContent;
      f.addEventListener("input", () => settle(f));
      f.addEventListener("change", () => settle(f));
      const cancel = $(".setcancel", f);
      if (cancel) cancel.addEventListener("click", () => {
        f.reset();
        // what the drawn values show beside them, redrawn without the handlers' side effects
        $$(".setline", f).forEach((out) => { out.textContent = out.dataset.was; out.classList.remove("warn"); });
        const said = $(".setsaid", f); if (said) { said.textContent = said.dataset.was; said.classList.remove("warn"); }
        $$(".setbalance", f).forEach((row) => {
          const on = f.elements.balance_on.checked;
          [f.elements.balance_prs, f.elements.balance_oldest, f.elements.balance_review].forEach((x) => { x.disabled = !on; });
        });
        $$(".setdayswords", f).forEach((w) => { const d = (f.elements.board_days.value || "").trim() || "7"; w.textContent = d === "7" ? "due this week" : `due within ${d} days`; });
        if (f.elements.open_in && $("#settemplate")) $("#settemplate").classList.toggle("hidden", f.elements.open_in.value !== "template");
        if (f.elements.open_in && $("#setfilelink")) $("#setfilelink").classList.toggle("hidden", f.elements.open_in.value === "none");
        if (f.elements.folder_first) f.elements.wait.disabled = !f.elements.folder_first.checked;
        if (f.id === "setweights") wrows.innerHTML = wrows.dataset.drawn;
        settle(f);
      });
    });
    page.addEventListener("submit", async (e) => {
      const f = e.target.closest("form.setcard"); if (!f || !forms[f.dataset.section]) return;
      e.preventDefault();
      const [section, body] = forms[f.dataset.section](f);
      try {
        const got = await post(section, body);
        // the weights the home now reads, drawn again: a row put back at its default, the defaults marked
        // — unless another card holds edits not yet saved, which a reload would throw away
        if (section === "spend" && !$$("form.setcard", page).some((o) => o !== f && o.dataset.drawn !== state(o))) { location.reload(); return; }
        drawn(f);
        say(f, page.dataset.setAt ? `saved at ${page.dataset.setAt} · applies on the next tick` : "saved · applies on the next tick");
        // **flow** writes and nothing more (§4.5a, TD-356): the toast says whether Apply is needed
        const ap = (got && got.pick) || null;
        if (ap) AO.flowSet(body.team, ap);
        if (section === "you" && AO.termChan) { AO.termChan.postMessage(body.terminal); AO.setTermLook(body.terminal); }
        if (ap && f.elements.flow) f.elements.flow.dataset.was = body.flow;  // saved: a second Save does not send it again
        // the stop time is drawn in this host's clock by the server; a switch's toasts are read first
        if (section === "teams") setTimeout(() => location.reload(), ap ? 4000 : 600);
      } catch (err) { say(f, err.message, true); }
    });
    page.addEventListener("click", async (e) => {
      const clear = e.target.closest("[data-clear='until']"); if (!clear) return;
      const f = clear.closest("form.setcard");
      try { await post("teams", { team: f.dataset.team, until: null }); location.reload(); } catch (err) { say(f, err.message, true); }
    });
    $$(".setauto", page).forEach((box) => box.addEventListener("change", async () => {
      const card = box.closest(".setcard");
      try {
        await post("repos", { repo: card.dataset.repo, auto: box.checked });
        box.parentElement.querySelector(".note").textContent = box.checked ? "on: the home promotes 10 min after main moves" : "off: the Inbox row offers the press";
        AO.toast(`${card.dataset.repo}: promote ${box.checked ? "auto" : "by hand"} · applies on the next tick`, true);
      } catch (err) { box.checked = !box.checked; AO.toast(`not saved: ${err.message}`); }
    }));
    // **pull** (§4.5a *Settings page: Repos*, §6 *Pull*, TD-263): on every card, block or not
    $$(".setpull", page).forEach((box) => box.addEventListener("change", async () => {
      const card = box.closest(".setcard");
      try {
        await post("repos", { repo: card.dataset.repo, pull: box.checked });
        box.parentElement.querySelector(".note").textContent = box.checked ? "on: the home fast-forwards this checkout when git allows and no session in it is mid-turn" : "off: the checkout is left to you";
        AO.toast(`${card.dataset.repo}: pull ${box.checked ? "on" : "off"} · applies on the next pass`, true);
      } catch (err) { box.checked = !box.checked; AO.toast(`not saved: ${err.message}`); }
    }));
    // **sync** (§4.5a *Settings page: Repos*, §6 *Sync*, TD-685): on every card; the verdict is the next pass's
    $$(".setsync", page).forEach((box) => box.addEventListener("change", async () => {
      const card = box.closest(".setcard");
      try {
        await post("repos", { repo: card.dataset.repo, sync: box.checked });
        box.parentElement.querySelector(".note").textContent = box.checked ? "on: the home merges a mechanical agent-cadence sync PR" : "off: every sync PR is the team's";
        const read = box.parentElement.querySelector(".setsyncread");  // drawn on every card, hidden when empty
        if (read) { read.textContent = box.checked ? "" : "off"; read.hidden = box.checked; }
        AO.toast(`${card.dataset.repo}: sync ${box.checked ? "on" : "off"} · applies on the next pass`, true);
      } catch (err) { box.checked = !box.checked; AO.toast(`not saved: ${err.message}`); }
    }));
    // the **Sweep** card's per-repo **swept** switch (§4.5a, TD-1091): saved on its own press, as **pull** is;
    // what sweeps the repo is the next page's reading, so the line says only what the press changed
    $$(".setsweep", page).forEach((box) => box.addEventListener("change", async () => {
      const line = box.closest(".setsweepline");
      try {
        await post("repos", { repo: line.dataset.repo, sweep: box.checked });
        box.defaultChecked = box.checked;  // saved: the card's Cancel (a form reset) keeps it as pressed
        $(".setsweepwhat", line).textContent = box.checked ? "on · what sweeps it shows on the next load" : "off";
        AO.toast(`${line.dataset.repo}: sweep ${box.checked ? "on" : "off"} · applies on the next tick`, true);
      } catch (err) { box.checked = !box.checked; AO.toast(`not saved: ${err.message}`); }
    }));
    // **Send a test** (§4.5a **You**: **Telegram**, §4.10): `notify_test` at the home, its result in words beside the button
    $$(".settgtest", page).forEach((b) => {
      b.dataset.title = b.title;
      b.addEventListener("click", async () => {
        const out = $(".settgsaid", b.closest("form"));
        b.disabled = true; out.textContent = "sending…"; out.classList.remove("warn");
        try {
          const got = await post("notify_test", {});
          const at = got.at ? new Date(got.at) : null, clock = at && !isNaN(at) ? at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
          out.textContent = got.sent ? `sent ${clock} — look for it on your phone` : got.result || "the send failed";
          out.classList.toggle("warn", !got.sent);
        } catch (err) { out.textContent = err.message; out.classList.add("warn"); }
        settle(b.closest("form"));
      });
    });
    const openin = $("#setopenin");
    if (openin) openin.addEventListener("change", () => {
      $("#settemplate").classList.toggle("hidden", openin.value !== "template");
      const fl = $("#setfilelink"); if (fl) fl.classList.toggle("hidden", openin.value === "none");
    });
    // **file link**'s wait is disabled with the switch off (§4.5a *Settings page: You, file link*, TD-536)
    const first = $("#setyou") && $("#setyou").elements.folder_first;
    if (first) first.addEventListener("change", () => { $("#setyou").elements.wait.disabled = !first.checked; });
    // *this browser* (§4.5a): what it holds, each set by its own control; Reset clears every `ao.*` key
    $$("#setbrowser [data-key]", page).forEach((dd) => {
      const v = store.get(dd.dataset.key, null);
      dd.textContent = v === null ? "not set" : typeof v === "boolean" ? (v ? "on" : "off") : String(v);
    });
    $("#setreset").addEventListener("click", () => {
      if (!confirm("Reset this browser? Every ao.* key this browser keeps — the theme, the folds, the filters, the pop-out windows — is cleared, and the page reloads. Nothing anywhere else changes.")) return;
      try { Object.keys(localStorage).filter((k) => k.startsWith("ao.")).forEach((k) => localStorage.removeItem(k)); } catch (e) {}
      location.reload();
    });
  };
  function esc(t) { return String(t == null ? "" : t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
})();
