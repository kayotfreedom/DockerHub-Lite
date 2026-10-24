from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import running_processes
from history import add_history
from models import StopRequest

router = APIRouter()


@router.post("/api/stop")
async def stop_process(req: StopRequest):
    repo_name = req.repo_name
    if repo_name not in running_processes:
        return JSONResponse(
            {"status": "error", "message": "Нет запущенных процессов."},
            status_code=404,
        )
    try:
        proc = running_processes[repo_name]["proc"]
        proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        running_processes.pop(repo_name, None)
        add_history("stop", f"Процесс {repo_name} остановлен", "ok")
        return {"status": "ok", "message": "Процесс остановлен"}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)