"""Internal subprocess entry point; never executes submitted code."""

import json
from pathlib import Path
import resource
import sys

from .budget import Exhausted, PROCESS_LIMITS, work_budget
from .certificates import verify_lower
from .core import Board, Invalid, replay
from .judge import audit, judge, read_json, read_text


def main():
    resource.setrlimit(resource.RLIMIT_AS, (PROCESS_LIMITS["memory_bytes"],) * 2)
    cpu = PROCESS_LIMITS["cpu_seconds"]
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    command, *paths = sys.argv[1:]
    paths = list(map(Path, paths))
    code = 0
    try:
        with work_budget() as used:
            if command == "audit" and len(paths) == 1:
                result, _, _ = audit(paths[0])
                code = 0 if result["scoreable"] else 2
            elif command == "score" and len(paths) == 2:
                result = judge(*paths)
                result.update(accepted=True, outcome="accepted")
            elif command in {"verify-lower", "replay"} and len(paths) == 2:
                board = Board.parse(read_text(paths[0], 8192))
                if command == "verify-lower":
                    result = {"verified_lower": verify_lower(board, read_json(paths[1]))}
                else:
                    result = vars(replay(board, read_text(paths[1], 4_000_000)))
                result.update(accepted=True, outcome="accepted")
            else:
                raise Invalid("invalid verifier worker command")
            result["verification_work"] = dict(used)
    except (Exhausted, MemoryError) as error:
        result = {"accepted": None, "outcome": "resource_exhausted", "error": str(error) or "verification memory limit exceeded"}
        code = 3
    except (Invalid, OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        result = {"accepted": False, "outcome": "invalid", "error": str(error)}
        code = 1
    print(json.dumps(result, indent=2))
    return code
