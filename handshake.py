"""Offline trace of one HMI sending a recipe selection to one simulated PLC."""

from dataclasses import dataclass
import argparse
import json
from pathlib import Path

RECIPES = frozenset({"small", "large"})


@dataclass(frozen=True)
class Request:
    epoch: int
    seq: int
    recipe: str

    def __post_init__(self):
        for key in ("epoch", "seq"):
            value = getattr(self, key)
            if type(value) is not int or value < 1:
                raise ValueError(f"{key} must be a positive integer")
        if not isinstance(self.recipe, str) or not self.recipe.strip():
            raise ValueError("recipe must be a nonempty string")


class Controller:
    def __init__(self):
        self.epoch = 1
        self.recipe = "small"
        self.apply_count = 0  # Lab instrumentation, not a PLC tag.
        self._clear()

    def _clear(self):
        self.mailbox = None
        self.pending = None
        self.report = None  # (Request, phase); only the newest result is kept.
        self.high_water = 0

    def write(self, request):
        if self.mailbox not in (None, request):
            raise ValueError("mailbox occupied: keep only one command in flight")
        self.mailbox = request
        return "buffered"

    def scan(self):
        if self.pending is not None:
            request, self.pending = self.pending, None
            if request.recipe in RECIPES:
                self.recipe = request.recipe
                self.apply_count += 1
                phase = "applied"
            else:
                phase = "rejected"
            self.report = (request, phase)
            return phase

        request, self.mailbox = self.mailbox, None
        if request is None:
            return "idle"
        if request.epoch != self.epoch:
            return "wrong_epoch"
        if request.seq < self.high_water:
            return "old_sequence"
        if request.seq == self.high_water:
            return "duplicate" if self.report[0] == request else "sequence_conflict"

        self.high_water = request.seq
        self.pending = request
        self.report = (request, "accepted")
        return "accepted"

    def observe(self, request, *, connected=True, expired=False):
        """Model a fresh read, or an unavailable read; never consume cached tags."""
        if not connected:
            return "unknown" if expired else "waiting"
        if request.epoch != self.epoch:
            return "reconcile"
        if self.report is not None and self.report[0] == request:
            phase = self.report[1]
            if phase in ("applied", "rejected") or not expired:
                return phase
        return "unknown" if expired else "waiting"

    def restart(self):
        self.epoch += 1
        self._clear()
        # Deliberately preserve the mock process value: restart is not rollback.
        return "restarted"


def trace(events):
    plc = Controller()
    for n, event in enumerate(events, 1):
        op = event["op"]
        if op in ("write", "observe"):
            request = Request(event["epoch"], event["seq"], event["recipe"])
            if op == "write":
                result = plc.write(request)
            else:
                connected = event.get("connected", True)
                expired = event.get("expired", False)
                if type(connected) is not bool or type(expired) is not bool:
                    raise ValueError("connected and expired must be JSON booleans")
                result = plc.observe(request, connected=connected, expired=expired)
        elif op == "scan":
            result = plc.scan()
        elif op == "restart":
            result = plc.restart()
        else:
            raise ValueError(f"unknown event: {op!r}")
        yield n, op, result, plc.epoch, plc.recipe, plc.apply_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    args = parser.parse_args()
    try:
        events = json.loads(args.scenario.read_text(encoding="utf-8"))
        if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
            raise ValueError("scenario must be a JSON array of event objects")
        rows = list(trace(events))
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    print("step event    result             epoch recipe applies")
    for n, op, result, epoch, recipe, count in rows:
        print(f"{n:>4} {op:<8} {result:<18} {epoch:>5} {recipe:<6} {count:>7}")


if __name__ == "__main__":
    main()
