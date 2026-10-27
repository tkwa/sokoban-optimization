"""Rebuild the source audit and provisional selection from archived sources.

Run from the project root: python3 -m scripts.import_xsokoban
Only data is read from third-party archives; no third-party code is executed.
"""

import base64
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tarfile
from urllib.parse import parse_qs, urlparse

from sokogap.core import Board, MatchingBound, replay

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "research/source"


class Table(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.boards = {}
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = ""
        elif tag == "a":
            href = attrs.get("href", "")
            if "?json=" in href:
                row = json.loads(base64.b64decode(parse_qs(urlparse(href).query)["json"][0]))
                self.boards[row["Level No."]] = row["Board"]

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            if self.row is not None:
                self.row.append(" ".join(self.cell.split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row and self.row[0].isdigit():
                self.rows.append(self.row)
            self.row = None


def load_table(name):
    parser = Table()
    parser.feed((SOURCE/name).read_text())
    return parser


def main():
    stats = {int(row[0]): row for row in load_table("statistics.html").rows}
    optimal = load_table("xsokoban-optimal.html")
    assert len(stats) == len(optimal.rows) == len(optimal.boards) == 90
    unresolved = {int(row[0]) for row in optimal.rows if not row[2].isdigit()}
    assert len(unresolved) == 17
    text = (SOURCE/"ijcai2016.txt").read_text()
    table = text[text.index("\n       #    1I"):text.index("5     Experimental Results")]
    paper = {}
    for line in table.splitlines():
        if re.fullmatch(r"\s*\d[\d\s]*", line):
            nums = list(map(int, line.split()))
            assert len(nums) % 5 == 0
            for i in range(0, len(nums), 5):
                number, *bounds, upper = nums[i:i+5]
                paper[number] = {"initial_heuristics": bounds, "lower": max(bounds), "upper": upper}
    assert len(paper) == 90
    solutions = [line.split(":", 1) for line in (SOURCE/"xsokoban-solutions.txt").read_text().splitlines() if line]
    assert len(solutions) == 90
    for folder in ("instances", "evidence/solutions", "evidence/lower", "research"):
        (ROOT/folder).mkdir(parents=True, exist_ok=True)
    records = []
    with tarfile.open(SOURCE/"xsokoban-3.3c.tar.gz") as archive:
        for number in sorted(unresolved):
            board = Board.parse("\n".join(optimal.boards[number]))
            original = Board.parse(archive.extractfile(f"xsokoban/screens/screen.{number}").read().decode())
            assert board == original, f"board variant mismatch at {number}"
            source_id, solution = solutions[number-1]
            witness = replay(board, solution)
            upper = int(stats[number][-1])
            lower = max(paper[number]["lower"], int(stats[number][-2]))
            name = f"xsokoban-{number:02}"
            board_path = f"instances/{name}.xsb"
            solution_path = f"evidence/solutions/{name}-festival.lurd"
            (ROOT/board_path).write_text(board.text())
            (ROOT/solution_path).write_text(solution+"\n")
            records.append({
                "id": name, "board": board_path, "board_sha256": board.digest,
                "collection": "XSokoban", "number": number, "boxes": len(board.boxes), "floor_cells": len(board.floor),
                "reported_lower": lower, "reported_upper": upper, "reported_gap": upper-lower,
                "independently_computed_matching_lower": MatchingBound(board).cost(board.boxes),
                "replayed_upper": witness.pushes, "replayed_solution": solution_path,
                "board_matches_cornell_3_3c": True,
                "lower_source": "IJCAI 2016, Table 1, maximum initial heuristic; stronger than the statistics table for this board",
                "upper_source": "Sokoban Solver Statistics, XSokoban, table dated 2026-04-28",
                "optimal_solver_status": "Sokolution 7.32 did not finish within 30 minutes in the published test",
                "upper_witness_source": "solver-tools.zip: Script/Utilities/XSokoban Solutions.txt (Festival traces)",
                "record_url": f"https://www.letslogic.com/level/{source_id}",
            })
    # Largest documented residual gaps among the 17 boards; ties by level number.
    selected = sorted(records, key=lambda r: (-r["reported_gap"], r["number"]))[:10]
    total_gap = sum(r["reported_gap"] for r in selected)
    live_path = ROOT / "research/live-records-2026-10-26.json"
    if live_path.exists():
        live = {r["number"]: r for r in json.loads(live_path.read_text())["records"]}
        for row in selected:
            assert row["reported_upper"] == live[row["number"]]["pushes"]
            row["upper_source"] = "Let's Logic live Site Push Record, checked 2026-10-26; corroborates the 2026-04-28 statistics table"
            row["record_url"] = live[row["number"]]["url"]
    for row in selected:
        row["share_of_total_gap_percent"] = 100 * row["reported_gap"] / total_gap
    report = {"status": "provisional; current lower-bound records and exact upper witnesses still under audit",
              "selection": "ten largest documented gaps in XSokoban after excluding 73 reported optimal solves",
              "source_checked_date": "2026-10-26", "lower_source_year": 2016,
              "selected_ids": [r["id"] for r in selected], "total_reported_lower": sum(r["reported_lower"] for r in selected),
              "total_reported_upper": sum(r["reported_upper"] for r in selected), "total_reported_gap": total_gap,
              "percentage_points_per_push": 100/total_gap, "selected": selected, "pool": records,
              "sources": [json.loads(p.read_text()) for p in sorted(SOURCE.glob("*.meta.json"))]}
    (ROOT/"research/candidates.json").write_text(json.dumps(report, indent=2)+"\n")
    instances = []
    for row in selected:
        instances.append({"id": row["id"], "board": row["board"], "board_sha256": row["board_sha256"],
                          "lower": row["reported_lower"], "upper": row["reported_upper"],
                          "lower_certificate": None, "upper_solution": None,
                          "audit_reference": "research/candidates.json"})
    manifest = {"format": "sokogap-benchmark-v1", "benchmark_id": "xsokoban-gap10-draft-2026-10-26",
                "status": "draft", "metric": "pushes", "aggregation": "total_gap_closed",
                "snapshot_date": "2026-10-26", "instances": instances}
    path = ROOT/"benchmark.draft.json"
    if not path.exists():
        path.write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps({key:report[key] for key in ("selected_ids", "total_reported_lower", "total_reported_upper", "total_reported_gap")}, indent=2))


if __name__ == "__main__":
    main()
