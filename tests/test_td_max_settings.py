"""td-max's settings (design §4.9 *Scaling with the work*, *The bounds*; §5 `teams.<team>.max`, `scale`; TD-1545
slice 1): a team's `max` is `size`'s map or `off`, `off` per name refused; `scale.live` caps a host's live
sessions, its default the machine's (half its memory at 0.5 GB a session, capped at twice its cores);
`scale.migrated` the home's stamp."""

from datetime import date

import pytest
import yaml

from sessionorc import settings as s

pytestmark = pytest.mark.unit


def test_max_is_a_map_of_names_to_numbers_or_off_for_the_team():
    assert s.parse_team({"max": {"grinder-ao": 5, "techlead-ao-1": 3}}) == {
        "max": {"grinder-ao": 5, "techlead-ao-1": 3}
    }
    assert s.parse_team({"max": "off"}) == {"max": "off"}
    assert s.parse_team({"max": {"grinder-ao": 0}}) == {"max": {"grinder-ao": 0}}, "0: no scaling at any size"


@pytest.mark.parametrize(
    ("value", "says"),
    [
        ({"grinder-ao": "off"}, "off is the whole team's"),
        ({"grinder-ao": -1}, "0 or more"),
        ({"grinder-ao": True}, "0 or more"),
        ("on", "max is off or a mapping"),
        (3, "max is off or a mapping"),
    ],
)
def test_a_bad_max_is_refused_in_words(value, says):
    with pytest.raises(ValueError, match=says):
        s.parse_team({"max": value})


def test_the_reader_drops_a_bad_name_and_keeps_the_rest():
    doc = {"teams": {"ao-grind": {"size": {"grinder-ao": 3}, "max": {"grinder-ao": "off", "techlead-ao-1": 3}}}}
    assert s.teams(doc) == {"ao-grind": {"size": {"grinder-ao": 3}, "max": {"techlead-ao-1": 3}}}
    assert s.teams({"teams": {"t": {"max": "sometimes", "size": {"w": 1}}}}) == {"t": {"size": {"w": 1}}}
    hand = yaml.safe_load("teams:\n  t:\n    max: off\n")  # YAML reads a bare off as False
    assert s.teams(hand) == {"t": {"max": "off"}}
    with pytest.raises(ValueError, match="max is off or a mapping"):
        s.parse_team({"max": False})  # the RPC's side keeps refusing a boolean


def test_scale_live_and_its_migration_stamp():
    assert s.parse_scale({"live": {"kmaster": 30}, "migrated": date(2026, 11, 11)}) == {
        "live": {"kmaster": 30},
        "migrated": "2026-11-11",
    }
    assert s.parse_scale({"migrated": "2026-11-11"}) == {"migrated": "2026-11-11"}
    with pytest.raises(ValueError, match="1 or more"):
        s.parse_scale({"live": {"kmaster": 0}})
    with pytest.raises(ValueError, match="unknown key"):
        s.parse_scale({"min": 1})
    with pytest.raises(ValueError, match="is a date"):
        s.parse_scale({"migrated": "soon"})
    assert s.scale({"scale": {"live": {"kmaster": 0, "node": 8}, "migrated": "soon"}}) == {"live": {"node": 8}}
    assert s.scale({"scale": "big"}) == {}


def test_the_host_cap_is_the_settings_else_the_machines():
    assert s.default_live_cap(30 << 30, 16) == 30, "kmaster: 30 GB and 16 cores"
    assert s.default_live_cap(64 << 30, 8) == 16, "capped at twice its cores"
    assert s.default_live_cap(None, 4) == 8 and s.default_live_cap(8 << 30, None) == 8
    assert s.default_live_cap(None, None) is None
    assert s.default_live_cap(512 << 20, 1) == 1, "never below one"
    doc = {"scale": {"live": {"kmaster": 12}}}
    assert s.live_cap(doc, "kmaster", 30) == 12
    assert s.live_cap(doc, "node-a", 30) == 30
    assert s.live_cap({}, "kmaster") is None
    assert s.machine_live_cap() is None or s.machine_live_cap() >= 1
