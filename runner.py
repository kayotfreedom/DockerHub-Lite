import asyncio
import re
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from config import (
    SCRIPT_TIMEOUT, MAX_LOG_LINES, LONG_RUNNING_THRESHOLD, LONG_RUNNING_MARKERS,
    SAFE_RUN_COMMANDS, UNSAFE_RUN_COMMANDS, KNOWN_EXECUTORS,
    DEPENDENCY_ERROR_PATTERNS, PYTHON3_NOT_FOUND_PATTERNS,
    build_queues, running_processes,
)
from utils import decode_bytes, make_env, find_bash
from dockerfile_parser import _substitute_vars, parse_cmd
from crlf import fix_crlf, patch_python3_to_python


async def execute_run(args, repo_path: Path, dockerfile_workdir: str, env_vars: dict, shell_cmd: list | None, queue: asyncio.Queue, log) -> dict:
    if not args:
        await log("   ❌ пустой RUN", "error")
        return {"status": "error", "detail": "пустой"}

    if isinstance(args, (list, tuple)):
        cmd_str = " ".join(str(a) for a in args)
    else:
        cmd_str = str(args)

    cmd_str = _substitute_vars(cmd_str, env_vars)

    cwd = repo_path
    workdir_rel = dockerfile_workdir.lstrip("/").rstrip("/") if dockerfile_workdir else ""
    if workdir_rel:
        candidate = repo_path / workdir_rel
        if not candidate.exists():
            try:
                candidate.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        if candidate.exists():
            cwd = candidate

    def _rewrite_path(m):
        rel = m.group(1)
        return str((repo_path / rel).resolve())

    cmd_str = re.sub(r'(?<![\w:])/([A-Za-z0-9_\-./]+)', _rewrite_path, cmd_str)

    parts = re.split(r"\s*(?:&&|\|\||;)\s*", cmd_str)
    results = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        words = part.split()
        first = words[0].lower() if words else ""

        if first in UNSAFE_RUN_COMMANDS:
            await log(f"   ❌ '{first}' требует сети/привилегий — пропускаю", "error")
            results.append(False)
            continue

        if first not in SAFE_RUN_COMMANDS:
            await log(f"   ⚠ '{first}' не в списке безопасных — пропускаю", "info")
            results.append(False)
            continue

        try:
            env = make_env(repo_path, repo_path / "Dockerfile")
            env.update(env_vars)

            if shell_cmd:
                run_cmd = shell_cmd + [part]
                result = await asyncio.to_thread(
                    subprocess.run,
                    run_cmd, cwd=str(cwd),
                    capture_output=True, timeout=30, env=env,
                )
            else:
                result = await asyncio.to_thread(
                    subprocess.run,
                    part, shell=True, cwd=str(cwd),
                    capture_output=True, timeout=30, env=env,
                )
            out = decode_bytes(result.stdout)
            err = decode_bytes(result.stderr)
            rc = result.returncode

            if rc == 0:
                await log(f"   ✅ {part}", "ok")
                if out.strip():
                    for line in out.splitlines()[:10]:
                        await log(f"      {line}", "ok")
                results.append(True)
            else:
                await log(f"   ❌ {part} (код {rc})", "error")
                if err.strip():
                    for line in err.splitlines()[:5]:
                        await log(f"      ⚠ {line}", "error")
                results.append(False)
        except subprocess.TimeoutExpired:
            await log(f"   ❌ {part} — таймаут (30 сек)", "error")
            results.append(False)
        except Exception as e:
            await log(f"   ❌ {part} — {e}", "error")
            results.append(False)

    if all(results) and results:
        return {"status": "ok", "detail": "ok"}
    return {"status": "error", "detail": "частично"}


