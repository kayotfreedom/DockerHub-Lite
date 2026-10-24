import re
from pathlib import Path


def _substitute_vars(text: str, env: dict) -> str:
    if not text or not env:
        return text
    result = text
    for key, value in env.items():
        result = result.replace(f"${{{key}}}", str(value))
        result = re.sub(rf"\${re.escape(key)}(?![A-Za-z0-9_])", str(value), result)
    return result


def parse_cmd(args) -> list | None:
    import json
    import ast
    import shlex

    if not args:
        return None
    if isinstance(args, (list, tuple)):
        items = [str(a).strip() for a in args if str(a).strip()]
        if not items:
            return None
        if len(items) == 1 and " " in items[0]:
            try:
                return shlex.split(items[0])
            except Exception:
                return items[0].split()
        return items
    s = str(args).strip()
    if not s:
        return None
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(a) for a in parsed]
        except Exception:
            pass
    if s.startswith("(") and s.endswith(")"):
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, (list, tuple)):
                return [str(a) for a in parsed]
        except Exception:
            pass
    try:
        return shlex.split(s)
    except Exception:
        return s.split()


def parse_dockerfile(df_path: Path) -> list:
    import dockerfile
    return dockerfile.parse_file(str(df_path))


def collect_stage_config(commands: list, target_stage: str | None) -> dict:
    stages = []
    current_stage = {"name": None, "commands": []}

    for cmd in commands:
        instr = cmd.cmd.upper()
        if instr == "FROM":
            if current_stage["commands"]:
                stages.append(current_stage)
            stage_name = None
            args = cmd.value
            if args and len(args) >= 3 and str(args[-2]).upper() == "AS":
                stage_name = str(args[-1]).strip('"')
            current_stage = {"name": stage_name, "commands": [cmd]}
        else:
            current_stage["commands"].append(cmd)
    if current_stage["commands"]:
        stages.append(current_stage)

    if target_stage:
        idx = None
        for i, s in enumerate(stages):
            if s["name"] and s["name"].lower() == target_stage.lower():
                idx = i
                break
        if idx is not None:
            stages = stages[:idx + 1]

    env_vars = {}
    workdir = "/"
    shell = None
    expose = []
    volume = []
    user = None
    last_cmd = None
    last_entrypoint = None

    for stage in stages:
        for cmd in stage["commands"]:
            instr = cmd.cmd.upper()
            args = cmd.value
            if instr == "ENV":
                if args:
                    if "=" in str(args[0]):
                        for a in args:
                            if "=" in str(a):
                                k, _, v = str(a).partition("=")
                                env_vars[k.strip()] = v.strip()
                    elif len(args) >= 2:
                        env_vars[str(args[0]).strip()] = " ".join(str(x) for x in args[1:]).strip()
            elif instr == "WORKDIR":
                workdir = _substitute_vars(str(args[0]).strip('"') if args else "/", env_vars)
            elif instr == "SHELL":
                shell = parse_cmd(args) if args else None
            elif instr == "EXPOSE":
                expose.extend(str(a) for a in args)
            elif instr == "VOLUME":
                volume.extend(str(a) for a in args)
            elif instr == "USER":
                user = " ".join(str(a) for a in args)
            elif instr == "CMD":
                last_cmd = cmd
            elif instr == "ENTRYPOINT":
                last_entrypoint = cmd

    return {
        "stages": stages,
        "env_vars": env_vars,
        "workdir": workdir,
        "shell": shell,
        "expose": expose,
        "volume": volume,
        "user": user,
        "last_cmd": last_cmd,
        "last_entrypoint": last_entrypoint,
    }