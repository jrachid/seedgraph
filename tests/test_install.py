"""The base install: seedgraph and its pytest plugin import without the async extra."""

import subprocess
import sys

WITHOUT_GREENLET = """
import sys
sys.modules["greenlet"] = None
import seedgraph
import seedgraph.pytest_plugin
"""


def test_seedgraph_and_its_plugin_import_without_greenlet():
    result = subprocess.run([sys.executable, "-c", WITHOUT_GREENLET], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
