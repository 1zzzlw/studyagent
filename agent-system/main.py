"""启动：在 studyAgent 目录运行 uv run python agent-system/main.py。"""
import argparse
import logging
from datetime import datetime
import uvicorn
from agent.common.models import BEIJING

if __name__ == "__main__":
    formatter = logging.Formatter("%(asctime)s 北京时间 %(levelname)s %(name)s: %(message)s")
    formatter.converter = lambda stamp: datetime.fromtimestamp(stamp, BEIJING).timetuple()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    parser = argparse.ArgumentParser(description="四系统记忆实验室后端")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("agent.api:app", host=args.host, port=args.port)
