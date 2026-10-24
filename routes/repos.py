import asyncio
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from config import REPOS_DIR, running_processes
from history import add_history
from models import CloneRequest
from utils import decode_bytes, is_text_file

router = APIRouter()


@router.get("/api/search")
async def search_github(q: str, page: int = 1):
    if not q.strip():
        return JSONResponse({"items": []})

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://api.github.com/search/repositories",
            params={"q": q, "per_page": 10, "page": page},
            headers={"Accept": "application/vnd.github.v3+json"},
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="GitHub API error")

    data = resp.json()
    items = []
    for repo in data.get("items", []):
        items.append({
            "name": repo["name"],
            "full_name": repo["full_name"],
            "description": repo.get("description", ""),
            "html_url": repo["html_url"],
            "clone_url": repo["clone_url"],
            "stars": repo["stargazers_count"],
            "language": repo.get("language", ""),
            "forks": repo.get("forks_count", 0),
            "updated_at": repo.get("updated_at", ""),
        })
    return {"items": items, "total": data.get("total_count", 0)}


@router.post("/api/clone")
async def clone_repo(req: CloneRequest):
    target = REPOS_DIR / req.name

    if target.exists():
        return JSONResponse(
            {"status": "error", "message": f"Папка '{req.name}' уже существует."},
            status_code=400,
        )

    try:
        result = subprocess.run(
            ["git", "clone", req.clone_url, str(target)],
            capture_output=True,
            timeout=180,
        )
    except FileNotFoundError:
        add_history("clone", f"Git не найден при клонировании {req.name}", "error")
        return JSONResponse(
            {"status": "error", "message": "Git не установлен или не найден в PATH."},
            status_code=500,
        )
    except subprocess.TimeoutExpired:
        add_history("clone", f"Таймаут при клонировании {req.name}", "error")
        return JSONResponse(
            {"status": "error", "message": "Клонирование превысило лимит времени."},
            status_code=500,
        )

    stderr = decode_bytes(result.stderr)

    if result.returncode != 0:
        add_history("clone", f"Ошибка Git при клонировании {req.name}: {stderr.strip()}", "error")
        return JSONResponse(
            {"status": "error", "message": f"Git error: {stderr.strip()}"},
            status_code=500,
        )

    add_history("clone", f"Репозиторий {req.name} склонирован")
    return {"status": "ok", "message": f"Репозиторий склонирован в {target}"}


@router.get("/api/repos")
async def list_repos():
    repos = []

    for item in REPOS_DIR.iterdir():
        if not item.is_dir():
            continue

        has_git = (item / ".git").exists()
        has_dockerfile = (item / "Dockerfile").exists()
        sh_files = [f for f in item.rglob("*.sh") if f.is_file()]

        total_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
        mtime = datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M")

        repos.append({
            "name": item.name,
            "path": str(item),
            "is_git": has_git,
            "has_dockerfile": has_dockerfile,
            "sh_count": len(sh_files),
            "size_mb": round(total_size / (1024 * 1024), 2),
            "modified": mtime,
        })

    repos.sort(key=lambda x: x["name"].lower())
    return {"repos": repos}


@router.get("/api/repos/{repo_name}")
async def repo_info(repo_name: str):
    repo_path = REPOS_DIR / repo_name

    if not repo_path.exists() or not repo_path.is_dir():
        raise HTTPException(status_code=404, detail="Репозиторий не найден")

    files = []
    sh_files = []
    for f in sorted(repo_path.rglob("*")):
        if f.is_file():
            rel = f.relative_to(repo_path).as_posix()
            if rel.startswith(".git/"):
                continue
            info = {
                "path": rel,
                "size": f.stat().st_size,
                "is_text": is_text_file(f),
            }
            files.append(info)
            if rel.lower().endswith(".sh"):
                sh_files.append(rel)

    git_info = {}
    if (repo_path / ".git").exists():
        try:
            branch = subprocess.run(
                ["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, timeout=10,
            ).stdout.decode("utf-8", errors="replace").strip()
            remote = subprocess.run(
                ["git", "-C", str(repo_path), "remote", "-v"],
                capture_output=True, timeout=10,
            ).stdout.decode("utf-8", errors="replace").strip()
            last_commit = subprocess.run(
                ["git", "-C", str(repo_path), "log", "-1", "--pretty=format:%h|%an|%ar|%s"],
                capture_output=True, timeout=10,
            ).stdout.decode("utf-8", errors="replace").strip()
            git_info = {"branch": branch, "remote": remote, "last_commit": last_commit}
        except Exception:
            git_info = {}

    dockerfile_content = None
    df_path = repo_path / "Dockerfile"
    if df_path.exists():
        try:
            dockerfile_content = df_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            dockerfile_content = None

    return {
        "name": repo_name,
        "files": files,
        "sh_files": sh_files,
        "git": git_info,
        "dockerfile": dockerfile_content,
        "file_count": len(files),
        "total_size_mb": round(sum(f["size"] for f in files) / (1024 * 1024), 2),
    }


@router.get("/api/repos/{repo_name}/file")
async def read_file(repo_name: str, path: str):
    repo_path = REPOS_DIR / repo_name
    file_path = (repo_path / path).resolve()

    if not str(file_path).startswith(str(repo_path.resolve())):
        raise HTTPException(status_code=400, detail="Недопустимый путь")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")

    if not is_text_file(file_path):
        return JSONResponse(
            {"status": "error", "message": "Бинарный файл, просмотр недоступен."},
            status_code=415,
        )

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"path": path, "content": content, "size": file_path.stat().st_size}


@router.delete("/api/repos/{repo_name}")
async def delete_repo(repo_name: str):
    repo_path = REPOS_DIR / repo_name

    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Репозиторий не найден")

    if repo_name in running_processes:
        try:
            running_processes[repo_name]["proc"].kill()
        except Exception:
            pass
        running_processes.pop(repo_name, None)

    try:
        shutil.rmtree(repo_path)
    except Exception as e:
        add_history("delete", f"Ошибка удаления {repo_name}: {e}", "error")
        raise HTTPException(status_code=500, detail=str(e))

    add_history("delete", f"Репозиторий {repo_name} удалён")
    return {"status": "ok", "message": f"Репозиторий {repo_name} удалён"}