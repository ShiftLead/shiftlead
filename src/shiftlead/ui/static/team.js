// A switched team's page (design §4.9d *The page*, §4.5a *Team page*, TD-2060). Every press is one `team_set`, the
// person's own act, with the version the page was drawn at; the host agent refuses a stale one, and the page reloads.
(function () {
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
