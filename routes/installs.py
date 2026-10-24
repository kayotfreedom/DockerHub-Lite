import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import build_queues
from models import InstallDepsRequest
from install import run_install

router = APIRouter()


@router.get("/api/install-deps/log/{queue_key:path}")
async def install_log_stream(queue_key: str, request: Request):
    queue = build_queues.get(queue_key)
    if queue is None:
        raise HTTPException(status_code=404, detail="Установка не запущена")

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


@router.post("/api/install-deps/start")
async def install_deps_start(req: InstallDepsRequest):
    repo_name = req.repo_name
    queue_key = f"install:{repo_name}"
    if queue_key in build_queues:
        return JSONResponse(
            {"status": "error", "message": "Установка уже идёт."},
            status_code=409,
        )

    queue: asyncio.Queue = asyncio.Queue()
    build_queues[queue_key] = queue
    asyncio.create_task(run_install(repo_name, req.requirements_path, queue))
    return {"status": "ok", "message": "Установка запущена", "queue_key": queue_key}