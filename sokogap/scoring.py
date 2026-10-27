"""Each certified push of gap closure has exactly the same weight."""

from dataclasses import dataclass
from fractions import Fraction

from .core import Invalid


def integer(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise Invalid(f"{name} must be a nonnegative integer")
    return value


@dataclass(frozen=True)
class Bounds:
    lower: int
    upper: int

    def __post_init__(self):
        integer(self.lower, "lower bound")
        integer(self.upper, "upper bound")
        if self.lower > self.upper:
            raise Invalid("lower bound exceeds upper bound")

    @property
    def gap(self) -> int:
        return self.upper - self.lower

    def improve(self, lower: int | None = None, upper: int | None = None) -> "Bounds":
        """Arguments must already have been certified by the judge."""
        return Bounds(max(self.lower, integer(lower, "lower bound")) if lower is not None else self.lower,
                      min(self.upper, integer(upper, "upper bound")) if upper is not None else self.upper)


def score(baseline: dict[str, Bounds], verified: dict[str, Bounds]) -> dict:
    if len(baseline) != 10:
        raise Invalid("the benchmark must contain exactly 10 instances")
    if any(bounds.gap <= 0 for bounds in baseline.values()):
        raise Invalid("each baseline instance must have a positive gap")
    if set(verified) - set(baseline):
        raise Invalid("unknown instance in submission")
    total_gap = sum(b.gap for b in baseline.values())
    rows = []
    for name, initial in baseline.items():
        result = verified.get(name, initial)
        current = initial.improve(result.lower, result.upper)
        closed = initial.gap - current.gap
        rows.append({"id": name, "baseline_lower": initial.lower, "baseline_upper": initial.upper,
                     "lower": current.lower, "upper": current.upper, "initial_gap": initial.gap,
                     "remaining_gap": current.gap, "pushes_closed": closed,
                     "instance_percent": float(Fraction(100 * closed, initial.gap)),
                     "contribution_percentage_points": float(Fraction(100 * closed, total_gap))})
    closed = sum(row["pushes_closed"] for row in rows)
    percent = Fraction(100 * closed, total_gap)
    return {"initial_gap_pushes": total_gap, "remaining_gap_pushes": total_gap-closed,
            "pushes_closed": closed, "score_percent": float(percent),
            "score_percent_exact": f"{percent.numerator}/{percent.denominator}", "instances": rows}
