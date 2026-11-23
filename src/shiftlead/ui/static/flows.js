// The Flows page (design §4.9c *The Flows page*, §4.5a *Flows page*, TD-2054). The page edits the flow's parsed
// `flow.yml` in the browser; whether it flows, and the file Save writes, are always the host agent's (`flow_check`),
// so there is one check and one writer. Save and Delete go through `flow_save`, the person's own act.
(function () {
  const page = document.getElementById("flowspage");
  if (!page) return;
  const data = JSON.parse(document.getElementById("flowsdata").textContent);
  const OUT = {
    design: ["work-pushed", "no-design-needed"],
    build: ["work-pushed", "design-needs-changing", "not-needed"],
    review: ["ship", "changes-wanted"],
  };
  const KIND = {
    design: ["Design", "Writes the design for an entry and files the builds it needs."],
    build: ["Build", "Writes the code, tests or documents for an entry, on the entry's branch."],
    review: ["Review", "Reads the pushed work, whatever it holds, and gives a verdict."],
    audit: ["Audit", "Starts on a clock, looks for problems in the area its brief names, and files what it finds."],
  };
  const FIXED = ["person", "done", "merge"], CAN_MERGE = ["work-pushed", "ship"];
  const TAKES = [["", "only what other stages send it"], ["design-first", "new entries that need a design first"],
    ["other", "new entries that are ready to build"], ["any", "new entries of both those kinds"]];
  const UNITS = [["merged-pull-requests", "merged pull requests"], ["hours", "hours"], ["days", "days"]];
  const CHECKED = {
    "work-pushed": "its pull request is open; its checks are green, unless a later Build stage finishes the work",
    ship: "a verdict is recorded on the latest push", "changes-wanted": "a verdict is recorded",
  };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const keyOf = (n) => String(n == null ? "" : n).trim().toLowerCase().replace(/ /g, "-");
  const words = (o) => o.replace(/-/g, " ");
  const ordinal = (n) => { const v = n % 100, s = ["th", "st", "nd", "rd"]; return n + (s[(v - 20) % 10] || s[v] || s[0]); };
  const copy = (x) => JSON.parse(JSON.stringify(x));
  const clean = (doc) => JSON.parse(JSON.stringify(doc, (k, v) => (k.startsWith("$") ? undefined : v)));
  const idOf = (r) => `${r.place}/${r.repo || ""}/${r.name}`;
  const remember = (r) => { if (r.doc && r.place === "own" && r.version) (r.doc.stages || []).forEach((s) => { s.$was = keyOf(s.name); }); };

  const S = { rows: data.flows || [], sel: null, tab: "stages", open: null, brief: null, walk: null, del: false, pending: false, seq: 0, timer: 0, check: null };
  S.rows.forEach(remember);
  const cur = () => S.rows.find((r) => idOf(r) === S.sel) || null;
  const editable = (r) => !!(r && r.place === "own" && r.doc);
  const stagesOf = (r) => (r && r.doc && Array.isArray(r.doc.stages) ? r.doc.stages : []);
  const auditsOf = (r) => (r && r.doc && Array.isArray(r.doc.audits) ? r.doc.audits : []);
  const say = (t) => { const el = document.getElementById("flowsaid"); el.textContent = t || ""; el.hidden = !t; };

  function select(r) {
    S.sel = r ? idOf(r) : null; S.tab = r && !r.doc ? "file" : "stages"; S.open = null; S.brief = null; S.walk = null; S.del = false;
    S.check = r ? { problems: r.problems || [], info: r.info || [], text: r.text || "" } : null;
    S.pending = false; S.seq++; clearTimeout(S.timer);
    if (r && r.place === "own" && r.doc && !r.version) ask();
  }

  // ---- a destination, as the file writes it and as the page reads it
  function nd(v) {
    if (v === undefined || v === null) return { to: "person" };
    if (typeof v === "string") return { to: FIXED.includes(v) ? v : keyOf(v) };
    const to = typeof v.to === "string" ? (FIXED.includes(v.to) ? v.to : keyOf(v.to)) : "person";
    const d = { to };
    if (v.limit) d.limit = v.limit;
    if (v.answers) d.answers = v.answers;
    if (v.refused !== undefined) d.refused = nd(v.refused);
    return d;
  }
  function raw(d) {
    if (d.to === "person") return d.answers && Object.keys(d.answers).length ? { to: "person", answers: d.answers } : "person";
    if (d.to === "merge") { const r = raw(d.refused || { to: "person" }); return r === "person" ? "merge" : { to: "merge", refused: r }; }
    return d.limit ? { to: d.to, limit: d.limit } : d.to;
  }
  function put(s, o, d) { const v = raw(d); if (v === "person") delete s[o]; else s[o] = v; }
  const outs = (s) => (OUT[s.does] || []).concat("other");
  function renameIn(v, old, now) {
    if (typeof v === "string") return keyOf(v) === old && !FIXED.includes(v) ? now : v;
    if (!v || typeof v !== "object") return v;
    const out = { ...v };
    if (typeof out.to === "string" && !FIXED.includes(out.to) && keyOf(out.to) === old) out.to = now;
    if (out.refused !== undefined) out.refused = renameIn(out.refused, old, now);
    if (out.answers) out.answers = Object.fromEntries(Object.entries(out.answers).map(([k, a]) => [k, keyOf(a) === old ? now : a]));
    return out;
  }

  // ---- the check is the host agent's
  function ask() {
    clearTimeout(S.timer); S.pending = true;
    S.timer = setTimeout(run, 200);
  }
  async function run() {
    const r = cur(); if (!r || !r.doc) return;
    const seq = ++S.seq;
    try {
      const got = await post("/api/flows/check", { name: r.name, doc: clean(r.doc), version: r.version || null });
      if (seq !== S.seq) return;
      S.check = { problems: got.problems || [], info: got.info || [], text: got.text || "" };
    } catch (e) {
      if (seq !== S.seq) return;
      S.check = { problems: [`the check did not answer: ${e.message}`], info: [], text: S.check ? S.check.text : "" };
    }
    S.pending = false; render();
  }
  async function post(path, body) {
    const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) { let t = res.statusText; try { t = (await res.json()).detail || t; } catch (e) { /* the status says it */ } throw new Error(t); }
    return res.json();
  }
  const touched = () => { say(""); ask(); render(); };

  // A problem is drawn on the row it is about, in the check's words: `<name>: \`<outcome>…`.
  function problemsOf(name) { const at = `${name}: `; return (S.check ? S.check.problems : []).filter((p) => p.startsWith(at)).map((p) => p.slice(at.length)); }
  const outcomeOf = (msg) => { const m = /^`([a-z-]+)/.exec(msg); return m ? m[1] : null; };

  // ---- the left column
  function drawList() {
    const f = cur();
    const item = (r) => `<button type="button" class="fl${r === f ? " on" : ""}" data-act="pick" data-id="${esc(idOf(r))}">${esc(r.name)}${(r.problems || []).length ? ' <span class="dot" title="has problems">●</span>' : ""}<small>${r.place === "repo" ? esc(r.repo) : r.doc ? esc(`${stagesOf(r).length} stages`) : "first shape"}</small></button>`;
    const of = (p) => S.rows.filter((r) => r.place === p);
    let h = "<h4>Built in</h4>" + of("builtin").map(item).join("");
    h += "<h4>Yours</h4>" + (of("own").map(item).join("") || '<p class="note">None yet. Copy a built-in flow to start.</p>');
    if (of("repo").length) h += "<h4>In a repo</h4>" + of("repo").map(item).join("");
    h += `<button type="button" class="btn sm ghost" data-act="new" title="${esc(page.dataset.helpNew)}">+ New flow</button>`;
    if (editable(f)) {
      const after = stagesOf(f)[openIdx(f)];
      h += `<h4>Kinds of stage</h4><p class="note">Click one to add a stage${after ? ` after <b>${esc(after.name)}</b>` : ""}, or drag it to where it belongs.</p>`;
      h += ["design", "build", "review"].map((k) => `<button type="button" class="pal k-${k}" draggable="true" data-pal="${k}" data-act="palette" data-k="${k}">${KIND[k][0]}<small>${esc(KIND[k][1])}</small></button>`).join("");
    }
    document.getElementById("fllist").innerHTML = h;
  }
  const openIdx = (f) => { const n = stagesOf(f).length; return S.open === null || S.open >= n ? n - 1 : S.open; };

  // ---- one outcome's Next
  function nextCell(f, s, si, o, msg) {
    const d = nd(s[o]);
    if (!editable(f)) {
      const name = (x) => (x.to === "person" ? '<span class="flyou">you</span>' : x.to === "merge" ? "merge it" : `→ <span class="flkey">${esc(x.to)}</span>`);
      const lim = (x) => (x.limit ? `<small>up to <b>${x.limit}</b> times; the ${ordinal(x.limit + 1)} comes to you</small>` : "");
      const ans = (x) => (x.answers ? `<small>answers: ${Object.entries(x.answers).map(([l, a]) => `${esc(l)} → ${esc(keyOf(a))}`).join(", ")}</small>` : "");
      if (d.to === "merge") { const e = d.refused || { to: "person" }; return `${name(d)}<small>if the merge is refused: ${name(e)}</small>${lim(e)}${ans(e)}`; }
      return name(d) + lim(d) + ans(d);
    }
    const pick = (x, sub) => {
      const opts = [["person", "you"]];
      if (!sub && CAN_MERGE.includes(o)) opts.push(["merge", "merge it"]);
      stagesOf(f).forEach((y, j) => { const k = keyOf(y.name); opts.push([k, j === si ? "this stage again, with a fresh session" : k]); });
      if (!opts.some(([v]) => v === x.to)) opts.push([x.to, `${x.to} (missing)`]);
      let h = `<select id="nx-${si}-${o}-${sub}" class="input${msg ? " bad" : ""}" data-act="dest" data-si="${si}" data-o="${o}" data-sub="${sub}" aria-label="${sub ? "If the merge is refused" : `Next for ${words(o)}`}">` + opts.map(([v, t]) => `<option value="${esc(v)}"${v === x.to ? " selected" : ""}>${esc(t)}</option>`).join("") + "</select>";
      if (!FIXED.includes(x.to)) h += `<small>up to <input type="number" min="1" class="input" id="lm-${si}-${o}-${sub}" data-act="limit" data-si="${si}" data-o="${o}" data-sub="${sub}" value="${x.limit || ""}" aria-label="Limit"> times${x.limit ? `; the ${ordinal(x.limit + 1)} comes to you` : " (no limit)"}</small>`;
      if (x.to === "person") h += answersEdit(f, x, si, o, sub);
      return h;
    };
    return d.to === "merge" ? `${pick(d, 0)}<small>if the merge is refused:</small>${pick(d.refused || { to: "person" }, 1)}` : pick(d, 0);
  }
  // A move to the person can offer answers that each name a stage (§4.9c *Where an outcome goes*).
  function answersEdit(f, x, si, o, sub) {
    const rows = Object.entries(x.answers || {}).map(([label, to], n) => {
      const key = keyOf(to), names = stagesOf(f).map((y) => keyOf(y.name));
      const opts = names.includes(key) ? names : [...names, key];
      return `<span class="flans"><input class="input" id="al-${si}-${o}-${sub}-${n}" data-act="anslabel" data-si="${si}" data-o="${o}" data-sub="${sub}" data-n="${n}" value="${esc(label)}" aria-label="Answer"><select class="input" id="at-${si}-${o}-${sub}-${n}" data-act="ansto" data-si="${si}" data-o="${o}" data-sub="${sub}" data-n="${n}" aria-label="Where this answer goes">${opts.map((k) => `<option value="${esc(k)}"${k === key ? " selected" : ""}>${esc(k)}</option>`).join("")}</select><button type="button" class="fllink" data-act="ansdel" data-si="${si}" data-o="${o}" data-sub="${sub}" data-n="${n}" aria-label="Remove this answer">remove</button></span>`;
    }).join("");
    return `${rows}<small><button type="button" class="fllink" data-act="ansadd" data-si="${si}" data-o="${o}" data-sub="${sub}">+ an answer that names a stage</button></small>`;
  }
  const getSub = (s, o, sub) => { const d = nd(s[o]); return sub ? d.refused || { to: "person" } : d; };
  const setSub = (s, o, sub, x) => { if (!sub) return put(s, o, x); const d = nd(s[o]); d.refused = x; put(s, o, d); };

  function briefPanel(f, x, kind, at) {
    const offered = (data.briefs || {})[kind] || [], ro = !editable(f);
    const name = x.brief || (kind === "audit" ? "" : kind);
    const b = offered.find((o) => o.name === name);
    let h = '<div class="flbrief"><b>What the session is told</b> ';
    if (ro) h += `<span class="note">${esc(name || "no brief")}</span>`;
    else {
      const list = b || !name ? offered : [...offered, { name, source: "this flow's" }];
      h += `<select class="input" id="bp-${at}" data-act="bpick" data-at="${at}" aria-label="Brief">${name ? "" : '<option value="" selected disabled>choose a brief</option>'}${list.map((o) => `<option value="${esc(o.name)}"${o.name === name ? " selected" : ""}>${esc(o.name)}${o.source === "own" ? " (yours)" : o.source === "standard" ? "" : " (this flow's)"}</option>`).join("")}</select> <a class="fllink" href="/briefs">all briefs</a>`;
    }
    h += b ? `<pre>${esc(b.text)}</pre>` : name ? '<p class="note">This brief is in the flow\'s own directory.</p>' : "";
    if (ro) h += x.also ? `<p><b>Also:</b> ${esc(x.also)}</p>` : "";
    else h += `<p><b>Also</b> <span class="note">added after the brief, for this ${kind === "audit" ? "audit" : "stage"} only</span></p><textarea class="input" id="also-${at}" data-act="also" data-at="${at}" aria-label="Also">${esc(x.also || "")}</textarea>`;
    return `${h}</div>`;
  }

  function modelPick(f, x, id, at) {
    if (!editable(f)) return `<span class="mono">${esc(x.model)}</span>`;
    const ms = data.models || [], list = ms.includes(x.model) || !x.model ? ms : [...ms, x.model];
    return `<select class="input mono" id="${id}" data-act="model" data-at="${at}" aria-label="Model">${x.model ? "" : '<option value="" selected disabled>choose</option>'}${list.map((m) => `<option${m === x.model ? " selected" : ""}>${esc(m)}</option>`).join("")}</select>`;
  }

  function stageCard(f, s, si, num) {
    const ro = !editable(f), k = OUT[s.does] ? s.does : "build", at = `s${si}`, errs = problemsOf(s.name);
    const up = ro ? "" : `<button type="button" data-act="up" data-si="${si}" aria-label="Move up" title="Move up">▲</button><button type="button" data-act="down" data-si="${si}" aria-label="Move down" title="Move down">▼</button>`;
    let h = `<div class="flrec k-${k}${errs.length ? " err" : ""}${!ro && openIdx(f) === si ? " open" : ""}" data-drop="${si}"><div class="n">${num}${up}</div><div class="who">`;
    h += ro ? `<div class="nm">${esc(s.name)}</div>` : `<input type="text" class="input nm" id="sn-${si}" data-act="sname" data-si="${si}" value="${esc(s.name)}" aria-label="Stage name">`;
    h += `<span class="slug">Stage: ${esc(keyOf(s.name))}</span><dl><dt>Does</dt><dd>`;
    h += ro ? esc(KIND[k][0]) : `<select class="input" id="sk-${si}" data-act="kind" data-si="${si}" aria-label="Kind of work">${["design", "build", "review"].map((x) => `<option value="${x}"${x === s.does ? " selected" : ""}>${KIND[x][0]}</option>`).join("")}</select>`;
    h += `</dd><dt>Model</dt><dd>${modelPick(f, s, `sm-${si}`, at)}</dd>`;
    const can = k === "review" ? [""] : ["", "design-first", "other", "any"], now = s.takes || "";
    const tk = TAKES.filter((t) => can.includes(t[0]) || t[0] === now);
    h += "<dt>Takes</dt><dd>" + (ro || tk.length < 2 ? esc((TAKES.find((t) => t[0] === now) || [0, now])[1]) : `<select class="input" id="st-${si}" data-act="takes" data-si="${si}" aria-label="Takes">${tk.map(([v, t]) => `<option value="${v}"${v === now ? " selected" : ""}>${esc(t)}</option>`).join("")}</select>`) + "</dd>";
    if (k === "review") {
      const on = s["only-when"] ? "protected-files" : "", opts = [["", "every time"], ["protected-files", "only when the work touches protected files"]];
      h += "<dt>Runs</dt><dd>" + (ro ? esc(opts.find((t) => t[0] === on)[1]) : `<select class="input" id="so-${si}" data-act="only" data-si="${si}" aria-label="Runs">${opts.map(([v, t]) => `<option value="${v}"${v === on ? " selected" : ""}>${esc(t)}</option>`).join("")}</select>`) + "</dd>";
    }
    h += "</dl>";
    if (!ro) h += `<p><button type="button" class="btn sm ghost" data-act="delstage" data-si="${si}">Remove stage</button></p>`;
    h += `</div><div class="ends"><div class="flahead"><b>${esc(KIND[k][0])}</b><span>${esc(KIND[k][1])}${s["only-when"] ? " Passed without a session, counting as ship, when no protected file is touched." : ""}</span><button type="button" class="fllink" data-act="brief" data-at="${at}">${S.brief === at ? "hide brief" : "brief"}</button></div>`;
    if (S.brief === at) h += briefPanel(f, s, k, at);
    h += '<div class="flhrow"><span>Outcome</span><span>Checked first</span><span>Next</span></div>';
    const placed = new Set();
    outs(s).forEach((o) => {
      const e = errs.find((m) => outcomeOf(m) === o);
      errs.forEach((m) => { if (outcomeOf(m) === o) placed.add(m); });
      h += `<div class="flerow${e ? " err" : ""}"><span>${esc(words(o))}${o === "other" ? ' <span class="note">(when none of the above fits)</span>' : ""}</span><span class="ck">${esc(CHECKED[o] || "a reason is given")}</span><span class="to">${nextCell(f, s, si, o, e)}</span>${e ? `<span class="flwhy">${esc(e)}</span>` : ""}</div>`;
    });
    errs.filter((m) => !placed.has(m)).forEach((m) => { h += `<div class="flwhy">${esc(m)}</div>`; });
    return `${h}</div></div>`;
  }

  function auditCard(f, a, ai) {
    const ro = !editable(f), at = `a${ai}`, errs = problemsOf(a.name), m = /^(\d+) (.+)$/.exec(String(a.every || "")) || [0, "", "days"];
    let h = `<div class="flrec k-audit${errs.length ? " err" : ""}"><div class="n"></div><div class="who">`;
    h += ro ? `<div class="nm">${esc(a.name)}</div>` : `<input type="text" class="input nm" id="an-${ai}" data-act="aname" data-ai="${ai}" value="${esc(a.name)}" aria-label="Audit name">`;
    h += `<dl><dt>Model</dt><dd>${modelPick(f, a, `am-${ai}`, at)}</dd><dt>Starts</dt><dd>every `;
    h += ro ? `<b>${esc(m[1])}</b> ${esc((UNITS.find((u) => u[0] === m[2]) || [0, m[2]])[1])}` : `<input type="number" min="1" class="input" id="ae-${ai}" data-act="every" data-ai="${ai}" value="${esc(m[1])}" aria-label="Every"> <select class="input" id="au-${ai}" data-act="unit" data-ai="${ai}" aria-label="Unit">${UNITS.map(([v, t]) => `<option value="${v}"${v === m[2] ? " selected" : ""}>${t}</option>`).join("")}</select>`;
    h += "</dd></dl>";
    if (!ro) h += `<p><button type="button" class="btn sm ghost" data-act="delaudit" data-ai="${ai}">Remove audit</button></p>`;
    h += `</div><div class="ends"><div class="flahead"><b>Audit</b><span>${esc(KIND.audit[1])}</span><button type="button" class="fllink" data-act="brief" data-at="${at}">${S.brief === at ? "hide brief" : "brief"}</button></div>`;
    if (S.brief === at) h += briefPanel(f, a, "audit", at);
    errs.forEach((e) => { h += `<div class="flwhy">${esc(e)}</div>`; });
    return `${h}</div></div>`;
  }

  function drawStages(f) {
    let h = stagesOf(f).map((s, i) => stageCard(f, s, i, i + 1)).join("");
    if (editable(f)) h += `<p><select class="input" id="addst" data-act="addstage" aria-label="Add a stage"><option value="">+ Add a stage</option>${["design", "build", "review"].map((k) => `<option value="${k}">${KIND[k][0]}</option>`).join("")}</select></p>`;
    h += '<h3>Audits</h3><p class="note">Each starts on its own clock, looks where its brief says, and files what it finds as new entries. It takes no entry through the stages above.</p>';
    h += auditsOf(f).map((a, i) => auditCard(f, a, i)).join("") || '<p class="note">None.</p>';
    if (editable(f)) h += '<p><button type="button" class="btn sm" data-act="addaudit">+ Add an audit</button></p>';
    return h;
  }

  function drawChecks(f) {
    const c = S.check || { problems: [], info: [] };
    const warns = c.info.filter((i) => i.startsWith("warning: ")).map((i) => i.slice(9));
    const rest = c.info.filter((i) => !i.startsWith("warning: ") && !/goes to the person on|an entry goes to the person after|an audit on its clock/.test(i));
    let asks = 0;
    stagesOf(f).forEach((s) => outs(s).forEach((o) => { const d = nd(s[o]); if (d.to === "person" || (d.to === "merge" && (!d.refused || d.refused.to === "person"))) asks++; }));
    let h = '<h3>Does it flow?</h3><div class="flchk">';
    h += c.problems.length ? c.problems.map((p) => `<div class="flbad">✗ ${esc(p)}</div>`).join("") : '<div class="flok">✓ Every stage a Next names exists, every loop has a limit, all pushed work can reach a merge or you, and every kind of entry has one way in.</div>';
    h += warns.map((w) => `<div class="flwarn">! ${esc(w)}</div>`).join("") + rest.map((i) => `<div class="note">→ ${esc(i)}</div>`).join("");
    if (f.doc) h += `<div class="note">→ ${asks} outcome${asks === 1 ? " goes" : "s go"} to you.</div><div class="note">→ An entry comes to you after ${capOf(f)} moves between stages, wherever it is.</div>`;
    return `${h}</div>`;
  }
  const capOf = (f) => (f.doc && f.doc["max-moves"] !== undefined ? f.doc["max-moves"] : data.max_moves || 25);

  // ---- Walk an entry: a simulation in the page, writing nothing (§4.5a)
  function walkStart(f, kind, ai) {
    if (kind === "clock") { const a = auditsOf(f)[ai]; S.walk = { kind, ai, moves: 0, counts: {}, log: [`The clock of <b>${esc(a.name)}</b> comes round. A fresh ${esc(a.model)} session starts a run; it holds no entry.`], at: "audit" }; return; }
    const i = stagesOf(f).findIndex((s) => s.takes === kind || s.takes === "any");
    S.walk = { kind, si: i, moves: 0, counts: {}, log: [], at: i < 0 ? "none" : "stage" };
    if (i >= 0) S.walk.log.push(`A new entry starts in <b>${esc(stagesOf(f)[i].name)}</b>. A fresh ${esc(stagesOf(f)[i].model)} session takes it.`);
  }
  function walkGo(f, d, label, k) {
    const w = S.walk, idx = stagesOf(f).findIndex((s) => keyOf(s.name) === d.to);
    if (d.to === "person" || idx < 0) { w.at = "you"; w.asker = w.si; w.blocked = null; w.answers = d.answers || null; w.log.push(`${label}. The entry waits for <b>you</b>, with a question on your Queue.`); return; }
    w.counts[k] = (w.counts[k] || 0) + 1; w.moves++;
    if (d.limit && w.counts[k] > d.limit) { w.at = "you"; w.asker = w.si; w.blocked = idx; w.blockedKey = k; w.answers = null; w.log.push(`${label}, for the ${ordinal(w.counts[k])} time. The limit is ${d.limit}, so the entry comes to <b>you</b>.`); return; }
    if (w.moves > capOf(f)) { w.at = "you"; w.asker = w.si; w.blocked = idx; w.blockedKey = k; w.answers = null; w.log.push(`${label}. That is move ${w.moves}, past the total cap of ${capOf(f)}, so the entry comes to <b>you</b>.`); return; }
    w.si = idx; w.at = "stage"; const n = stagesOf(f)[idx];
    w.log.push(`${label}. The entry moves to <b>${esc(n.name)}</b>${d.limit ? ` (${w.counts[k]} of ${d.limit})` : ""}. A fresh ${esc(n.model)} session takes it.`);
  }
  function walkStep(f, o, skipped) {
    const w = S.walk, s = stagesOf(f)[w.si], d = nd(s[o]);
    const label = skipped ? `No protected file is touched, so ${esc(s.name)} is passed without a session` : `${esc(s.name)}: ${esc(words(o))}`;
    if (d.to === "merge") { w.at = "merge"; w.pend = o; w.log.push(`${label}. The merge is tried: the checks are run again on what is there now.`); return; }
    walkGo(f, d, label, `${w.si}|${o}`);
  }
  function drawWalk(f) {
    const w = S.walk;
    let h = '<div class="flwalk"><div class="btns">Start a new entry: <button type="button" class="btn sm" data-act="wstart" data-k="other">ready to build</button><button type="button" class="btn sm" data-act="wstart" data-k="design-first">needs a design first</button></div>';
    if (auditsOf(f).length) h += `<div class="btns">Or let an audit's clock come round: ${auditsOf(f).map((a, i) => `<button type="button" class="btn sm" data-act="wstart" data-k="clock" data-ai="${i}">${esc(a.name)}</button>`).join("")}</div>`;
    if (!w) return `${h}<p class="note">Pick a kind of entry, then choose each outcome to see where the flow sends it.</p></div>`;
    if (w.at === "none") h += "<p>No stage takes that kind of entry.</p>";
    else if (w.at === "done") h += '<p class="flok">Done.</p>';
    else if (w.at === "audit") h += '<p>The run ends as:</p><div class="btns"><button type="button" class="btn sm" data-act="wclock" data-k="findings">findings filed</button><button type="button" class="btn sm" data-act="wclock" data-k="nothing">nothing found</button><button type="button" class="btn sm ghost" data-act="wclock" data-k="other">other</button></div>';
    else if (w.at === "you") {
      const stages = stagesOf(f);
      const buttons = w.answers ? Object.entries(w.answers).map(([l, a]) => `<button type="button" class="btn sm" data-act="wpick" data-k="${esc(keyOf(a))}" data-l="${esc(l)}">Answer: ${esc(l)}</button>`).join("") : w.kind === "clock" ? "" : `<button type="button" class="btn sm" data-act="wanswer">${w.blocked !== null && w.blocked !== undefined ? `Carry on: on to ${esc(stages[w.blocked].name)}` : `Answer: back to ${esc(stages[w.asker].name)}`}</button>`;
      h += `<p>Waiting for <span class="flyou">you</span>.</p><div class="btns">${buttons}${w.kind === "clock" ? "" : '<button type="button" class="btn sm" data-act="wmerged">I merged the pull request</button>'}</div>`;
    } else if (w.at === "merge") h += '<p>Merging the pull request. It ends as:</p><div class="btns"><button type="button" class="btn sm" data-act="wmerge" data-k="ok">merged</button><button type="button" class="btn sm" data-act="wmerge" data-k="no">refused: it changed since the verdict, is red, or conflicts</button></div>';
    else {
      const s = stagesOf(f)[w.si];
      h += `<p>In <span class="flkey">${esc(keyOf(s.name))}</span> on <span class="mono">${esc(s.model)}</span>, doing <b>${esc((KIND[s.does] || [s.does])[0])}</b>. It ends as:</p><div class="btns">${(OUT[s.does] || []).map((o) => `<button type="button" class="btn sm" data-act="wout" data-o="${o}">${esc(words(o))}</button>`).join("")}<button type="button" class="btn sm ghost" data-act="wout" data-o="other">other</button>${s["only-when"] ? '<button type="button" class="btn sm ghost" data-act="wout" data-o="ship" data-skip="1">no protected file is touched</button>' : ""}</div>`;
    }
    return `${h}<ol>${w.log.map((l) => `<li>${l}</li>`).join("")}</ol><p class="note">${w.moves} of ${capOf(f)} moves used.</p></div>`;
  }

  function render() {
    drawList();
    const f = cur(), main = document.getElementById("flmain");
    if (!f) { main.innerHTML = '<p class="note">No flow to show.</p>'; return; }
    const ro = !editable(f), c = S.check || { problems: [] }, n = c.problems.length;
    const tag = f.place === "builtin" ? "built in · not yet in use" : f.place === "repo" ? `${f.repo}'s · read-only` : f.doc ? "yours · not yet in use" : "first shape · read-only";
    let h = '<div class="flhead">';
    h += ro || f.version ? `<span class="flname mono">${esc(f.name)}</span>` : `<input class="input flname mono" id="fname" data-act="fname" value="${esc(f.name)}" aria-label="Flow name">`;
    h += `<span class="fltag">${esc(tag)}</span><span class="act">`;
    h += S.pending ? '<span class="note">checking…</span>' : n ? `<span class="flbad">${n} problem${n > 1 ? "s" : ""}</span>` : '<span class="flok">It flows</span>';
    if (f.doc) h += `<button type="button" class="btn sm" data-act="copy" title="${esc(page.dataset.helpCopy)}">Copy</button>`;
    if (!ro) {
      h += `<button type="button" class="btn sm ghost" data-act="${S.del ? "del2" : "del"}" title="${esc(page.dataset.helpDelete)}">${S.del ? "Really delete?" : "Delete"}</button>`;
      h += `<button type="button" class="btn sm" id="flsave" data-act="save" title="${esc(page.dataset.helpSave)}"${n || S.pending ? " disabled" : ""}>Save</button>`;
    }
    h += "</span></div>";
    if (f.place === "repo") h += '<p class="note">A repo\'s flow changes by a pull request: The file is the text to copy into it.</p>';
    if (!f.doc) h += '<p class="note">A first-shape flow, which a team may be running. It is read here and changed in its file until the switch-over.</p>';
    if (f.doc) h += `<div class="flcap">An entry comes to you after ${ro ? `<b class="mono">${esc(capOf(f))}</b>` : `<input type="number" min="2" class="input" id="maxm" data-act="maxm" value="${esc(capOf(f))}" aria-label="Total cap">`} moves between stages, wherever it is.</div>`;
    const tabs = f.doc ? [["stages", "Stages"], ["walk", "Walk an entry"], ["file", "The file"]] : [["file", "The file"]];
    h += `<div class="fltabs">${tabs.map(([k, t]) => `<button type="button" data-act="tab" data-k="${k}" class="${S.tab === k ? "on" : ""}">${t}</button>`).join("")}</div>`;
    h += S.tab === "file" ? `<pre class="flfile" id="flfile">${esc(c.text || f.text || "")}</pre>` : S.tab === "walk" ? drawWalk(f) : drawStages(f);
    h += drawChecks(f);
    main.innerHTML = h;
  }

  // ---- what a press does
  const uniqueFlow = (base) => { let n = base, i = 2; while (S.rows.some((r) => r.name === n)) n = `${base}-${i++}`; return n; };
  const uniqueStage = (f, base) => { const taken = [...stagesOf(f), ...auditsOf(f)].map((x) => keyOf(x.name)); let n = base, i = 2; while (taken.includes(keyOf(n))) n = `${base} ${i++}`; return n; };
  const firstModel = () => { const ms = data.models || []; return ms.includes("sonnet") ? "sonnet" : ms[0] || ""; };
  function addStage(f, kind, after) {
    if (!OUT[kind]) return;
    const s = { name: uniqueStage(f, KIND[kind][0]), does: kind, model: firstModel() }, at = Math.min(after + 1, stagesOf(f).length);
    f.doc.stages.splice(at, 0, s); S.open = at; touched();
  }
  function renames(f) {
    const out = {};
    stagesOf(f).forEach((s) => { if (s.$was && s.$was !== keyOf(s.name)) out[s.$was] = keyOf(s.name); });
    return out;
  }
  async function save(f) {
    if (S.pending || (S.check && S.check.problems.length)) return;
    try {
      const got = await post("/api/flows/save", { name: f.name, text: S.check.text, version: f.version || null, renames: renames(f) });
      f.version = got.version; f.text = S.check.text; f.problems = []; f.info = S.check.info;
      const was = S.sel; remember(f); S.sel = idOf(f);
      if (was !== S.sel) S.sel = idOf(f);
      say(got.moved ? `Saved. ${got.moved} ${got.moved === 1 ? "entry" : "entries"} moved to the renamed stage.` : "");
    } catch (e) { say(e.message); }
    render();
  }
  async function del(f) {
    try {
      if (f.version) await post("/api/flows/save", { name: f.name, version: f.version, delete: true });
      S.rows = S.rows.filter((r) => r !== f); select(S.rows[0] || null); say("");
    } catch (e) { S.del = false; say(e.message); }
    render();
  }

  function act(el) {
    const f = cur(), d = el.dataset, si = d.si === undefined ? null : +d.si, s = si === null ? null : stagesOf(f)[si];
    const ai = d.ai === undefined ? null : +d.ai, a = ai === null ? null : auditsOf(f)[ai];
    const at = d.at ? (d.at[0] === "s" ? stagesOf(f)[+d.at.slice(1)] : auditsOf(f)[+d.at.slice(1)]) : null;
    const sub = d.sub === "1", was = S.del;
    S.del = false;
    switch (d.act) {
      case "pick": select(S.rows.find((r) => idOf(r) === d.id)); say(""); return render();
      case "tab": S.tab = d.k; return render();
      case "brief": S.brief = S.brief === d.at ? null : d.at; return render();
      case "new": {
        const name = uniqueFlow("my-flow");
        const r = { name, place: "own", text: "", problems: [], info: [], doc: { format: 3, name, stages: [{ name: "Build", does: "build", model: firstModel(), takes: "any" }] } };
        S.rows.push(r); select(r); return render();
      }
      case "copy": {
        const name = uniqueFlow(`${f.name}-copy`), doc = clean(f.doc); doc.name = name;
        const r = { name, place: "own", text: "", problems: [], info: [], doc };
        S.rows.push(r); select(r); say("Copied. This one is yours to change, and is not saved yet."); return render();
      }
      case "del": S.del = true; return render();
      case "del2": if (was) del(f); return;
      case "save": save(f); return;
      case "fname": { const v = el.value.trim(); if (v) { f.name = v; f.doc.name = v; S.sel = idOf(f); } return touched(); }
      case "maxm": { const v = parseInt(el.value, 10); if (Number.isNaN(v)) delete f.doc["max-moves"]; else f.doc["max-moves"] = v; return touched(); }
      case "sname": {
        const v = el.value.trim(); if (!v) return render();
        const old = keyOf(s.name), now = keyOf(v); s.name = v;
        stagesOf(f).forEach((x) => outs(x).forEach((o) => { if (x[o] !== undefined) x[o] = renameIn(x[o], old, now); }));
        return touched();
      }
      case "kind":
        outs(s).forEach((o) => delete s[o]); delete s["only-when"]; s.does = el.value;
        if (s.does === "review") delete s.takes;
        return touched();
      case "model": at.model = el.value; return touched();
      case "takes": if (el.value) s.takes = el.value; else delete s.takes; return touched();
      case "only": if (el.value) s["only-when"] = el.value; else delete s["only-when"]; return touched();
      case "dest": {
        const v = el.value, c = getSub(s, d.o, sub);
        if (v === "merge") put(s, d.o, { to: "merge" });
        else setSub(s, d.o, sub, FIXED.includes(v) ? { to: v } : { to: v, limit: c.limit });
        return touched();
      }
      case "limit": { const c = getSub(s, d.o, sub), v = parseInt(el.value, 10); setSub(s, d.o, sub, { to: c.to, limit: v >= 1 ? v : undefined }); return touched(); }
      case "ansadd": {
        const c = getSub(s, d.o, sub), answers = { ...(c.answers || {}) };
        let n = 1; while (`Answer ${n}` in answers) n++;
        answers[`Answer ${n}`] = keyOf(stagesOf(f)[0].name);
        setSub(s, d.o, sub, { to: "person", answers }); return touched();
      }
      case "anslabel": case "ansto": case "ansdel": {
        const c = getSub(s, d.o, sub), rows = Object.entries(c.answers || {}), n = +d.n;
        if (d.act === "ansdel") rows.splice(n, 1);
        else if (d.act === "ansto") rows[n][1] = el.value;
        else { const v = el.value.trim(); if (!v || rows.some(([l], j) => j !== n && l === v)) return render(); rows[n][0] = v; }
        setSub(s, d.o, sub, { to: "person", answers: Object.fromEntries(rows) }); return touched();
      }
      case "bpick": {
        const kind = d.at[0] === "s" ? at.does : "audit";
        if (kind !== "audit" && el.value === kind) delete at.brief; else at.brief = el.value;
        return touched();
      }
      case "also": if (el.value) at.also = el.value; else delete at.also; return touched();
      case "palette": return addStage(f, d.k, openIdx(f));
      case "addstage": if (el.value) addStage(f, el.value, stagesOf(f).length - 1); return;
      case "delstage": f.doc.stages.splice(si, 1); return touched();
      case "up": if (si > 0) { f.doc.stages.splice(si - 1, 0, f.doc.stages.splice(si, 1)[0]); S.open = si - 1; } return touched();
      case "down": if (si < stagesOf(f).length - 1) { f.doc.stages.splice(si + 1, 0, f.doc.stages.splice(si, 1)[0]); S.open = si + 1; } return touched();
      case "addaudit": {
        if (!Array.isArray(f.doc.audits)) f.doc.audits = [];
        f.doc.audits.push({ name: uniqueStage(f, "Audit"), model: firstModel(), every: "1 days", brief: "docs" });
        return touched();
      }
      case "aname": { const v = el.value.trim(); if (v) a.name = v; return touched(); }
      case "every": case "unit": {
        const m = /^(\d+) (.+)$/.exec(String(a.every || "")) || [0, "1", "days"];
        a.every = d.act === "every" ? `${el.value} ${m[2]}` : `${m[1]} ${el.value}`;
        return touched();
      }
      case "delaudit": f.doc.audits.splice(ai, 1); if (!f.doc.audits.length) delete f.doc.audits; return touched();
      case "wstart": walkStart(f, d.k, ai); return render();
      case "wout": walkStep(f, d.o, d.skip === "1"); return render();
      case "wclock": {
        const w = S.walk;
        if (d.k === "other") { w.at = "you"; w.log.push("Other. The run stops and a question about it waits for <b>you</b> on your Queue."); }
        else { w.at = "done"; w.log.push(`${d.k === "findings" ? "Findings filed" : "Nothing found"}. The run is <b>done</b>.`); }
        return render();
      }
      case "wmerge": {
        const w = S.walk, dd = nd(stagesOf(f)[w.si][w.pend]);
        if (d.k === "ok") { w.at = "done"; w.log.push("The pull request is merged. The entry is <b>done</b>."); }
        else walkGo(f, dd.refused || { to: "person" }, "The merge is refused", `${w.si}|${w.pend}|refused`);
        return render();
      }
      case "wanswer": {
        const w = S.walk, on = w.blocked; w.at = "stage";
        w.si = on !== null && on !== undefined ? on : w.asker;
        if (on !== null && on !== undefined) { delete w.counts[w.blockedKey]; w.moves = 0; }
        w.log.push(on !== null && on !== undefined ? `You say carry on. The entry goes to <b>${esc(stagesOf(f)[w.si].name)}</b>, a fresh session reads your answer, and that move's count and the total start again.` : `You answer. The entry goes back to <b>${esc(stagesOf(f)[w.si].name)}</b>, and a fresh session reads your answer.`);
        w.blocked = null; return render();
      }
      case "wpick": {
        const w = S.walk, i = stagesOf(f).findIndex((x) => keyOf(x.name) === d.k);
        if (i >= 0) { w.si = i; w.at = "stage"; w.log.push(`You answer ${esc(d.l)}. The entry goes to <b>${esc(stagesOf(f)[i].name)}</b>, and a fresh session reads your answer.`); }
        return render();
      }
      case "wmerged": S.walk.at = "done"; S.walk.log.push("You merge the pull request by hand. Merged work ends its entry: <b>done</b>."); return render();
      default: return undefined;
    }
  }

  const FIELDS = ["SELECT", "INPUT", "TEXTAREA"];
  page.addEventListener("click", (ev) => {
    const el = ev.target.closest("[data-act]");
    if (el && !FIELDS.includes(el.tagName)) { act(el); return; }
    const r = ev.target.closest("[data-drop]"), f = cur();
    if (r && !el && editable(f) && S.open !== +r.dataset.drop && !FIELDS.includes(ev.target.tagName)) { S.open = +r.dataset.drop; render(); }
  });
  page.addEventListener("change", (ev) => {
    const el = ev.target.closest("[data-act]");
    if (!el || !FIELDS.includes(el.tagName)) return;
    const id = el.id; act(el);
    const again = id && document.getElementById(id); if (again) again.focus();
  });
  page.addEventListener("dragstart", (ev) => { const p = ev.target.closest && ev.target.closest("[data-pal]"); if (p) ev.dataTransfer.setData("text/plain", p.dataset.pal); });
  page.addEventListener("dragover", (ev) => { const r = ev.target.closest && ev.target.closest("[data-drop]"); if (r && editable(cur())) { ev.preventDefault(); r.classList.add("over"); } });
  page.addEventListener("dragleave", (ev) => { const r = ev.target.closest && ev.target.closest("[data-drop]"); if (r) r.classList.remove("over"); });
  page.addEventListener("drop", (ev) => {
    const r = ev.target.closest && ev.target.closest("[data-drop]"), f = cur();
    if (!r || !editable(f)) return;
    ev.preventDefault(); addStage(f, ev.dataTransfer.getData("text/plain"), +r.dataset.drop);
  });

  select(S.rows[0] || null);
  render();
})();
