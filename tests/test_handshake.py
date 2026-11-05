import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from handshake import Controller, Request


class HandshakeTests(unittest.TestCase):
    def setUp(self):
        self.plc = Controller()
        self.cmd = Request(1, 1, "large")

    def latch(self, request):
        self.assertEqual(self.plc.write(request), "buffered")
        return self.plc.scan()

    def test_transport_write_and_receipt_do_not_apply(self):
        self.plc.write(self.cmd)
        self.assertEqual(self.plc.observe(self.cmd), "waiting")
        self.assertEqual(self.plc.scan(), "accepted")
        self.assertEqual((self.plc.recipe, self.plc.apply_count), ("small", 0))
        self.assertEqual(self.plc.observe(self.cmd), "accepted")
        self.assertEqual(self.plc.scan(), "applied")
        self.assertEqual((self.plc.recipe, self.plc.apply_count), ("large", 1))
        self.assertEqual(self.plc.observe(self.cmd), "applied")

    def test_expiry_never_implies_failure_or_success(self):
        self.latch(self.cmd)
        self.assertEqual(self.plc.observe(self.cmd, expired=True), "unknown")
        self.plc.scan()
        self.assertEqual(self.plc.observe(self.cmd, connected=False, expired=True), "unknown")
        self.assertEqual(self.plc.observe(self.cmd, expired=True), "applied")

    def test_duplicate_pending_or_finished_applies_once(self):
        self.latch(self.cmd)
        self.plc.write(self.cmd)
        self.assertEqual(self.plc.scan(), "applied")
        self.assertEqual(self.plc.scan(), "duplicate")
        self.assertEqual(self.latch(self.cmd), "duplicate")
        self.assertEqual(self.plc.apply_count, 1)

    def test_conflicting_retry_does_not_replace_receipt(self):
        self.latch(self.cmd)
        self.plc.scan()
        other = Request(1, 1, "small")
        self.assertEqual(self.latch(other), "sequence_conflict")
        self.assertEqual(self.plc.observe(other, expired=True), "unknown")
        self.assertEqual(self.plc.observe(self.cmd), "applied")
        self.assertEqual(self.plc.recipe, "large")

    def test_rejected_recipe_never_changes_state(self):
        bad = Request(1, 1, "turbo")
        self.assertEqual(self.latch(bad), "accepted")
        self.assertEqual(self.plc.scan(), "rejected")
        self.assertEqual(self.plc.observe(bad), "rejected")
        self.assertEqual(self.latch(bad), "duplicate")
        self.assertEqual((self.plc.recipe, self.plc.apply_count), ("small", 0))

    def test_restart_does_not_replay_or_erase_applied_value(self):
        self.latch(self.cmd)
        self.plc.scan()
        self.plc.restart()
        self.assertEqual(self.latch(self.cmd), "wrong_epoch")
        self.assertEqual(self.plc.observe(self.cmd), "reconcile")
        self.assertEqual((self.plc.recipe, self.plc.apply_count), ("large", 1))
        new = Request(2, 1, "small")
        self.assertEqual(self.latch(new), "accepted")
        self.assertEqual(self.plc.scan(), "applied")

    def test_restart_before_completion_discards_pending(self):
        self.latch(self.cmd)
        self.plc.restart()
        self.assertEqual(self.plc.scan(), "idle")
        self.assertEqual(self.plc.observe(self.cmd), "reconcile")
        self.assertEqual((self.plc.recipe, self.plc.apply_count), ("small", 0))

    def test_mailbox_rejects_second_distinct_unconsumed_write(self):
        self.plc.write(self.cmd)
        with self.assertRaisesRegex(ValueError, "mailbox occupied"):
            self.plc.write(Request(1, 2, "small"))
        self.assertEqual(self.plc.scan(), "accepted")
        self.assertEqual(self.plc.scan(), "applied")
        self.assertEqual(self.plc.recipe, "large")

    def test_seeded_trace_against_set_oracle(self):
        rng = random.Random(413)
        applied = set()
        last = "small"
        for seq in range(1, 201):
            recipe = rng.choice(["large", "small", "invalid"])
            cmd = Request(1, seq, recipe)
            self.assertEqual(self.latch(cmd), "accepted")
            self.plc.scan()
            if recipe != "invalid":
                applied.add(seq)
                last = recipe
            for _ in range(rng.randrange(1, 7)):
                replay = rng.randint(1, seq)
                packet = cmd if replay == seq else Request(1, replay, "large")
                self.assertEqual(self.latch(packet), "duplicate" if replay == seq else "old_sequence")
                self.assertEqual((self.plc.apply_count, self.plc.recipe), (len(applied), last))

    def test_cli_rejects_invalid_sequence_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps([dict(op="write", epoch=1, seq=True, recipe="large")]))
            got = subprocess.run([sys.executable, "handshake.py", str(path)], capture_output=True, text=True)
            self.assertEqual(got.returncode, 2)
            self.assertIn("seq must be a positive integer", got.stderr)
            self.assertEqual(got.stdout, "")


if __name__ == "__main__":
    unittest.main()
