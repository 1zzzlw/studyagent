"""启动：python 12-memory/contrast/web.py，访问 http://127.0.0.1:80。"""
import argparse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from web_service import BusyError, MemoryLab


Version = Literal["v1", "v2", "v3"]
STATIC = Path(__file__).resolve().parent / "static"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    read_only: bool = False


class TimeRequest(BaseModel):
    days: float = Field(gt=0, allow_inf_nan=False)


def create_app(lab=None):
    @asynccontextmanager
    async def lifespan(app):
        if lab is None:
            from v1.llm import load_environment
            load_environment()
        app.state.lab = lab or MemoryLab()
        yield

    app = FastAPI(title="记忆实验室", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def session(version):
        return app.state.lab.session(version)

    def execute(action):
        try:
            return action()
        except BusyError as error:
            raise HTTPException(409, str(error)) from error
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except Exception as error:
            raise HTTPException(500, f"{type(error).__name__}: {error}") from error

    @app.get("/")
    def index():
        return RedirectResponse("/static/index.html")

    @app.get("/api/{version}/state")
    def state(version: Version):
        def read():
            current = session(version)
            return {**current.status(), "turns": current.turns(), "memories": current.memories()}
        return execute(read)

    @app.get("/api/{version}/memories/{node_id}")
    def memory(version: Version, node_id: str):
        return execute(lambda: session(version).memory(node_id))

    @app.get("/api/{version}/graph")
    def graph(version: Version):
        return execute(lambda: session(version).graph())

    @app.post("/api/{version}/chat")
    def chat(version: Version, body: ChatRequest):
        message = body.message.strip()
        if not message:
            raise HTTPException(422, "请输入对话内容。")
        return execute(lambda: session(version).chat(message, body.read_only))

    @app.post("/api/{version}/elapse")
    def elapse(version: Version, body: TimeRequest):
        return execute(lambda: session(version).elapse(body.days))

    @app.post("/api/{version}/reset")
    def reset(version: Version):
        return execute(lambda: session(version).reset())

    return app


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser(description="从空记忆开始的三版聊天与结构观察界面")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=80)
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port, workers=1)
