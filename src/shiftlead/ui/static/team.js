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
