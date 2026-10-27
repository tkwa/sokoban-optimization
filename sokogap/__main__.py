import argparse
import json
from pathlib import Path
import sys

from .certificates import verify_lower
from .core import Board, Invalid, replay
from .judge import read_text
from .release import prepare_freeze
from .runner import run_limited
from .search import prove


def main():
    parser = argparse.ArgumentParser(description="Verify and score Sokoban gap closure")
    sub = parser.add_subparsers(dest="command", required=True)
    audit_parser = sub.add_parser("audit", help="check baseline evidence and freeze status")
    audit_parser.add_argument("manifest", type=Path)
    score_parser = sub.add_parser("score", help="score a submission against a verified frozen baseline")
    score_parser.add_argument("manifest", type=Path)
    score_parser.add_argument("submission", type=Path)
    score_parser.add_argument("--reviews", type=Path, help="trusted maintainer review registry; never participant supplied")
    freeze_parser = sub.add_parser("freeze", help="create a new local release after baseline verification")
    freeze_parser.add_argument("draft", type=Path)
    freeze_parser.add_argument("output", type=Path)
    replay_parser = sub.add_parser("replay", help="verify a complete legal solution and count its pushes")
    replay_parser.add_argument("board", type=Path)
    replay_parser.add_argument("solution", type=Path)
    lower_parser = sub.add_parser("verify-lower", help="verify a lower-bound certificate")
    lower_parser.add_argument("board", type=Path)
    lower_parser.add_argument("certificate", type=Path)
    encode_parser = sub.add_parser("encode-sat", help="write the exact CNF for fewer than LOWER pushes")
    encode_parser.add_argument("board", type=Path)
    encode_parser.add_argument("lower", type=int)
    encode_parser.add_argument("output", type=Path)
    prove_parser = sub.add_parser("prove", help="run the reference A* and emit a lower-bound certificate")
    prove_parser.add_argument("board", type=Path)
    prove_parser.add_argument("output", type=Path)
    prove_parser.add_argument("--expansions", type=int, default=1000)
    prove_parser.add_argument("--seconds", type=float, default=10.0)
    args = parser.parse_args()
    try:
        status = 0
        if args.command in {"audit", "score"}:
            paths = [args.manifest] + ([args.submission] if args.command == "score" else [])
            if args.command == "score" and args.reviews is not None:
                paths.append(args.reviews)
            result, status = run_limited(args.command, paths)
        elif args.command == "encode-sat":
            if args.lower < 1:
                raise Invalid("SAT lower bound must be positive")
            result, status = run_limited("encode-sat", [args.board, args.output], parameters=[str(args.lower)])
        elif args.command in {"replay", "verify-lower"}:
            evidence = args.solution if args.command == "replay" else args.certificate
            result, status = run_limited(args.command, [args.board, evidence])
        elif args.command == "freeze":
            result = prepare_freeze(args.draft, args.output)
        else:
            board = Board.parse(read_text(args.board, 8192))
            if not 0 <= args.expansions <= 100_000 or not 0 < args.seconds <= 60:
                raise Invalid("use 0..100000 expansions and 0 < seconds <= 60")
            certificate, result = prove(board, args.expansions, args.seconds)
            verify_lower(board, certificate)
            args.output.write_text(json.dumps(certificate, separators=(",", ":"))+"\n")
        print(json.dumps(result, indent=2))
        return status
    except (Invalid, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"accepted": False, "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
