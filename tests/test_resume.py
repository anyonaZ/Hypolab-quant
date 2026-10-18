"""1.4.1: pick up where you left off - interrupted simulations, recent results, the last Lab card and Play roll."""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("HYPOLAB_HOME", tempfile.mkdtemp(prefix="hypolab_test_"))

from hypolab import play  # noqa: E402
from hypolab.brain import BrainClient, make_payload  # noqa: E402
from hypolab.research import Researcher  # noqa: E402

EXPR = "group_rank(ts_backfill(ern_eps_surprise, 63), subindustry)"


class TestPendingLifecycle(unittest.TestCase):
    def test_pending_is_written_before_polling_and_cleared_after(self):
        R = Researcher.sandbox()
        seen = []
        orig = R.journal.add_pending
        R.journal.add_pending = lambda *a, **k: (seen.append(a[0]), orig(*a, **k))
        R.test(expression=EXPR, settings={"region": "SBX"})
        self.assertEqual(len(seen), 1)                 # recorded while BRAIN was working
        self.assertEqual(R.pending(), [])              # and cleared once the result was read

    def _interrupted(self, R, peek):
        """A simulation BRAIN accepted, then the laptop shut down before HYPOLAB read it."""
        p = make_payload(EXPR, region="SBX", universe="SANDBOX")
        done = R.brain.simulate([p], progress=None)[0]          # what BRAIN finished meanwhile
        R.journal.add_pending("https://api.example/simulations/abc", "ERN_PEAD@SBX", "core", "explore", EXPR,
                              p["settings"], p)
        R.brain.peek = lambda loc, payloads: peek(done, payloads)
        return done

    def test_recover_finished_simulation_without_simulating_again(self):
        R = Researcher.sandbox()
        done = self._interrupted(R, lambda d, ps: [dict(d, payload=ps[0])])
        n_alphas = len(R.brain._alphas)
        out = R.recover_pending()
        self.assertEqual(len(out["recovered"]), 1)
        self.assertEqual(len(R.brain._alphas), n_alphas)       # no new simulation
        t = out["recovered"][0]
        self.assertEqual(t.alpha_id, done["alpha_id"])
        self.assertIn("recovered", t.rung)
        self.assertIsNotNone(t.card)                            # the card is rebuilt from the idea id
        self.assertEqual(R.pending(), [])
        self.assertEqual(R.journal.trials("ERN_PEAD@SBX"), 1)  # journaled and counted as a try

    def test_still_running_stays_and_gone_is_dropped(self):
        R = Researcher.sandbox()
        self._interrupted(R, lambda d, ps: None)
        out = R.recover_pending()
        self.assertEqual((len(out["recovered"]), out["running"]), (0, 1))
        self.assertEqual(len(R.pending()), 1)
        R.brain.peek = lambda loc, ps: [{"ok": False, "alpha_id": None, "status": "GONE", "error": "", "payload": ps[0]}]
        self.assertEqual(R.recover_pending()["gone"], 1)
        self.assertEqual(R.pending(), [])


class TestRecentResults(unittest.TestCase):
    def test_rebuilt_from_journal(self):
        R = Researcher.sandbox()
        card = R.card("ERN_PEAD", "SBX")
        first = [R.test(card, rung=i) for i in range(2)]
        play_res = R.play(R.roll(n=1, mode="wild", seed=4))
        back = R.recent_results(10)
        self.assertEqual(len(back), 3)
        self.assertTrue(all(t.cached for t in back))
        self.assertEqual([t.diagnosis.verdict for t in back[:2]], [t.diagnosis.verdict for t in first])
        self.assertEqual(back[0].card.id, card.id)
        self.assertEqual(back[2].key, play_res[0].key)          # play results keep their play: idea


class TestPlayRoll(unittest.TestCase):
    def test_last_roll_round_trip(self):
        R = Researcher.sandbox()
        items = R.roll(n=3, mode="mix", seed=9)
        play.save_roll(items, sandbox=True)
        back = play.load_roll(sandbox=True)
        self.assertEqual([i.expression for i in back], [i.expression for i in items])
        self.assertIsNone(back[0].card)
        self.assertEqual(len(R.play(back)), 3)                   # still playable without the card object


class _FakeSim(BaseHTTPRequestHandler):
    polls = {"n": 0}

    def log_message(self, *a):
        pass

    def _send(self, code, body, headers=None):
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        if self.path.startswith("/simulations"):
            return self._send(201, {}, {"Location": f"http://127.0.0.1:{self.server.server_port}/simulations/s1",
                                        "X-Ratelimit-Remaining": "99", "X-Ratelimit-Limit": "100"})
        self._send(404, {})

    def do_GET(self):
        if self.path.startswith("/simulations/s1"):
            _FakeSim.polls["n"] += 1
            if _FakeSim.polls["n"] < 2:
                return self._send(200, {"progress": 0.5}, {"Retry-After": "0.05"})
            return self._send(200, {"status": "COMPLETE", "alpha": "A1"})
        self._send(404, {})


class TestBrainClientHook(unittest.TestCase):
    def test_on_submitted_fires_before_result_and_peek_sees_running(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeSim)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            c = BrainClient(base_url=f"http://127.0.0.1:{srv.server_port}", verbose=False)
            c.ensure = lambda: None
            p = make_payload("rank(close)", region="USA", universe="TOP3000")
            calls = []
            _FakeSim.polls["n"] = 0
            res = c.simulate([p], progress=None, on_submitted=lambda ps, loc: calls.append((loc, _FakeSim.polls["n"])))
            self.assertEqual(res[0]["alpha_id"], "A1")
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0][0].endswith("/simulations/s1"))
            self.assertEqual(calls[0][1], 0)                     # recorded before the first poll
            _FakeSim.polls["n"] = 0
            self.assertIsNone(c.peek(calls[0][0], [p]))          # still running: no blocking wait
            self.assertEqual(c.peek(calls[0][0], [p])[0]["alpha_id"], "A1")
        finally:
            srv.shutdown()


class TestCockpitCommand(unittest.TestCase):
    def test_session_ttl_is_passed_unless_given(self):
        from unittest import mock
        from hypolab import __main__ as cli
        with mock.patch("subprocess.call", return_value=0) as call:
            cli.main(["cockpit"])
            self.assertIn("--session-ttl", call.call_args[0][0])
            self.assertEqual(call.call_args[0][0][-1], "3600")
            cli.main(["cockpit", "--session-ttl", "60"])
            self.assertEqual(call.call_args[0][0].count("--session-ttl"), 1)


if __name__ == "__main__":
    unittest.main()
