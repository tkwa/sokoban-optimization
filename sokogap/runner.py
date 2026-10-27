"""Resource-limited local execution of the data-only verifier on Linux."""

import json
from pathlib import Path
import subprocess
import sys

from .budget import PROCESS_LIMITS
from .core import Invalid


def run_limited(command: str, paths: list[Path], *, parameters: list[str] | None = None) -> tuple[dict, int]:
    if sys.platform != "linux":
        raise Invalid("the published resource-limited runner requires Linux")
    root = str(Path(__file__).resolve().parents[1])
    bootstrap = "import sys; sys.path.insert(0, sys.argv.pop(1)); from sokogap.worker import main; raise SystemExit(main())"
    args = [sys.executable, "-I", "-B", "-c", bootstrap, root, command,
            *[str(p.resolve()) for p in paths], *(parameters or [])]
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = process.communicate(timeout=PROCESS_LIMITS["wall_seconds"])
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return {"accepted": None, "outcome": "resource_exhausted", "error": "verification wall-time limit exceeded"}, 3
    if process.returncode < 0:
        return {"accepted": None, "outcome": "resource_exhausted",
                "error": "verifier process terminated before a decision", "signal": -process.returncode}, 3
    try:
        result = json.loads(out)
    except (ValueError, TypeError):
        return {"accepted": None, "outcome": "checker_error", "error": "verifier failed without a valid result"}, 4
    if process.returncode not in (0, 1, 2, 3) or not isinstance(result, dict):
        return {"accepted": None, "outcome": "checker_error", "error": "unexpected verifier outcome"}, 4
    return result, process.returncode
