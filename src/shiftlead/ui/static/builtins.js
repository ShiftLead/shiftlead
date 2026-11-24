// The Built-in seats page (design §4.9d *The built-in seats and their page*, §4.5a, TD-2066). Every press is one call,
// the person's own act, with the version the page was drawn at; the host agent refuses a stale one.
(function () {
  const AWAY = "The host agent did not answer, so nothing was changed.";
  const post = async (url, body) => {
    try {
      const r = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.ok) return { ok: true, got: await r.json() };
      let why = r.statusText;
      try { why = (await r.json()).detail || why; } catch (e) { /* the status line stands */ }
      return { ok: false, why };
    } catch (e) { return { ok: false, why: AWAY }; }
  };
  const shout = (el, words) => { el.textContent = words; el.hidden = false; };

  const form = document.getElementById("bnew");
  if (form) {
    const said = document.getElementById("bnewsaid");
    document.getElementById("bnewopen").addEventListener("click", () => { form.hidden = false; form.elements.name.focus(); });
    document.getElementById("bnewcancel").addEventListener("click", () => { form.hidden = true; });
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      said.hidden = true;
      const body = { name: form.elements.name.value.trim() };
      const label = form.elements.label.value.trim();
      if (label) body.label = label;
      const r = await post("/api/builtins/new", body);
      if (r.ok) location.href = `/builtins/${encodeURIComponent(r.got.set)}`;
      else shout(said, r.why);
    });
  }

  const box = document.getElementById("bset");
  if (!box) return;
  const name = box.dataset.set, version = box.dataset.version;
  const order = JSON.parse(box.dataset.order), models = JSON.parse(box.dataset.models);
  const said = document.getElementById("bsaid");
  const finish = (r) => { if (r.ok) location.reload(); else shout(said, r.why); };
  const send = async (change) => {
    said.hidden = true;
    finish(await post(`/api/builtins/${encodeURIComponent(name)}/set`, { ...change, version }));
  };

  const label = document.getElementById("blabel");
  if (label) label.addEventListener("click", () => {
    const now = prompt("The set's label (empty clears it)", label.dataset.label);
    if (now !== null && now !== label.dataset.label) send({ label: now });
  });
  const add = (key) => { if (key) send({ logins: [...order, key] }); };
  document.getElementById("badd").addEventListener("click", () => add(document.getElementById("baddpick").value));
  document.getElementById("baddtypedgo").addEventListener("click", () => add(document.getElementById("baddtyped").value.trim()));

  box.addEventListener("change", async (ev) => {
    const el = ev.target;
    if (el.dataset.seat) send({ models: { ...models, [el.dataset.seat]: el.value } });
    else if (el.dataset.repo) {
      said.hidden = true;
      finish(await post("/api/builtins/repo", { repo: el.dataset.repo, set: el.value, version }));
    }
  });
  box.addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    const row = b && b.closest("[data-login]");
    if (!row || b.disabled) return;
    if (b.dataset.move) {
      const list = [...order], at = list.indexOf(row.dataset.login), to = at + Number(b.dataset.move);
      [list[at], list[to]] = [list[to], list[at]];
      send({ logins: list });
    } else if ("drop" in b.dataset) {
      send({ logins: order.filter((k) => k !== row.dataset.login) });
    }
  });

  const del = document.getElementById("bdelete");
  del.addEventListener("click", async () => {
    if (del.dataset.armed !== "1") {
      del.dataset.armed = "1";
      del.textContent = "Really delete?";
      return;
    }
    const out = document.getElementById("bdeletesaid");
    out.hidden = true;
    del.disabled = true;
    const r = await post(`/api/builtins/${encodeURIComponent(name)}/delete`, { version });
    if (r.ok) { location.href = "/builtins"; return; }
    shout(out, r.why);
    del.disabled = false;
    del.dataset.armed = "";
    del.textContent = `Delete ${name}`;
  });
})();
