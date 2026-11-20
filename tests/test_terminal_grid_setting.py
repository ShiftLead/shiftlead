"""§5 `person.terminal.grid` (§4.6 *Attach behaviour with another client present*, TD-1919, TD-1947): the
columns and rows a new session's window is pinned at — two whole numbers, columns 20–500 and rows 5–200."""

import pytest

from sessionorc import settings as settings_mod


@pytest.mark.parametrize("grid", [[120, 40], [20, 5], [500, 200], (80, 24)])
def test_a_grid_within_its_bounds_is_taken(grid):
    assert settings_mod.parse_terminal_grid(grid) == list(grid)
    assert settings_mod.parse_person({"terminal": {"grid": grid}})["terminal"]["grid"] == list(grid)


@pytest.mark.parametrize(
    "grid",
    [[19, 40], [501, 40], [120, 4], [120, 201], [120], [120, 40, 1], "120x40", [120.0, 40], [True, 40], None],
)
def test_a_grid_outside_its_bounds_or_not_two_whole_numbers_is_refused(grid):
    with pytest.raises(ValueError, match=r"terminal\.grid is \[columns, rows\], columns from 20 to 500"):
        settings_mod.parse_terminal_grid(grid)
    with pytest.raises(ValueError):
        settings_mod.parse_person({"terminal": {"grid": grid}})
    # read leniently (a hand-edited file), the bad grid is dropped and the rest stands
    assert settings_mod.parse_person({"terminal": {"grid": grid, "size": 14}}, drop=True)["terminal"] == {"size": 14}


def test_the_bounds_and_the_default_are_the_designs():
    assert settings_mod.TERMINAL_GRID == ((20, 500), (5, 200))
    assert settings_mod.TERMINAL_GRID_DEFAULT == (120, 40)
    assert "grid" in settings_mod.TERMINAL_KEYS