async def execute_cmd(parsed: list, repo_name: str, repo_path: Path, dockerfile_workdir: str, queue: asyncio.Queue, log, extra_env: dict = None) -> dict:
    if not parsed:
        return {"status": "error", "detail": "пустой CMD"}

    extra_env = extra_env or {}
    parsed = [_substitute_vars(str(a), extra_env) for a in parsed]
    executor = parsed[0].strip().lower()
    rest = parsed[1:]

    cwd = repo_path
    workdir_rel = dockerfile_workdir.lstrip("/").rstrip("/") if dockerfile_workdir else ""
    if workdir_rel:
        candidate = repo_path / workdir_rel
        if candidate.exists() and candidate.is_dir():
            cwd = candidate
            await log(f"📂 Рабочая директория: {candidate.relative_to(repo_path).as_posix()}", "info")

    # bash/sh + файл-скрипт
    if executor in ("bash", "sh", "zsh") and rest and not rest[0].startswith("-"):
        script_name = rest[0]
        await log(f"🔍 Поиск скрипта: {script_name}", "info")

        candidates = [(repo_path / script_name).resolve(), (cwd / script_name).resolve()]
        try:
            for r in repo_path.rglob(script_name):
                if r.is_file() and ".git" not in r.parts:
                    candidates.append(r.resolve())
        except Exception:
            pass

        seen = set()
        unique = []
        for c in candidates:
            key = str(c).lower()
            if key not in seen:
                seen.add(key)
                unique.append(c)

        script_path = None
        for c in unique:
            if c.exists() and c.is_file():
                script_path = c
                break

        if not script_path:
            await log(f"❌ Файл '{script_name}' не найден", "error")
            return {"status": "error", "detail": "файл не найден"}

        await log(f"✅ Найден: {script_path.relative_to(repo_path).as_posix()}", "ok")

        script_path = fix_crlf(script_path)

        try:
            content = script_path.read_text(encoding="utf-8", errors="replace")
            await log("📄 Содержимое скрипта:", "info")
            for l in content.splitlines()[:50]:
                await log(f"   {l}", "info")
        except Exception as e:
            content = ""
            await log(f"❌ Ошибка чтения: {e}", "error")

        bash_exe = find_bash()
        if not bash_exe:
            await log("❌ bash не найден", "error")
            return {"status": "error", "detail": "bash не найден"}

        await log("🧪 Проверка синтаксиса (bash -n)...", "info")
        try:
            check = await asyncio.to_thread(
                subprocess.run,
                [bash_exe, "-n", str(script_path)],
                capture_output=True, timeout=10,
            )
            if check.returncode != 0:
                err = decode_bytes(check.stderr)
                await log(f"⚠️ Возможны ошибки синтаксиса: {err.strip()[:300]}", "error")
            else:
                await log("✅ Синтаксис OK", "ok")
        except Exception:
            pass

        await log("▶ Попытка 1: запуск как есть", "info")
        first = await run_script_with_stream(
            bash_exe, script_path, repo_name, repo_path, queue,
            cwd=cwd, extra_env=extra_env, allow_long_running=True
        )
        await log(f"↩ Код возврата: {first['returncode']}", "info")

        final = first
        used_fallback = False

        if first["returncode"] != 0 and not first.get("long_running"):
            combined = first["stdout"] + "\n" + first["stderr"]
            stderr_stripped = first["stderr"].strip()
            looks_py_missing = (
                any(p.search(combined) for p in PYTHON3_NOT_FOUND_PATTERNS)
                or stderr_stripped.lower().startswith("python")
            )
            if looks_py_missing:
                await log("🔁 python3 не найден — fallback на python", "info")
                patched = patch_python3_to_python(content)
                if patched != content:
                    temp = script_path.parent / f"_fallback_{script_path.name}.sh"
                    try:
                        temp.write_text(patched, encoding="utf-8", errors="replace")
                        await log(f"▶ Попытка 2: {temp.name}", "info")
                        second = await run_script_with_stream(
                            bash_exe, temp, repo_name, repo_path, queue,
                            cwd=cwd, extra_env=extra_env, allow_long_running=True
                        )
                        await log(f"↩ Код возврата: {second['returncode']}", "info")
                        final = second
                        used_fallback = True
                    except Exception as e:
                        await log(f"❌ Fallback ошибка: {e}", "error")
                    finally:
                        if temp.exists():
                            try:
                                temp.unlink()
                            except Exception:
                                pass

        out = final["stdout"]
        err = final["stderr"]
        rc = final["returncode"]
        combined = out + "\n" + err

        if final.get("long_running"):
            await log("✅ Процесс запущен и работает в фоне" + (" (fallback)" if used_fallback else ""), "ok")
            await log("   💡 Нажмите «Остановить», чтобы завершить процесс", "info")
            return {"status": "ok", "detail": "long_running"}

        if any(p.search(combined) for p in DEPENDENCY_ERROR_PATTERNS):
            await log("⚠️ Обнаружены отсутствующие зависимости!", "error")
            req_path = repo_path / "requirements.txt"
            if req_path.exists():
                await log("💡 Найден requirements.txt — можно установить зависимости", "info")
            else:
                await log("❌ requirements.txt не найден", "error")
            return {"status": "error", "detail": "зависимости"}
        elif rc == 0:
            await log("✅ Скрипт выполнен успешно" + (" (fallback)" if used_fallback else ""), "ok")
            return {"status": "ok", "detail": "ok"}
        else:
            await log(f"❌ Скрипт завершился с кодом {rc}", "error")
            return {"status": "error", "detail": f"код {rc}"}

    # bash -c "..."
    if executor in ("bash", "sh", "zsh") and rest and rest[0] in ("-c", "/c"):
        bash_exe = find_bash()
        if not bash_exe:
            await log("❌ bash не найден", "error")
            return {"status": "error", "detail": "bash не найден"}

        command_str = " ".join(rest[1:]) if len(rest) > 1 else ""
        if not command_str:
            await log("❌ Пустая команда после -c", "error")
            return {"status": "error", "detail": "пустая команда"}

        await log(f"▶ Выполняю: {executor} -c {command_str}", "info")
        result = await run_command_with_stream(
            [bash_exe, "-c", command_str], repo_name, repo_path, queue,
            cwd=cwd, extra_env=extra_env, allow_long_running=True
        )
        await log(f"↩ Код возврата: {result['returncode']}", "info")
        if result.get("long_running"):
            await log("✅ Процесс запущен и работает в фоне", "ok")
            return {"status": "ok", "detail": "long_running"}
        if result["returncode"] == 0:
            await log("✅ Команда выполнена успешно", "ok")
            return {"status": "ok", "detail": "ok"}
        else:
            await log(f"❌ Команда завершилась с кодом {result['returncode']}", "error")
            return {"status": "error", "detail": f"код {result['returncode']}"}

    # Поиск исполнителя в системе
    exe_path = shutil.which(executor)
    if not exe_path:
        local_candidate = (repo_path / parsed[0]).resolve()
        if local_candidate.exists() and local_candidate.is_file():
            await log(f"🔍 Найден локальный файл: {parsed[0]}", "info")
            if local_candidate.suffix.lower() in (".sh", ".bash"):
                bash_exe = find_bash()
                if bash_exe:
                    await log(f"▶ Запуск через bash: {parsed[0]}", "info")
                    result = await run_script_with_stream(
                        bash_exe, local_candidate, repo_name, repo_path, queue,
                        cwd=cwd, extra_env=extra_env, allow_long_running=True
                    )
                    await log(f"↩ Код возврата: {result['returncode']}", "info")
                    if result.get("long_running"):
                        return {"status": "ok", "detail": "long_running"}
                    if result["returncode"] == 0:
                        await log("✅ Скрипт выполнен", "ok")
                        return {"status": "ok", "detail": "ok"}
                    else:
                        await log(f"❌ Скрипт завершился с кодом {result['returncode']}", "error")
                        return {"status": "error", "detail": f"код {result['returncode']}"}
            else:
                await log(f"▶ Запуск файла напрямую: {parsed[0]}", "info")
                result = await run_command_with_stream(
                    [str(local_candidate)] + rest, repo_name, repo_path, queue,
                    cwd=cwd, extra_env=extra_env, allow_long_running=True
                )
                await log(f"↩ Код возврата: {result['returncode']}", "info")
                if result.get("long_running"):
                    return {"status": "ok", "detail": "long_running"}
                if result["returncode"] == 0:
                    await log("✅ Файл выполнен", "ok")
                    return {"status": "ok", "detail": "ok"}
                else:
                    await log(f"❌ Файл завершился с кодом {result['returncode']}", "error")
                    return {"status": "error", "detail": f"код {result['returncode']}"}

        await log(f"❌ Команда '{parsed[0]}' не найдена", "error")
        if executor in KNOWN_EXECUTORS:
            await log(f"   💡 '{executor}' не установлен.", "info")
        return {"status": "error", "detail": f"'{parsed[0]}' не найден"}

    await log(f"▶ Выполняю: {' '.join(parsed)}", "info")
    await log(f"   (исполнитель: {exe_path})", "info")
    result = await run_command_with_stream(
        [exe_path] + rest, repo_name, repo_path, queue,
        cwd=cwd, extra_env=extra_env, allow_long_running=True
    )
    await log(f"↩ Код возврата: {result['returncode']}", "info")

    if result.get("long_running"):
        await log("✅ Процесс запущен и работает в фоне", "ok")
        return {"status": "ok", "detail": "long_running"}
    if result["returncode"] == 0:
        await log("✅ Команда выполнена успешно", "ok")
        return {"status": "ok", "detail": "ok"}
    else:
        await log(f"❌ Команда завершилась с кодом {result['returncode']}", "error")
        return {"status": "error", "detail": f"код {result['returncode']}"}


