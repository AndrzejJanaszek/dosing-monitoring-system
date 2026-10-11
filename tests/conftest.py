from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).parent
TEST_LEVELS = ("unit", "integration", "e2e")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        level = item.path.relative_to(TESTS_ROOT).parts[0]
        if level in TEST_LEVELS:
            item.add_marker(level)
