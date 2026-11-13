"""HTTP 接收即时确认，回复协调线程处理模型；读取端点观察真实进度。"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field
from .application.runtime import Runtime, BusyError
from .common.models import Model


class MessageRequest(Model):
    message_id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=20000)


class TimeRequest(Model):
    days: float = Field(gt=0, le=3650)


class StateRequest(Model):
    energy: float = Field(ge=0, le=1)
    busyness: float = Field(ge=0, le=1)
    activity: str = Field(min_length=1, max_length=100)
    attention_focus: str = Field(min_length=1, max_length=100)
    environment: str = Field(min_length=1, max_length=200)
    current_intent: str = Field(min_length=1, max_length=200)


def create_app(runtime=None, quiet_seconds=2.0):
    @asynccontextmanager
    async def lifespan(app):
        # 初始化也放在线程池，避免 Chroma 的同步加载阻塞主循环。
        import asyncio
        from .application.reply_control.coordinator import ReplyCoordinator
        app.state.runtime = runtime or await asyncio.to_thread(Runtime)
        app.state.coordinator = ReplyCoordinator(app.state.runtime, quiet_seconds)
        app.state.coordinator.start()
        try:
            yield
        finally:
            await asyncio.to_thread(app.state.coordinator.close)

    app = FastAPI(title="四系统记忆实验室", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def current():
        return app.state.runtime

    def invoke(action):
        try:
            return action()
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        except BusyError as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except Exception as error:
            raise HTTPException(500, str(error)) from error

    @app.get("/api/health")
    def health():
        return {"status": "ok", "character_name": current().repo.character_name}

    @app.get("/api/conversations")
    def conversations():
        return current().repo.conversations()

    @app.post("/api/conversations")
    def create_conversation():
        return current().repo.create_conversation(current().now())

    @app.delete("/api/conversations/{key}")
    def archive(key: str):
        return invoke(lambda: current().archive(key))

    @app.get("/api/conversations/{key}/messages")
    def messages(key: str, limit: int = Query(100, ge=1, le=500), before_id: int | None = Query(None, ge=1)):
        return invoke(lambda: current().repo.messages(key, limit, before_id))

    @app.post("/api/conversations/{key}/messages", status_code=202)
    def send(key: str, request: MessageRequest):
        if not request.content.strip():
            raise HTTPException(422, "消息不能为空")
        return invoke(lambda: app.state.coordinator.submit(key, request.message_id, request.content))

    @app.get("/api/conversations/{key}/activity")
    def activity(key: str):
        return invoke(lambda: app.state.coordinator.activity(key))

    @app.get("/api/turns/{key}")
    def turn(key: str, summary: bool = False):
        def action():
            if not summary:
                return current().turn_result(key)
            value = current().repo.turn(key)
            if value is None:
                raise KeyError("处理记录不存在")
            return value

        return invoke(action)

    @app.get("/api/snapshot")
    def snapshot():
        return current().snapshot()

    @app.get("/api/status")
    def status():
        return current().status()

    @app.get("/api/memories/{key}")
    def detail(key: str):
        return invoke(lambda: current().memory_detail(key))

    @app.get("/api/storage/chroma")
    def chroma():
        return invoke(lambda: current().index.info())

    @app.get("/api/storage/tables/{name}")
    def table(name: str, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
        return invoke(lambda: current().repo.table(name, limit, offset))

    @app.patch("/api/character-state")
    def update_state(request: StateRequest):
        return invoke(lambda: current().change_state(request.model_dump()))

    @app.post("/api/time/advance")
    def advance(request: TimeRequest):
        return invoke(lambda: current().advance(request.days))

    @app.post("/api/index/retry")
    def retry():
        return invoke(current().retry_index)

    return app


app = create_app()
