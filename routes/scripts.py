from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import REPOS_DIR
from models import RunScriptRequest
from utils import find_bash, run_bash_script
from crlf import fix_crlf

router = APIRouter()


@router.post("/api/run-script")
async def run_script(req: RunScriptRequest):
    repo_path = REPOS_DIR / req.repo_name
    script_path = (repo_path / req.script_path).resolve()

    if not str(script_path).startswith(str(repo_path.resolve())):
        return JSONResponse({"status": "error", "message": "Недопустимый путь."}, status_code=400)
    if not script_path.exists() or not script_path.is_file():
        return JSONResponse({"status": "error", "message": f"Скрипт не найден: {req.script_path}"}, status_code=404)
    if not script_path.name.lower().endswith(".sh"):
        return JSONResponse({"status": "error", "message": "Это не .sh файл."}, status_code=400)

    script_path = fix_crlf(script_path)

    bash_exe = find_bash()
    if not bash_exe:
        return JSONResponse({"status": "error", "message": "bash не найден."}, status_code=500)

    result = run_bash_script(bash_exe, script_path, repo_path)
    return {
        "status": "ok" if result["returncode"] == 0 else "error",
        "script": req.script_path,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "bash_used": bash_exe,
        "cwd": str(script_path.parent),
        "script_size": script_path.stat().st_size,
        "summary": (
            "Скрипт выполнен (код 0)" if result["returncode"] == 0
            else f"Скрипт завершился с кодом {result['returncode']}"
        ),
    }