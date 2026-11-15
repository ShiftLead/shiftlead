"""A v3 board for a test (ledgerboard v3.0, TD-1881): write a board the way `board.py split` leaves one.

v3.0's writers refuse a v2 board (*split first*), so a test that writes a board through ShiftLead's code holds a
v3 board: the directory `docs/user_attention/` (its `README.md`, one `<id>.md` per open item and
`archive/<YYYY-MM>/<id>.md` per closed one) and the stub at `docs/user_attention.md` naming it. A test still
*writes its fixture* as the v2 text it always has, and this module splits it with the vendored `split_board()`,
so a migrated item's id is `<its line's date>-<the 8 hex of its old board:<key>>`, exactly as the real split
gives it: `ref_of(text)` below is that reference, from the line alone.
"""

from __future__ import annotations

from pathlib import Path

from sessionorc import ledgerboard as lb

BOARD = Path("docs") / "user_attention.md"


def write_board(root: Path | str, text: str, archive: str = "", rel: Path | str = BOARD) -> Path:
    """Write `text` (a v2 board, and `archive` its archive) under `root` as a v3 board at `rel`: the stub at `rel`
    and the directory beside it, less `.md`. Any old directory there is replaced. The stub's path, which every
    reader and writer takes."""
    stub = Path(root) / rel
    d = stub.with_suffix("")
    if d.exists():
        for p in sorted(d.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        d.rmdir()
    files = lb.split_board(text, archive)
    for name, body in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    stub.parent.mkdir(parents=True, exist_ok=True)
    title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), "User attention")
    stub.write_text(lb.board_stub(title, d.name), encoding="utf-8")
    archive_file = Path(lb.archive_path(str(stub)))
    if archive_file.exists():
        archive_file.unlink()
    return stub


def ref_of(line: str) -> str:
    """`board:<8 hex>` of a v2 item line (with or without its `- [ ] ` tick): the reference the split item keeps."""
    full = line if line.lstrip().startswith("- [") else f"- [ ] {line}"
    return "board:" + lb.key_id(lb.item_key(full))


def load(root: Path | str, rel: Path | str = BOARD) -> lb.Board:
    """The board at `root`/`rel` as `load_board()` reads it from the working tree."""
    from sessionorc import ledger

    return lb.load_board(str(rel), *ledger.fs_io(root))


def item(root: Path | str, ref: str, rel: Path | str = BOARD) -> lb.BoardItem | None:
    """The item, open or closed, whose id ends with `ref`'s 8 hex digits, else None."""
    nonce = ref.removeprefix("board:")
    b = load(root, rel)
    return next((it for it in [*b.items, *b.closed] if it.id and it.id.endswith("-" + nonce)), None)
