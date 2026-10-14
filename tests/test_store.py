import pytest

from sessionorc.models import Pending, Session
from sessionorc.store import EventQueue, SessionStore

pytestmark = pytest.mark.unit


def test_session_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    s = Session(id="ao-r-n", name="n", kind="interactive", adapter="claude-code", dir="/r", profile="p")
    s.set_state("needs-you", confidence="hook", pending=Pending(kind="permission", text="Bash: git push"))
    store.save(s)
    back = store.load("ao-r-n")
    assert back is not None and back.pending is not None
    assert back.state == "needs-you" and back.pending.text == "Bash: git push" and back.confidence == "hook"
    assert list(store.load_all()) == ["ao-r-n"]
    store.delete("ao-r-n")
    assert store.load("ao-r-n") is None


def test_load_all_skips_garbage(tmp_path):
    root = tmp_path / "s"
    root.mkdir()
    (root / "bad.json").write_text("{not json")
    (root / "empty.json").write_text("{}")
    assert SessionStore(root).load_all() == {}


def test_set_state_keeps_since_when_unchanged():
    s = Session(id="a", name="a", kind="interactive", adapter="shell", dir="/", state="idle")
    since = s.since
    s.set_state("idle", confidence="scraped")
    assert s.since == since


def test_event_queue_drain_order(tmp_path):
    q = EventQueue(tmp_path / "events")
    q.append("s1", {"event": "Stop"})
    q.append("s1", {"event": "UserPromptSubmit"})
    q.append("s0", {"event": "SessionEnd"})
    drained = q.drain()
    assert [sid for sid, _ in drained] == ["s0", "s1", "s1"]
    assert [e["event"] for _, e in drained] == ["SessionEnd", "Stop", "UserPromptSubmit"]
    assert q.drain() == []


def test_two_threads_writing_one_path_each_land_whole_and_leave_no_temporary(tmp_path):
    """TD-643: two saves of one path on two threads shared a fixed `<name>.tmp`, and the second rename
    found it gone (ENOENT). Each write now has its own temporary."""
    import os
    import threading

    from sessionorc.store import _atomic_write

    target = tmp_path / "spend.json"
    errors: list[BaseException] = []
    start = threading.Barrier(8)

    def write(n: int) -> None:
        start.wait()
        for i in range(50):
            try:
                _atomic_write(target, f'{{"writer": {n}, "i": {i}}}')
            except BaseException as e:  # noqa: BLE001 — collected and asserted below
                errors.append(e)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert target.read_text().startswith('{"writer": ')
    assert os.listdir(tmp_path) == ["spend.json"]


def test_a_write_keeps_the_mode_asked_and_the_umasks_default_otherwise(tmp_path):
    import os
    import stat

    from sessionorc.store import _UMASK, _atomic_write

    _atomic_write(tmp_path / "secret", "x", mode=0o600)
    _atomic_write(tmp_path / "plain", "y")
    assert stat.S_IMODE(os.stat(tmp_path / "secret").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / "plain").st_mode) == 0o666 & ~_UMASK
