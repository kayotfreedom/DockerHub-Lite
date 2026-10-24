import re
from pathlib import Path


def fix_crlf(script_path: Path) -> Path:
    try:
        raw = script_path.read_bytes()
        if b"\r\n" not in raw:
            return script_path
        fixed = raw.replace(b"\r\n", b"\n")
        temp = script_path.parent / f"_lf_{script_path.name}"
        temp.write_bytes(fixed)
        return temp
    except Exception:
        return script_path


def patch_python3_to_python(content: str) -> str:
    pattern = re.compile(r"(?<![\w./])python3(?![\w.])")
    return pattern.sub("python", content)