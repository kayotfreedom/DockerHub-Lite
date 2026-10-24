from fastapi import APIRouter

from config import REPOS_DIR, running_processes
from history import load_history

router = APIRouter()


@router.get("/api/history")
async def get_history():
    return {"history": load_history()}


@router.get("/api/stats")
async def stats():
    repos = [d for d in REPOS_DIR.iterdir() if d.is_dir()]
    total_size = 0
    total_sh = 0
    for repo in repos:
        total_size += sum(f.stat().st_size for f in repo.rglob("*") if f.is_file())
        total_sh += sum(1 for f in repo.rglob("*.sh") if f.is_file())

    return {
        "repo_count": len(repos),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "with_dockerfile": sum(1 for r in repos if (r / "Dockerfile").exists()),
        "with_git": sum(1 for r in repos if (r / ".git").exists()),
        "sh_count": total_sh,
        "running": list(running_processes.keys()),
    }