async def run_command_with_stream(cmd: list, repo_name: str, repo_path: Path, queue: asyncio.Queue, cwd: Path = None, extra_env: dict = None, allow_long_running: bool = False) -> dict:
    loop = asyncio.get_running_loop()
    extra_env = extra_env or {}
    work_cwd = cwd or repo_path

    def _sync():
        try:
            env = make_env(repo_path, repo_path / "Dockerfile")
            env.update(extra_env)
            proc = subprocess.Popen(
                cmd,
                cwd=str(work_cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError:
            return {"returncode": -2, "stdout": "", "stderr": f"Команда не найдена: {cmd[0]}"}
        except Exception as e:
            return {"returncode": -2, "stdout": "", "stderr": f"Ошибка: {e}"}

        lines_out, lines_err = [], []
        line_count = [0]
        marker_found = [False]

        def push(line: str, level: str):
            try:
                if line_count[0] >= MAX_LOG_LINES:
                    if line_count[0] == MAX_LOG_LINES:
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            {"type": "log", "level": "info", "text": "   ... (вывод обрезан, слишком много строк)", "time": datetime.now().strftime("%H:%M:%S")},
                        )
                    line_count[0] += 1
                    return
                line_count[0] += 1
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "log", "level": level, "text": line, "time": datetime.now().strftime("%H:%M:%S")},
                )
                if allow_long_running:
                    for m in LONG_RUNNING_MARKERS:
                        if m.search(line):
                            marker_found[0] = True
                            break
            except Exception:
                pass

        def read(stream, lines, level, prefix):
            try:
                for raw in iter(stream.readline, b""):
                    line = decode_bytes(raw).rstrip()
                    if line:
                        lines.append(line)
                        push(f"   {prefix}: {line}", level)
            except Exception:
                pass

        t1 = threading.Thread(target=read, args=(proc.stdout, lines_out, "ok", "stdout"), daemon=True)
        t2 = threading.Thread(target=read, args=(proc.stderr, lines_err, "error", "stderr"), daemon=True)
        t1.start()
        t2.start()

        waited = 0
        while waited < SCRIPT_TIMEOUT:
            try:
                proc.wait(timeout=1)
                break
            except subprocess.TimeoutExpired:
                waited += 1
                if allow_long_running and waited >= LONG_RUNNING_THRESHOLD and marker_found[0]:
                    running_processes[repo_name] = {"proc": proc, "script": str(cmd[0])}
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {"type": "log", "level": "ok", "text": "   🟢 Процесс оставлен работать в фоне", "time": datetime.now().strftime("%H:%M:%S")},
                    )
                    return {
                        "returncode": 0,
                        "stdout": "\n".join(lines_out),
                        "stderr": "\n".join(lines_err),
                        "long_running": True,
                    }

        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            return {"returncode": -1, "stdout": "\n".join(lines_out), "stderr": f"Таймаут ({SCRIPT_TIMEOUT} сек)."}

        t1.join(timeout=2)
        t2.join(timeout=2)

        return {"returncode": proc.returncode, "stdout": "\n".join(lines_out), "stderr": "\n".join(lines_err)}

    return await asyncio.to_thread(_sync)


