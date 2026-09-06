"""允许从 studyAgent 根目录直接运行本模块。"""

import sys

from embedding_lab.cli import main


if __name__ == "__main__":
    # Windows 终端代码页可能不是 UTF-8，显式统一后中文教学输出不会乱码。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        exit_code = main()
    except OSError as exc:
        if getattr(exc, "winerror", None) != 10106:
            raise
        print(
            "无法加载 Windows asyncio/_overlapped（WinError 10106）。"
            "这是当前主机的 Winsock/运行环境问题，不是切块或 Chroma 业务错误。",
            file=sys.stderr,
        )
        exit_code = 1
    raise SystemExit(exit_code)
