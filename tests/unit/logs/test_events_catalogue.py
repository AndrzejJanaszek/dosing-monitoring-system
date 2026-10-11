import re
from pathlib import Path

from dms.logs import events

CATALOGUE_PATH = Path(__file__).parents[3] / "docs" / "log-events.md"
CATALOGUE_ROW = re.compile(r"^\| `([a-z_.]+)` \|", re.MULTILINE)


def events_in_code() -> set[str]:
    return {
        value for name, value in vars(events).items() if name.isupper() and isinstance(value, str)
    }


def events_in_catalogue() -> list[str]:
    return CATALOGUE_ROW.findall(CATALOGUE_PATH.read_text(encoding="utf-8"))


def test_every_event_in_code_is_in_the_catalogue() -> None:
    assert events_in_code() - set(events_in_catalogue()) == set()


def test_every_event_in_the_catalogue_is_in_code() -> None:
    assert set(events_in_catalogue()) - events_in_code() == set()


def test_catalogue_has_no_duplicates() -> None:
    names = events_in_catalogue()

    assert len(names) == len(set(names))