async def run_script_with_stream(bash_exe: str, script_path: Path, repo_name: str, repo_path: Path, queue: asyncio.Queue, cwd: Path = None, extra_env: dict = None, allow_long_running: bool = False) -> dict:
    loop = asyncio.get_running_loop()
    extra_env = extra_env or {}
    work_cwd = cwd or script_path.parent

    def _sync():
        try:
            env = make_env(repo_path, script_path)
            env.update(extra_env)
            proc = subprocess.Popen(
                [bash_exe, str(script_path)],
                cwd=str(work_cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        except Exception as e:
            return {"returncode": -2, "stdout": "", "stderr": f"Ошибка: {e}"}

        lines_out, lines_err = [], []
        line_count = [0]
        marker_found = [False]

        def push(line: str, level: str):
            try:
                if line_count[0] >= MAX_LOG_LINES:
                    if line_count[0] == MAX_LOG_LINES:
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            {"type": "log", "level": "info", "text": "   ... (вывод обрезан)", "time": datetime.now().strftime("%H:%M:%S")},
                        )
                    line_count[0] += 1
                    return
                line_count[0] += 1
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "log", "level": level, "text": line, "time": datetime.now().strftime("%H:%M:%S")},
                )
                if allow_long_running:
                    for m in LONG_RUNNING_MARKERS:
                        if m.search(line):
                            marker_found[0] = True
                            break
            except Exception:
                pass

        def read(stream, lines, level, prefix):
            try:
                for raw in iter(stream.readline, b""):
                    line = decode_bytes(raw).rstrip()
                    if line:
                        lines.append(line)
                        push(f"   {prefix}: {line}", level)
            except Exception:
                pass

        t1 = threading.Thread(target=read, args=(proc.stdout, lines_out, "ok", "stdout"), daemon=True)
        t2 = threading.Thread(target=read, args=(proc.stderr, lines_err, "error", "stderr"), daemon=True)
        t1.start()
        t2.start()

        waited = 0
        while waited < SCRIPT_TIMEOUT:
            try:
                proc.wait(timeout=1)
                break
            except subprocess.TimeoutExpired:
                waited += 1
                if allow_long_running and waited >= LONG_RUNNING_THRESHOLD and marker_found[0]:
                    running_processes[repo_name] = {"proc": proc, "script": str(script_path)}
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {"type": "log", "level": "ok", "text": "   🟢 Процесс оставлен работать в фоне", "time": datetime.now().strftime("%H:%M:%S")},
                    )
                    return {
                        "returncode": 0,
                        "stdout": "\n".join(lines_out),
                        "stderr": "\n".join(lines_err),
                        "long_running": True,
                    }

        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            return {"returncode": -1, "stdout": "\n".join(lines_out), "stderr": f"Таймаут ({SCRIPT_TIMEOUT} сек)."}

        t1.join(timeout=2)
        t2.join(timeout=2)

        return {"returncode": proc.returncode, "stdout": "\n".join(lines_out), "stderr": "\n".join(lines_err)}

    return await asyncio.to_thread(_sync)