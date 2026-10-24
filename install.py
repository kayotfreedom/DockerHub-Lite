import asyncio
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from config import REPOS_DIR, build_queues, WHEEL_BUILD_ERROR_PATTERNS, _NOT_PACKAGES
from history import add_history
from utils import decode_bytes
from dockerfile_parser import parse_dockerfile, collect_stage_config, parse_cmd
from runner import execute_cmd


def extract_problem_packages(output: str) -> list:
    found = set()
    for pattern in WHEEL_BUILD_ERROR_PATTERNS:
        for m in pattern.finditer(output):
            name = m.group(1).strip().lower()
            if not name or name in _NOT_PACKAGES:
                continue
            if len(name) < 2 or len(name) > 80 or " " in name:
                continue
            found.add(name)
    return sorted(found)


async def run_install(repo_name: str, requirements_path: str, queue: asyncio.Queue):
    async def log(text: str, level: str = "info"):
        await queue.put({
            "type": "log",
            "level": level,
            "text": text,
            "time": datetime.now().strftime("%H:%M:%S"),
        })

    async def end(status: str = "ok", summary: str = ""):
        await queue.put({"type": "end", "status": status, "summary": summary})
        await asyncio.sleep(2)
        build_queues.pop(f"install:{repo_name}", None)

    try:
        repo_path = REPOS_DIR / repo_name
        req_path = (repo_path / requirements_path).resolve()

        if not str(req_path).startswith(str(repo_path.resolve())):
            await log("❌ Недопустимый путь", "error")
            await end("error", "Недопустимый путь")
            return

        if not req_path.exists():
            await log(f"❌ Файл не найден: {requirements_path}", "error")
            await end("error", "Файл не найден")
            return

        python_exe = shutil.which("python") or shutil.which("python3")
        if not python_exe:
            await log("❌ Python не найден в PATH", "error")
            await end("error", "Python не найден")
            return

        await log(f"📦 pip install -r {requirements_path}", "info")
        await log(f"🐍 Python: {python_exe}", "info")
        await log("⏳ Это может занять несколько минут...", "info")

        async def run_pip(cmd: list, cwd: str) -> dict:
            def _sync():
                try:
                    proc = subprocess.Popen(
                        cmd, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1,
                    )
                except Exception as e:
                    return ("launch_error", str(e))

                lines_out, lines_err = [], []

                def read_stream(stream, lines):
                    try:
                        for raw in iter(stream.readline, b""):
                            line = decode_bytes(raw).rstrip()
                            if line:
                                lines.append(line)
                    except Exception:
                        pass

                t_out = threading.Thread(target=read_stream, args=(proc.stdout, lines_out), daemon=True)
                t_err = threading.Thread(target=read_stream, args=(proc.stderr, lines_err), daemon=True)
                t_out.start(); t_err.start()
                proc.wait()
                t_out.join(timeout=5); t_err.join(timeout=5)
                return (proc.returncode, {"stdout": lines_out, "stderr": lines_err})

            return await asyncio.to_thread(_sync)

        try:
            content = req_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            await log(f"❌ Не удалось прочитать requirements.txt: {e}", "error")
            await end("error", str(e))
            return

        raw_lines = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            raw_lines.append(stripped)

        await log(f"📋 Пакетов в requirements.txt: {len(raw_lines)}", "info")

        ignored = set()
        installed_ok = []
        failed = []

        total = len(raw_lines)
        for idx, pkg_line in enumerate(raw_lines, start=1):
            await log("", "info")
            await log(f"[{idx}/{total}] 📦 {pkg_line}", "info")

            cmd = [python_exe, "-m", "pip", "install", pkg_line]
            await log(f"   $ pip install {pkg_line}", "info")
            result = await run_pip(cmd, str(repo_path))

            if isinstance(result, tuple) and len(result) == 2 and result[0] == "launch_error":
                await log(f"   ❌ Ошибка запуска pip: {result[1]}", "error")
                failed.append(pkg_line)
                continue

            rc, streams = result
            stdout_text = "\n".join(streams["stdout"])
            stderr_text = "\n".join(streams["stderr"])

            if rc != 0:
                for line in streams["stdout"][-50:]:
                    await log(f"     {line}", "info")
                for line in streams["stderr"][-30:]:
                    await log(f"     ⚠ {line}", "info")

            if rc == 0:
                await log(f"   ✅ установлен", "ok")
                installed_ok.append(pkg_line)
                continue

            combined = stdout_text + "\n" + stderr_text
            problem_pkgs = extract_problem_packages(combined)

            if not problem_pkgs:
                await log(f"   ❌ pip код {rc} (не ошибка сборки — пропускаем)", "error")
                failed.append(pkg_line)
                continue

            await log(f"   ⚠ Ошибка сборки wheel: {', '.join(problem_pkgs)}", "error")

            await log(f"   🔁 Пробую --only-binary для {pkg_line}", "info")
            cmd = [python_exe, "-m", "pip", "install", pkg_line, "--only-binary=:all:"]
            result = await run_pip(cmd, str(repo_path))
            if isinstance(result, tuple) and len(result) == 2 and result[0] != "launch_error":
                rc2, streams2 = result
                if rc2 == 0:
                    await log(f"   ✅ установлен через --only-binary", "ok")
                    installed_ok.append(pkg_line)
                    continue
                for line in streams2["stderr"][-10:]:
                    await log(f"     ⚠ {line}", "info")

            await log(f"   🔁 Пробую --no-deps для {pkg_line}", "info")
            cmd = [python_exe, "-m", "pip", "install", pkg_line, "--no-deps"]
            result = await run_pip(cmd, str(repo_path))
            if isinstance(result, tuple) and len(result) == 2 and result[0] != "launch_error":
                rc3, streams3 = result
                if rc3 == 0:
                    await log(f"   ✅ установлен через --no-deps", "ok")
                    installed_ok.append(pkg_line)
                    continue
                for line in streams3["stderr"][-10:]:
                    await log(f"     ⚠ {line}", "info")

            for p in problem_pkgs:
                ignored.add(p)
            await log(f"   ❌ {pkg_line} пропущен (не удалось поставить)", "error")
            failed.append(pkg_line)

        if installed_ok and not failed:
            await log("", "info")
            await log("🚀 Зависимости установлены. Запускаю CMD из Dockerfile...", "info")

            df_path = repo_path / "Dockerfile"
            if df_path.exists():
                try:
                    commands = parse_dockerfile(df_path)
                    config = collect_stage_config(commands, None)
                    parsed_cmd = None
                    if config["last_entrypoint"] and config["last_cmd"]:
                        ep = parse_cmd(config["last_entrypoint"].value)
                        cm = parse_cmd(config["last_cmd"].value)
                        if ep:
                            parsed_cmd = ep + (cm if cm else [])
                    elif config["last_entrypoint"]:
                        parsed_cmd = parse_cmd(config["last_entrypoint"].value)
                    elif config["last_cmd"]:
                        parsed_cmd = parse_cmd(config["last_cmd"].value)

                    if parsed_cmd:
                        result = await execute_cmd(
                            parsed=parsed_cmd,
                            repo_name=repo_name,
                            repo_path=repo_path,
                            dockerfile_workdir=config["workdir"],
                            queue=queue,
                            log=log,
                            extra_env=config["env_vars"],
                        )
                        if result["status"] == "ok":
                            await log("✅ CMD выполнен успешно", "ok")
                        else:
                            await log(f"❌ CMD завершился с ошибкой: {result['detail']}", "error")
                    else:
                        await log("⚠️ CMD не найден в Dockerfile", "info")
                except Exception as e:
                    await log(f"⚠️ Не удалось разобрать Dockerfile: {e}", "info")

        await log("", "info")
        summary_parts = []
        if installed_ok:
            summary_parts.append(f"установлено: {len(installed_ok)}")
        if failed:
            summary_parts.append(f"пропущено: {len(failed)}")
        if ignored:
            summary_parts.append(f"проблемные: {', '.join(sorted(ignored))}")

        summary = "Установка завершена. " + ", ".join(summary_parts) if summary_parts else "Установка завершена"

        if failed:
            await log(f"⚠️ Пропущенные пакеты: {', '.join(failed)}", "error")
            await log(f"🏁 {summary}", "info")
            add_history("install", f"pip install в {repo_name}: {summary}", "error" if not installed_ok else "ok")
            await end("ok" if installed_ok else "error", summary)
        else:
            await log(f"✅ Все пакеты установлены", "ok")
            await log(f"🏁 {summary}", "ok")
            add_history("install", f"pip install в {repo_name}: {summary}", "ok")
            await end("ok", summary)

    except Exception as e:
        import traceback
        await log(f"💥 Ошибка: {e}", "error")
        await log(traceback.format_exc(), "error")
        await end("error", str(e))