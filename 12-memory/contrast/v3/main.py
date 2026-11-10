"""在任意终端目录运行：python .../contrast/v3/main.py。"""
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from v3.cli import run


if __name__ == "__main__":
    run("v3")
