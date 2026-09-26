import re
from pathlib import Path

README = Path(__file__).parent.parent / "README.md"


def _python_blocks() -> list[str]:
    return re.findall(r"^```python\n(.*?)^```", README.read_text(), flags=re.DOTALL | re.MULTILINE)


def test_the_readme_python_blocks_run_in_order_as_a_reader_would_paste_them():
    namespace: dict[str, object] = {}
    for number, block in enumerate(_python_blocks(), start=1):
        try:
            exec(compile(block, f"README.md python block {number}", "exec"), namespace)  # noqa: S102
        except Exception as exc:
            raise AssertionError(f"README python block {number} fails:\n{block}") from exc
