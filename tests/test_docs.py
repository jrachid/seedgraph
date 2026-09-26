import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
RECIPES = sorted((ROOT / "docs" / "recipes").glob("*.md"))

pytest_plugins = ["pytester"]


def _python_blocks(page: Path) -> list[str]:
    return re.findall(r"^```python\n(.*?)^```", page.read_text(), flags=re.DOTALL | re.MULTILINE)


def test_the_readme_python_blocks_run_in_order_as_a_reader_would_paste_them():
    namespace: dict[str, object] = {}
    for number, block in enumerate(_python_blocks(ROOT / "README.md"), start=1):
        try:
            exec(compile(block, f"README.md python block {number}", "exec"), namespace)  # noqa: S102
        except Exception as exc:
            raise AssertionError(f"README python block {number} fails:\n{block}") from exc


def test_every_recipe_page_is_found():
    assert [page.stem for page in RECIPES] == ["custom-columns", "fastapi", "pytest"]


@pytest.mark.parametrize("page", RECIPES, ids=lambda page: page.stem)
def test_a_recipe_pasted_into_a_test_file_passes(page: Path, pytester: pytest.Pytester):
    pytester.makepyfile(test_recipe="\n\n".join(_python_blocks(page)))

    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")

    outcomes = result.parseoutcomes()
    assert outcomes.get("passed", 0) > 0 and not outcomes.get("failed") and not outcomes.get("errors"), result.stdout.str()
