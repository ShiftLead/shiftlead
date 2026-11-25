// A switched team's page (design §4.9d *The page*, §4.5a *Team page*, TD-2060). Every press is one `team_set`, the
// person's own act, with the version the page was drawn at; the host agent refuses a stale one, and the page reloads.
(function () {
  const post = async (url, body) => {
    const r = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (r.ok) return { ok: true, got: await r.json() };
    let why = r.statusText;
    try { why = (await r.json()).detail || why; } catch (e) { /* the status line stands */ }
    return { ok: false, why };
  };
  const shout = (el, words) => { el.textContent = words; el.hidden = false; };
  const AWAY = "The host agent did not answer, so nothing was changed.";

  // **+ New team** (§4.9d *New team*, TD-2063)
  const form = document.getElementById("teamnew");
  if (form) {
    const hosts = JSON.parse(form.dataset.hosts), teams = JSON.parse(form.dataset.teams);
    const declared = JSON.parse(form.dataset.declared);
    const said = document.getElementById("teamnewsaid");
    const second = document.getElementById("teamnewsecond");
    // the names the ledger declares first, a deleted one among them, as the page's own `declared_line` writes them
    const drawLine = () => {
      const repo = form.elements.repo.value, seen = new Set();
      const names = [...(declared[repo] || []), ...(teams[repo] || []), form.elements.name.value.trim() || "<name>"];
      const line = names.filter((n) => !seen.has(n.toLowerCase()) && seen.add(n.toLowerCase()));
      document.getElementById("teamnewline").textContent = `Team = ${line.join(" | ")}`;
    };
    const redraw = () => {
      const repo = form.elements.repo.value;
      form.elements.host.replaceChildren(...(hosts[repo] || []).map((h) => new Option(h, h)));
      second.hidden = !(teams[repo] || []).length;
      drawLine();
    };
    document.getElementById("teamnewopen").addEventListener("click", () => {
      form.hidden = false;
      redraw();
      form.elements.name.focus();
    });
    document.getElementById("teamnewcancel").addEventListener("click", () => { form.hidden = true; });
    form.elements.repo.addEventListener("change", redraw);
    form.elements.name.addEventListener("input", drawLine);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      said.hidden = true;
      const body = Object.fromEntries(["name", "label", "repo", "host", "flow"].map((k) => [k, form.elements[k].value.trim()]));
      if (!body.label) delete body.label;
      try {
        const r = await post("/api/teams/new", body);
        if (r.ok) { location.href = `/teams/${encodeURIComponent(r.got.team)}`; return; }
        shout(said, r.why);
      } catch (e) { shout(said, AWAY); }
    });
  }

  // **Delete** (§4.9d *Delete*, TD-2063): a second press, as §4.5a's row says
  const del = document.getElementById("teamdelete");
  if (del) {
    const said = document.getElementById("teamdeletesaid");
    del.addEventListener("click", async () => {
      if (del.dataset.armed !== "1") {
        del.dataset.armed = "1";
        del.textContent = "Really delete?";
        return;
      }
      said.hidden = true;
      del.disabled = true;
      try {
        const r = await post(`/api/teams/${encodeURIComponent(del.dataset.team)}/delete`, { version: del.dataset.version });
        if (r.ok) { location.href = "/teams"; return; }
        shout(said, r.why);
      } catch (e) { shout(said, AWAY); }
      del.disabled = false;
      del.dataset.armed = "";
      del.textContent = `Delete ${del.dataset.team}`;
    });
  }

  const box = document.getElementById("teamset");
  if (!box) return;
  const said = document.getElementById("teamsaid");
  const order = JSON.parse(box.dataset.order);
  const send = async (change) => {
    said.hidden = true;
    try {
      const r = await fetch(`/api/teams/${encodeURIComponent(box.dataset.team)}/set`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...change, version: box.dataset.version }),
      });
      if (r.ok) return location.reload();
      let why = r.statusText;
      try { why = (await r.json()).detail || why; } catch (e) { /* the status line stands */ }
      said.textContent = why;
    } catch (e) {
      said.textContent = "The host agent did not answer, so nothing was changed.";
    }
    said.hidden = false;
  };
  // the flow pick and the switch preview (§4.9d *The flow pick and a switch*, §4.5a *Team page: the switch preview*,
  // TD-2062): a pick writes nothing; it reads what the switch would do, and **Switch now** is the switch itself
  const pick = document.getElementById("teamflow");
  const pane = document.getElementById("teamswitch");
  if (pick && pane) {
    const team = encodeURIComponent(box.dataset.team);
    const el = (tag, cls, text) => {
      const e = document.createElement(tag);
      if (cls) e.className = cls;
      if (text !== undefined) e.textContent = text;
      return e;
    };
    const keep = () => { pick.value = pick.dataset.flow; pane.hidden = true; pane.replaceChildren(); };
    const draw = (flow, r) => {
      const from = pick.dataset.flow;
      const head = el("div", "note");
      head.append(el("b", "", `Switch ${box.dataset.team} from ${from} to ${flow}`));
      const parts = [head];
      const refused = r.ok ? r.got.refused : r.why;
      if (refused) parts.push(el("div", "note warn", refused));
      if (r.ok && !refused) {
        const records = r.got.records || [];
        if (!records.length) parts.push(el("div", "note", "No entry of this team is in a stage, so none is moved."));
        else {
          const list = el("ul", "teamswitchlist");
          for (const x of records) {
            const li = el("li", `teamswitchrow case-${x.case}`);
            li.append(el("b", "", x.id), " ", el("span", "note mono", x.stage), " ", el("span", "", x.line));
            list.append(li);
          }
          parts.push(list);
        }
        if (r.got.none_ended) parts.push(el("div", "note", "No session is ended."));
        if ((r.got.drops || []).length) {
          parts.push(el("div", "note", `The sessions-at-once numbers of ${r.got.drops.join(", ")} are dropped: ${flow} has no such stage.`));
        }
      }
      const go = el("button", "btn sm", "Switch now");
      go.type = "button";
      go.disabled = Boolean(refused);
      const no = el("button", "btn sm ghost", `Keep ${from}`);
      no.type = "button";
      no.addEventListener("click", keep);
      go.addEventListener("click", async () => {
        go.disabled = no.disabled = pick.disabled = true;  // one switch at a time: the pick waits for its answer
        said.hidden = true;
        try {
          const done = await post(`/api/teams/${team}/switch`, { flow, version: box.dataset.version });
          if (done.ok) return location.reload();
          shout(said, done.why);
        } catch (e) { shout(said, AWAY); }
        go.disabled = no.disabled = pick.disabled = false;
      });
      const row = el("div", "row gap wrap");
      row.append(go, no);
      parts.push(row);
      pane.replaceChildren(...parts);
      pane.hidden = false;
    };
    pick.addEventListener("change", async () => {
      const flow = pick.value;
      if (flow === pick.dataset.flow) return keep();
      pane.replaceChildren(el("div", "note", `Reading what a switch to ${flow} would do…`));
      pane.hidden = false;
      let r;
      try {
        const got = await fetch(`/api/teams/${team}/switch-preview?flow=${encodeURIComponent(flow)}`);
        if (got.ok) r = { ok: true, got: await got.json() };
        else {
          let why = got.statusText;
          try { why = (await got.json()).detail || why; } catch (e) { /* the status line stands */ }
          r = { ok: false, why: `No preview, so it cannot be switched now: ${why}` };
        }
      } catch (e) { r = { ok: false, why: "The host agent did not answer, so there is no preview." }; }
      if (pick.value === flow) draw(flow, r);  // a later pick's read wins
    });
  }

  const label = document.getElementById("teamlabel");
  if (label) label.addEventListener("click", () => {
    const now = prompt("The team's label (empty clears it)", label.dataset.label);
    if (now !== null && now !== label.dataset.label) send({ label: now });
  });
  const add = document.getElementById("teamadd");
  if (add) add.addEventListener("click", () => {
    const from = document.getElementById("teamaddpick") || document.getElementById("teamaddtyped");
    const key = from.value.trim();
    if (key) send({ logins: [...order, key] });
  });
  box.addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b || b.disabled) return;
    const row = b.closest("[data-login]");
    const num = b.closest("[data-key]");
    if (row && b.dataset.move) {
      const list = [...order], at = list.indexOf(row.dataset.login), to = at + Number(b.dataset.move);
      [list[at], list[to]] = [list[to], list[at]];
      send({ logins: list });
    } else if (row && "drop" in b.dataset) {
      send({ logins: order.filter((k) => k !== row.dataset.login) });
    } else if (num && b.dataset.number) {
      const n = Number(num.querySelector(".mono").textContent) + Number(b.dataset.number);
      send({ at_once: { [num.dataset.key]: n } });
    } else if (num && "removeNumber" in b.dataset) {
      send({ at_once: { [num.dataset.key]: null } });
    } else if (b.dataset.mostSet) {
      send({ most: Number(b.dataset.mostSet) });
    } else if (b.dataset.mostStep) {
      send({ most: Number(b.closest("[data-most]").dataset.most) + Number(b.dataset.mostStep) });
    } else if ("mostClear" in b.dataset) {
      send({ clear: "most" });
    }
  });
})();
