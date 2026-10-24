import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import build_queues
from models import BuildRequest
from build import run_build

router = APIRouter()


@router.get("/api/build-log/{repo_name}")
async def build_log_stream(repo_name: str, request: Request):
    queue = build_queues.get(repo_name)
    if queue is None:
        raise HTTPException(status_code=404, detail="Сборка не запущена")

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                if msg.get("type") == "end":
                    break
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/build/start")
async def build_start(req: BuildRequest):
    repo_name = req.repo_name
    if repo_name in build_queues:
        return JSONResponse(
            {"status": "error", "message": "Сборка уже идёт."},
            status_code=409,
        )

    queue: asyncio.Queue = asyncio.Queue()
    build_queues[repo_name] = queue
    asyncio.create_task(run_build(repo_name, req.dockerfile_path, req.target, queue))
    return {"status": "ok", "message": "Сборка запущена"}