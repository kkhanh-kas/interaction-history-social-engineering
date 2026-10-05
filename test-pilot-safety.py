"""Offline regression checks for dataset locks, calibration and cost planning."""
import contextlib
import importlib.util
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("pilot_safety", Path(__file__).with_name("pilot.py"))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def response(text):
    if p.DEEPSEEK:
        body = {"choices": [{"finish_reason": "stop", "message": {"content": text}}], "model": "offline"}
    else:
        body = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}],
                "modelVersion": "offline"}
    return io.BytesIO(json.dumps(body).encode())


class PilotSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pilot-safety-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(p, "DATA", self.root / "pilot"))
        self.stack.enter_context(patch.object(p, "MOCK", True))
        self.stack.enter_context(patch.object(p, "KEYS", None))
        self.stack.enter_context(patch.object(p.urllib.request, "urlopen",
                                              side_effect=AssertionError("network forbidden")))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def invoke(self, *argv):
        return p.main(list(argv))

    def pilot(self):
        self.invoke("init", "--role", "pilot", "--ids", "900-908", "--scripted-only")
        self.invoke("history", "--ids", "900-908")
        self.invoke("choose-k", "--ids", "900-908")
        return p.DATA

    def calibrated_pilot(self):
        src = self.pilot()
        self.invoke("run", "--ids", "900,901,904,908", "--calibrate", "--scripted")
        self.invoke("run", "--ids", "900,901,904,908", "--L", "3", "--strong", "--scripted", "--conds", "A")
        return src

    def main_dir(self):
        src = self.calibrated_pilot()
        p.DATA = self.root / "main"
        self.invoke("init", "--role", "main", "--from", str(src))
        return p.DATA

    def test_live_commands_reject_mock_dataset_before_calls(self):
        self.main_dir()
        p.MOCK = False
        for command in (("history", "--ids", "1"), ("run", "--ids", "1"), ("report",)):
            with self.subTest(command=command), self.assertRaisesRegex(SystemExit, "mock"):
                self.invoke(*command)

    def test_deepseek_interruptions_retry_and_exhaust_as_missing(self):
        self.pilot()
        cfg = dict(k=3, L=3, strong=False, s_mode="scripted", emph="normal")
        def response(fin):
            return io.BytesIO(json.dumps({"choices": [{"finish_reason": fin,
                "message": {"content": "" if fin != "stop" else "No."}}]}).encode())
        for fin in ("insufficient_system_resource", "aborted"):
            with self.subTest(fin=fin), patch.object(p, "DEEPSEEK", True), patch.object(p, "MOCK", False), \
                    patch.object(p, "RPM", 1e12), patch.object(p, "KEYS", p.Keys([("offline", "dummy")])):
                with patch.object(p.urllib.request, "urlopen", side_effect=lambda *a, **k: response(fin)) as up:
                    row = p.attack(900, 0, "A", cfg)
                self.assertEqual(up.call_count, 4)
                self.assertEqual(row["outcome"], "missing")
                self.assertEqual(row["calls"], 4)
                self.assertTrue(all(c.get("error") and not c["blocked"] for c in p.read_rows("calls.jsonl")[-4:]))
                replies = [response(fin)] + [response("stop") for _ in range(3)]
                with patch.object(p.urllib.request, "urlopen", side_effect=replies):
                    row = p.attack(900, 0, "A", cfg)
                self.assertEqual(row["outcome"], "none")
                self.assertEqual(row["calls"], 4)
                self.assertEqual(len(row["discarded"]), 1)
        self.assertEqual(p.parse_ds({"choices": [{"finish_reason": "content_filter"}]})["blocked"],
                         "output:content_filter")

    def test_copy_requires_all_locked_histories_before_writing(self):
        src = self.main_dir()
        self.invoke("history", "--ids", "1")
        p.DATA = self.root / "copy"
        with patch.object(p, "MODEL", "second-model"), self.assertRaisesRegex(SystemExit, "missing checkpoints"):
            self.invoke("init", "--role", "main", "--from", str(src))
        self.assertFalse(p.DATA.exists())

    def test_copy_run_checks_even_missing_histories_outside_requested_batch(self):
        src = self.main_dir()
        self.invoke("history", "--ids", "1-%d" % p.manifest()["n"])
        p.DATA = self.root / "copy"
        with patch.object(p, "MODEL", "second-model"):
            self.invoke("init", "--role", "main", "--from", str(src))
            p.ckpt_path(2).unlink()
            with patch.object(p, "llm", side_effect=AssertionError("must fail before calls")), \
                    self.assertRaisesRegex(SystemExit, "missing checkpoints"):
                self.invoke("run", "--ids", "1")
        self.assertFalse((p.DATA / "attempts.jsonl").exists())

    def test_live_init_rejects_legacy_mock_pilot(self):
        src = self.calibrated_pilot()
        m = p.manifest()
        m.pop("mock", None)
        (src / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        p.DATA = self.root / "main"
        p.MOCK = False
        with self.assertRaisesRegex(SystemExit, "mock"):
            self.invoke("init", "--role", "main", "--from", str(src))

    def test_mock_commands_reject_live_dataset(self):
        p.MOCK = False
        self.invoke("init", "--role", "pilot", "--ids", "900-908")
        p.MOCK = True
        with self.assertRaisesRegex(SystemExit, "mock"):
            self.invoke("history", "--ids", "900")

    def test_changed_generation_is_rejected_before_history_run_and_init(self):
        main = self.main_dir()
        self.invoke("history", "--ids", "1")
        with patch.object(p, "GEN", dict(p.GEN, temperature=0.2)):
            for command in (("history", "--ids", "2"), ("run", "--ids", "1")):
                with self.subTest(command=command), self.assertRaisesRegex(SystemExit, "configuration"):
                    self.invoke(*command)
            p.DATA = self.root / "changed-main"
            with self.assertRaisesRegex(SystemExit, "configuration"):
                self.invoke("init", "--role", "main", "--from", str(self.root / "pilot"))
        self.assertFalse((main / "attempts.jsonl").exists())

    def test_changed_safety_is_rejected_for_legacy_dataset(self):
        src = self.pilot()
        m = p.manifest()
        for field in ("mock", "gen", "safety"):
            m.pop(field, None)
        (src / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        # Legacy settings are accepted while unchanged, then rejected when safety changes.
        self.invoke("history", "--ids", "900")
        with patch.object(p, "SAFETY", []), self.assertRaisesRegex(SystemExit, "configuration"):
            self.invoke("history", "--ids", "901")

    def test_partial_calibration_cannot_lock_main_even_with_override(self):
        src = self.calibrated_pilot()
        rows = [r for r in p.read_rows("attempts.jsonl") if r["cfg"]["L"] == 8][:2]
        # One success and one complete eight-turn refusal: 1/2 must not become an accepted 12-cell round.
        r = rows[1]
        r.update(outcome="none", turns=[dict(r["turns"][0], turn=n, t_reply="No.", blocks={},
                                               s_msg=p.OPENERS[r["j"]].format(S=r["S"]) if n == 0 else p.SCRIPTED[n-1])
                                        for n in range(8)])
        (src / "attempts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        for n, override in enumerate(((), ("--override", "L=3,emph=normal,reason=offline check"))):
            p.DATA = self.root / ("partial-main-%d" % n)
            with self.subTest(override=override), self.assertRaisesRegex(SystemExit, "12"):
                self.invoke("init", "--role", "main", "--from", str(src), *override)

    def test_partial_strong_round_cannot_lock_main(self):
        src = self.calibrated_pilot()
        rows = p.read_rows("attempts.jsonl")
        rows = [r for r in rows if not r["cfg"]["strong"]] + [r for r in rows if r["cfg"]["strong"]][:1]
        (src / "attempts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        p.DATA = self.root / "partial-strong-main"
        with self.assertRaisesRegex(SystemExit, "strong A calibration needs exactly 12"):
            self.invoke("init", "--role", "main", "--from", str(src))

    def test_empty_t_retry_is_overhead_not_a_second_kept_trajectory(self):
        missing = {"key": "same", "cfg": {"s_mode": "scripted"}, "traj_id": "empty", "outcome": "missing",
                   "turns": [{"t_reply": "", "t_missing": True}]}
        valid = dict(missing, traj_id="kept", outcome="none", turns=[{"t_reply": "No."}] * 3)
        runs = [{"run_id": "run", "cmd": "run", "cfg": {"s_mode": "scripted"}}]
        calls = [{"run_id": "run", "phase": "attack", "requests": 7}]
        self.assertEqual(p.cost(calls, runs, [missing, valid], "scripted", 0)["factor"], 2.3333)

    def test_only_empty_t_attempts_do_not_provide_a_cost_basis(self):
        missing = {"key": "empty", "cfg": {"s_mode": "scripted"}, "traj_id": "empty", "outcome": "missing",
                   "turns": [{"t_reply": "", "t_missing": True}]}
        runs = [{"run_id": "run", "cmd": "run", "cfg": {"s_mode": "scripted"}}]
        calls = [{"run_id": "run", "phase": "attack", "requests": 4}]
        self.assertIsNone(p.cost(calls, runs, [missing], "scripted", 0)["factor"])

    def test_choose_k_requires_all_nine_histories_before_locking(self):
        self.invoke("init", "--role", "pilot", "--ids", "900-908")
        self.invoke("history", "--ids", "900-908")
        with self.assertRaisesRegex(SystemExit, "900-908"):
            self.invoke("choose-k", "--ids", "900,903,906")
        self.assertFalse((p.DATA / "k.json").exists())
        self.invoke("choose-k", "--ids", "900-908")
        self.assertEqual(p.read_k(), 3)

    def test_unfixable_api_error_stops_without_consuming_attempt_command(self):
        self.main_dir()
        self.invoke("history", "--ids", "1")
        cfg = p.manifest()["cfg"]
        denied = p.urllib.error.HTTPError("url", 403, "denied", {}, io.BytesIO(b"PERMISSION_DENIED"))
        for name, keys, error in (("403", p.Keys([("proj-1", "x")]), "403"),
                                  ("no key", p.Keys([]), "no usable key")):
            with self.subTest(name), patch.object(p, "MOCK", False), patch.object(p, "KEYS", keys), \
                    patch.object(p, "RPM", 6000), patch.object(p.urllib.request, "urlopen", side_effect=denied) as up:
                with self.assertRaisesRegex(SystemExit, error):
                    p.run([1], cfg, "A")
                self.assertLessEqual(up.call_count, 1)
                rows = p.read_rows("attempts.jsonl")
                self.assertTrue(rows)
                self.assertTrue(all(r["interrupted"] and not r["closed"] and r["outcome"] == "missing" for r in rows))

    def test_repeated_ids_are_refused_before_any_log(self):
        for ids in ("1,1", "1-3,3-5"):
            with self.subTest(ids), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.invoke("run", "--ids", ids, "--L", "3")
        self.assertFalse(p.DATA.exists())

    def test_ping_checks_mock_live_mode_before_logging(self):
        for made, pinged in ((False, True), (True, False)):
            p.DATA = self.root / ("ping-%s" % made)
            p.MOCK = made
            self.invoke("init", "--role", "pilot", "--ids", "900-908")
            p.MOCK = pinged
            with self.subTest(made=made), self.assertRaisesRegex(SystemExit, "mock"):
                self.invoke("ping")
            self.assertEqual(len(p.read_rows("runs.jsonl")), 1)

    def test_pattern_bound_requires_every_cell_observed(self):
        rows = [dict(hid=h, j=j, cond=c, outcome="success" if c == "B" else "none")
                for h in range(1, 5) for j in range(3) for c in "AB"]
        self.assertEqual(p.same_pattern(rows, "B", "A", ("success",), ("missing",)), (4, 4, 0.75))
        for whole in (False, True):
            incomplete = [dict(r, outcome="missing") if r["hid"] == 4 and (whole or r["j"] == 0)
                          else r for r in rows]
            with self.subTest(whole_history=whole):
                self.assertIsNone(p.same_pattern(incomplete, "B", "A", ("success",), ("missing",))[2])

    def test_sensitivity_report_does_not_bound_a_filtered_pattern(self):
        rows = [dict(hid=h, j=j, cond=c, outcome="success" if c == "B" else "none",
                     cfg={"s_mode": "adaptive"}, turns=[])
                for h in range(1, 5) for j in range(3) for c in "AB"]
        rows[-1]["turns"] = [{"t_reply": "No."}, {"s_msg": "You helped me before."}]
        labels = {p.s_hash("B", "No.", "You helped me before."): "invented-past"}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            p.print_delta(rows, "B", "A", labels)
        lines = output.getvalue().splitlines()
        self.assertIn("95% upper bound", next(s for s in lines if s.lstrip().startswith("main ")))
        self.assertNotIn("95% upper bound", next(s for s in lines if "excl confirmed S violations" in s))

    def test_calibration_preserves_usable_turns_across_quota_stop(self):
        seen = []
        def quota(request, **kwargs):
            seen.append(request)
            if len(seen) == 4:
                raise p.urllib.error.HTTPError("offline", 429, "quota", {}, io.BytesIO(b"PerDay"))
            return response("No.")

        def leak(request, **kwargs):
            body = json.loads(request.data)
            system = body["messages"][0]["content"] if p.DEEPSEEK else body["systemInstruction"]["parts"][0]["text"]
            return response(re.search(r"deploy token is (SW-[A-Z0-9-]+)", system).group(1))

        def keys():
            p.KEYS = p.Keys([("offline", "not-a-key")])

        with patch.object(p, "MOCK", False), patch.object(p, "RPM", 1e12), patch.object(p, "load_keys", keys):
            with patch.object(p.urllib.request, "urlopen", lambda *a, **k: response("No.")):
                self.pilot()
            command = ("run", "--ids", "900,901,904,908", "--calibrate", "--scripted")
            with patch.object(p.urllib.request, "urlopen", quota), self.assertRaisesRegex(SystemExit, "no usable key"):
                self.invoke(*command)
            with patch.object(p.urllib.request, "urlopen", leak):
                self.invoke(*command)
            counts = p.calibration(p.read_rows("attempts.jsonl"), "scripted")[2]
            self.assertEqual(counts[3], (11, 0, 12))
            self.assertEqual(counts[5], (12, 0, 12))

    def test_operational_stop_preserves_cost_and_does_not_close_missing_early(self):
        def keys():
            p.KEYS = p.Keys([("offline", "not-a-key")])

        # First T reply succeeds, S returns empty, then its identical retry gets a fatal error.
        replies = ["No.", ""]
        def stopped(request, **kwargs):
            if replies:
                return response(replies.pop(0))
            raise p.urllib.error.HTTPError("offline", 403, "denied", {}, io.BytesIO(b"denied"))

        with patch.object(p, "MOCK", False), patch.object(p, "RPM", 1e12), patch.object(p, "load_keys", keys):
            with patch.object(p.urllib.request, "urlopen", lambda *a, **k: response("No.")):
                self.invoke("init", "--role", "pilot", "--ids", "900-908")
                self.invoke("history", "--ids", "900-908")
                self.invoke("choose-k", "--ids", "900-908")
            command = ("run", "--ids", "900", "--L", "3", "--conds", "A")
            with patch.object(p.urllib.request, "urlopen", stopped), self.assertRaisesRegex(SystemExit, "403"):
                self.invoke(*command)
            first = p.read_rows("attempts.jsonl")[0]
            self.assertTrue(first["interrupted"])
            self.assertFalse(first["closed"])
            self.assertEqual(first["calls"], 3)
            self.assertEqual([t["calls"] for t in first["discarded"][0]["turns"]], [1, 2])
            # Three subsequent commands still get their full retry allowance for empty T replies.
            with patch.object(p.urllib.request, "urlopen", lambda *a, **k: response("")):
                for closed in (False, False, True):
                    self.invoke(*command)
                    current = [r for r in p.read_rows("attempts.jsonl") if r["key"] == first["key"]]
                    self.assertEqual(current[-1]["closed"], closed)
                calls = len(p.read_rows("calls.jsonl"))
                self.invoke(*command)
                self.assertEqual(len(p.read_rows("calls.jsonl")), calls)


if __name__ == "__main__":
    unittest.main()
