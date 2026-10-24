import asyncio
import os
from datetime import datetime
from pathlib import Path

from config import REPOS_DIR, build_queues
from history import add_history
from dockerfile_parser import parse_dockerfile, collect_stage_config, parse_cmd
from runner import execute_run, execute_cmd
from archives import is_archive, extract_archive


async def run_build(repo_name: str, dockerfile_path: str, target_stage: str | None, queue: asyncio.Queue):
    repo_path = REPOS_DIR / repo_name
    df_path = repo_path / dockerfile_path

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
        build_queues.pop(repo_name, None)

    try:
        await log(f"🐳 Начало сборки: {repo_name}", "info")
        await log(f"📄 Dockerfile: {dockerfile_path}", "info")
        if target_stage:
            await log(f"🎯 Целевая стадия: {target_stage}", "info")

        if not df_path.exists():
            await log(f"❌ Dockerfile не найден: {df_path}", "error")
            add_history("build", f"Dockerfile не найден в {repo_name}", "error")
            await end("error", "Dockerfile не найден")
            return

        try:
            commands = parse_dockerfile(df_path)
        except Exception as e:
            await log(f"❌ Ошибка парсинга Dockerfile: {e}", "error")
            add_history("build", f"Ошибка парсинга Dockerfile в {repo_name}: {e}", "error")
            await end("error", f"Ошибка парсинга: {e}")
            return

        await log(f"📋 Найдено инструкций: {len(commands)}", "info")

        config = collect_stage_config(commands, target_stage)
        env_vars = config["env_vars"]
        dockerfile_workdir = config["workdir"]
        shell_cmd = config["shell"]

        if env_vars:
            await log(f"🌍 ENV: {env_vars}", "info")
        if dockerfile_workdir:
            await log(f"📂 WORKDIR: {dockerfile_workdir}", "info")
        if shell_cmd:
            await log(f"🐚 SHELL: {shell_cmd}", "info")
        if config["expose"]:
            await log(f"🔌 EXPOSE: {', '.join(config['expose'])}", "info")
        if config["volume"]:
            await log(f"💾 VOLUME: {', '.join(config['volume'])}", "info")
        if config["user"]:
            await log(f"👤 USER: {config['user']}", "info")

        final_parsed = None
        final_raw = ""
        if config["last_entrypoint"] and config["last_cmd"]:
            ep = parse_cmd(config["last_entrypoint"].value)
            cm = parse_cmd(config["last_cmd"].value)
            if ep:
                final_parsed = ep + (cm if cm else [])
                final_raw = " ".join(final_parsed)
        elif config["last_entrypoint"]:
            final_parsed = parse_cmd(config["last_entrypoint"].value)
            final_raw = " ".join(final_parsed) if final_parsed else ""
        elif config["last_cmd"]:
            final_parsed = parse_cmd(config["last_cmd"].value)
            final_raw = " ".join(final_parsed) if final_parsed else ""

        if final_parsed:
            await log(f"🚀 Финальная команда: {final_raw}", "info")

        stage_artifacts = {None: repo_path}
        executed = 0
        errors = 0

        for cmd in commands:
            instruction = cmd.cmd.upper()
            args = cmd.value
            line = cmd.start_line

            if instruction == "FROM":
                stage_name = None
                if args and len(args) >= 3 and str(args[-2]).upper() == "AS":
                    stage_name = str(args[-1]).strip('"')
                if stage_name:
                    stage_dir = repo_path / f"_stage_{stage_name}"
                    stage_dir.mkdir(exist_ok=True)
                    stage_artifacts[stage_name] = stage_dir
                    await log(f"[{line}] FROM — ✅ стадия '{stage_name}' -> {stage_dir.relative_to(repo_path)}", "ok")
                    executed += 1
                else:
                    await log(f"[{line}] FROM — ⚠ образ не загружен (нет Docker), но стадия продолжается", "info")

            elif instruction == "SHELL":
                await log(f"[{line}] SHELL — ✅ {shell_cmd}", "ok")
                executed += 1

            elif instruction == "RUN":
                await log(f"[{line}] RUN — {str(args)[:200]}", "info")
                run_result = await execute_run(
                    args, repo_path, dockerfile_workdir, env_vars, shell_cmd, queue, log
                )
                if run_result["status"] == "ok":
                    executed += 1
                else:
                    errors += 1

            elif instruction in ("COPY", "ADD"):
                if len(args) >= 2:
                    from_stage = None
                    args_list = [str(a) for a in args]
                    if args_list[0].startswith("--from="):
                        from_stage = args_list[0].split("=", 1)[1].strip('"')
                        args_list = args_list[1:]

                    srcs = [a.strip('"') for a in args_list[:-1]]
                    dest_str = args_list[-1].strip('"')
                    from dockerfile_parser import _substitute_vars
                    dest_str = _substitute_vars(dest_str, env_vars)
                    dest_rel = dest_str.lstrip("/")
                    dest = repo_path / dest_rel if dest_rel else repo_path

                    if from_stage:
                        base_src = stage_artifacts.get(from_stage)
                        if not base_src:
                            await log(f"[{line}] {instruction} — ❌ стадия '{from_stage}' не найдена", "error")
                            errors += 1
                            continue
                        await log(f"   📦 Источник: стадия '{from_stage}'", "info")
                    else:
                        base_src = repo_path

                    copied = 0
                    not_found = []
                    for src_str in srcs:
                        src_str = _substitute_vars(src_str, env_vars)
                        src_rel = src_str.lstrip("/")
                        src = base_src / src_rel
                        if src.exists():
                            try:
                                src_res = src.resolve()
                                dest_res = dest.resolve()
                                if src_res == dest_res or str(dest_res).startswith(str(src_res) + os.sep):
                                    await log(f"   ℹ️ {src.name}: уже на месте, пропускаю", "info")
                                    copied += 1
                                    continue
                            except Exception:
                                pass

                            try:
                                if src.is_dir():
                                    import shutil
                                    shutil.copytree(src, dest, dirs_exist_ok=True)
                                elif instruction == "ADD" and is_archive(src):
                                    extract_archive(src, dest)
                                    await log(f"   📦 Распакован архив: {src.name}", "ok")
                                else:
                                    import shutil
                                    dest.mkdir(parents=True, exist_ok=True)
                                    target = dest / src.name if dest.is_dir() else dest
                                    shutil.copy2(src, target)
                                copied += 1
                            except Exception as e:
                                await log(f"[{line}] {instruction} — ❌ {src.name}: {e}", "error")
                        else:
                            matches = list(base_src.glob(src_rel))
                            if not matches:
                                not_found.append(src_str)
                            for m in matches:
                                try:
                                    if m.is_dir():
                                        import shutil
                                        shutil.copytree(m, dest, dirs_exist_ok=True)
                                    elif instruction == "ADD" and is_archive(m):
                                        extract_archive(m, dest)
                                    else:
                                        import shutil
                                        dest.mkdir(parents=True, exist_ok=True)
                                        target = dest / m.name if dest.is_dir() else dest
                                        shutil.copy2(m, target)
                                    copied += 1
                                except Exception as e:
                                    await log(f"[{line}] {instruction} — ❌ {m.name}: {e}", "error")

                    if copied > 0:
                        await log(f"[{line}] {instruction} — ✅ скопировано: {copied} -> {dest_rel or '.'}", "ok")
                        executed += 1
                    elif not_found:
                        await log(f"[{line}] {instruction} — ⚠ источники не найдены: {', '.join(not_found)}", "info")
                    else:
                        await log(f"[{line}] {instruction} — ℹ️ нечего копировать", "info")
                else:
                    await log(f"[{line}] {instruction} — ❌ неверный формат", "error")
                    errors += 1

            elif instruction == "WORKDIR":
                await log(f"[{line}] WORKDIR — ✅ {dockerfile_workdir}", "ok")
                executed += 1

            elif instruction == "ENV":
                await log(f"[{line}] ENV — ✅ {env_vars}", "ok")
                executed += 1

            elif instruction in ("EXPOSE", "VOLUME", "USER"):
                await log(f"[{line}] {instruction} — ✅ зафиксировано", "ok")
                executed += 1

            elif instruction in ("CMD", "ENTRYPOINT"):
                await log(f"[{line}] {instruction} — зафиксировано", "info")
                executed += 1

            else:
                await log(f"[{line}] {instruction} — ❌ требует Docker", "error")
                errors += 1

        if final_parsed:
            await log("", "info")
            await log("🚀 Выполняю финальную CMD...", "info")
            result = await execute_cmd(
                parsed=final_parsed,
                repo_name=repo_name,
                repo_path=repo_path,
                dockerfile_workdir=dockerfile_workdir,
                queue=queue,
                log=log,
                extra_env=env_vars,
            )
            if result["status"] == "ok":
                executed += 1
            else:
                errors += 1

        summary = f"Выполнено: {executed}, Ошибок: {errors}"
        await log(f"🏁 Сборка завершена. {summary}", "ok" if errors == 0 else "error")
        add_history("build", f"Сборка {repo_name}: {summary}", "ok" if errors == 0 else "error")
        await end("ok" if errors == 0 else "error", summary)

    except Exception as e:
        import traceback
        await log(f"💥 Критическая ошибка: {e}", "error")
        await log(traceback.format_exc(), "error")
        add_history("build", f"Критическая ошибка сборки {repo_name}: {e}", "error")
        await end("error", str(e))