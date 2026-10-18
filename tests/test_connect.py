"""Going live: credentials entry, saving (mode 600), the global sandbox/live switch, and the BRAIN login flow
(run against a fake HTTP session, since tests must not touch the real API)."""
import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

os.environ.setdefault("HYPOLAB_HOME", tempfile.mkdtemp(prefix="hypolab_test_"))

from hypolab import brain as brainmod, config, connect  # noqa: E402
from hypolab.__main__ import main as cli  # noqa: E402
from hypolab.brain import AuthError, BrainClient  # noqa: E402


class FakeResponse:
    def __init__(self, status, body=None, headers=None, url="https://api.worldquantbrain.com/authentication"):
        self.status_code, self._body, self.headers, self.url = status, body or {}, headers or {}, url
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeSession:
    """Mimics BRAIN: POST /authentication -> 201 for the right password, 401 otherwise; GET -> session info."""

    def __init__(self, good=("me@x.com", "right")):
        self.good, self.cookies, self.logged_in = good, mock.MagicMock(), False
        self.cookies.get_dict.return_value = {"t": "cookie"}

    def post(self, url, auth=None, timeout=None):
        if tuple(auth) == self.good:
            self.logged_in = True
            return FakeResponse(201, {"user": {"id": "ZZ1234"}})
        return FakeResponse(401, {"detail": "Invalid credentials."})

    def get(self, url, timeout=None):
        if self.logged_in:
            return FakeResponse(200, {"user": {"id": "ZZ1234"}, "token": {"expiry": 14400}})
        return FakeResponse(401)


def fake_client_factory(session):
    real_init = BrainClient.__init__

    def init(self, *a, **kw):
        real_init(self, *a, **kw)
        self.s = session
    return init


class TestConnect(unittest.TestCase):
    def setUp(self):
        for p in (brainmod._cred_path(), brainmod._session_path()):
            if p.exists():
                p.unlink()
        config.save_settings(mode="sandbox", live_region="USA")

    def tearDown(self):
        config.save_settings(mode="sandbox", live_region="USA")

    def test_brain_login_accepts_201(self):
        with mock.patch.object(BrainClient, "__init__", fake_client_factory(FakeSession())), redirect_stdout(io.StringIO()):
            b = BrainClient(credentials=("me@x.com", "right"))
            b.login(force=True)
        self.assertEqual(b.user_id, "ZZ1234")
        self.assertGreater(b.seconds_left(), 3600)

    def test_login_saves_private_credentials(self):
        with mock.patch.object(BrainClient, "__init__", fake_client_factory(FakeSession())), \
                mock.patch("builtins.input", return_value="me@x.com"), \
                mock.patch("getpass.getpass", return_value="right"), redirect_stdout(io.StringIO()):
            connect.login()
        p = brainmod._cred_path()
        self.assertTrue(p.exists())
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(json.loads(p.read_text())["email"], "me@x.com")

    def test_wrong_password_saves_nothing(self):
        with mock.patch.object(BrainClient, "__init__", fake_client_factory(FakeSession())), \
                mock.patch("builtins.input", return_value="me@x.com"), \
                mock.patch("getpass.getpass", return_value="wrong"), redirect_stdout(io.StringIO()):
            with self.assertRaises(AuthError):
                connect.login()
        self.assertFalse(brainmod._cred_path().exists())

    def test_global_switch(self):
        self.assertTrue(config.sandbox_mode())
        with redirect_stdout(io.StringIO()):
            connect.go_live("glb")
        self.assertFalse(config.sandbox_mode())
        self.assertEqual(config.live_region(), "GLB")
        with redirect_stdout(io.StringIO()):
            connect.go_sandbox()
        self.assertTrue(config.sandbox_mode())

    def test_researcher_start_follows_switch(self):
        from hypolab.research import Researcher
        with redirect_stdout(io.StringIO()):
            connect.go_live("EUR")
            with mock.patch.object(Researcher, "live", return_value="LIVE") as live:
                self.assertEqual(Researcher.start(), "LIVE")
                live.assert_called_once()

    def test_cli_status_and_logout(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli(["status"]), 0)
            self.assertEqual(cli(["logout"]), 0)
        self.assertIn("mode", out.getvalue())


class FakeBrainServer:
    """Local HTTP server that behaves like BRAIN's login: password -> 401 persona; persona POST -> 201 + cookie;
    every other call needs exactly the newest cookie (a stale duplicate cookie is rejected, as on BRAIN)."""

    def __init__(self):
        import http.server
        import threading
        srv = self
        self.persona_posts = 0
        self.token = "NEW1"

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=None, headers=None):
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                data = json.dumps(body or {}).encode()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authed(self):
                return self.headers.get("Cookie", "").split(";")[0].strip() == f"t={srv.token}"

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n:
                    self.rfile.read(n)
                if self.path.startswith("/authentication/persona"):
                    srv.persona_posts += 1
                    return self._send(201, {}, {"Set-Cookie": f"t={srv.token}; Path=/; HttpOnly"})
                return self._send(401, {}, {"WWW-Authenticate": "persona",
                                            "Location": "/authentication/persona?inquiry=inq_test"})

            def do_GET(self):
                if not self._authed():
                    return self._send(401, {"detail": "Incorrect authentication credentials."})
                if self.path.startswith("/authentication"):
                    return self._send(200, {"user": {"id": "ZZ1234"}, "token": {"expiry": 14400.0}})
                return self._send(200, {"ok": True})

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


class TestRealLoginFlow(unittest.TestCase):
    """Regression for: login + face scan succeeded, then the next step asked for the face scan again."""

    def setUp(self):
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
        self.srv = FakeBrainServer()
        self._defaults = BrainClient.__init__.__defaults__
        BrainClient.__init__.__defaults__ = (self.srv.url,) + self._defaults[1:]
        connect._CLIENT = None
        for p in (brainmod._cred_path(), brainmod._session_path()):
            if p.exists():
                p.unlink()
        # the situation on the user's laptop: an EXPIRED session file from an earlier run, old format
        brainmod._write_private(brainmod._session_path(), {"cookies": {"t": "OLD"}, "expiry_ts": 0, "user_id": "ZZ1234"})

    def tearDown(self):
        BrainClient.__init__.__defaults__ = self._defaults
        connect._CLIENT = None
        self.srv.close()

    def test_one_face_scan_for_the_whole_session(self):
        with mock.patch("builtins.input", return_value="me@x.com"), \
                mock.patch("getpass.getpass", return_value="right"), redirect_stdout(io.StringIO()) as out:
            b = connect.login()                                   # step 2 (with face scan)
            self.assertGreater(b.seconds_left(), 3600, out.getvalue())
            b2 = connect.client()                                 # step 4: must reuse, not log in again
            self.assertIs(b, b2)
            self.assertEqual(b2._get_json("/simulations"), {"ok": True})
        self.assertEqual(self.srv.persona_posts, 1, out.getvalue())

    def test_new_python_session_reuses_saved_session(self):
        with mock.patch("builtins.input", return_value="me@x.com"), \
                mock.patch("getpass.getpass", return_value="right"), redirect_stdout(io.StringIO()):
            connect.login()
        connect._CLIENT = None                                    # like restarting the kernel
        with mock.patch("builtins.input", side_effect=AssertionError("asked for input again")), \
                redirect_stdout(io.StringIO()):
            b = connect.client()
            self.assertEqual(b._get_json("/data-sets"), {"ok": True})
        self.assertEqual(self.srv.persona_posts, 1)


class TestWebLogin(TestRealLoginFlow):
    """The cockpit's login: no input(), the face-scan link is shown and a button finishes it."""

    def test_two_step_login_with_face_scan(self):
        res = connect.begin_login("me@x.com", "right")
        self.assertEqual(res["status"], "biometric")
        self.assertIn("/authentication/persona", res["url"])
        self.assertFalse(brainmod._cred_path().exists())          # nothing saved before BRAIN accepts
        done = connect.finish_login()
        self.assertEqual(done["status"], "ok")
        self.assertTrue(brainmod._cred_path().exists())
        self.assertEqual(stat.S_IMODE(os.stat(brainmod._cred_path()).st_mode), 0o600)
        self.assertGreater(connect.client(login_now=False).seconds_left(), 3600)
        self.assertEqual(self.srv.persona_posts, 1)

    def test_finish_without_begin(self):
        connect._PENDING = None
        self.assertEqual(connect.finish_login()["status"], "none")


class TestAppsRenewExpiredSession(TestRealLoginFlow):
    """Seen live on 2026-10-10: each app page started its own face-scan request and printed the link to the
    terminal. Now one request is kept, shown on the Setup tab, and reused by every page."""

    def test_one_face_scan_request_shown_on_setup(self):
        from ideaengine.connection import open_researcher
        brainmod._write_private(brainmod._cred_path(), {"email": "me@x.com", "password": "right"})
        config.save_settings(mode="live", live_region="USA")
        connect._PENDING = None
        try:
            with redirect_stdout(io.StringIO()) as out:
                R, problem = open_researcher()
                R2, problem2 = open_researcher()            # a second app page
            self.assertIsNone(R)
            self.assertIn("face scan", problem)
            self.assertNotIn("http", out.getvalue())          # no links dumped into the terminal
            first = connect.pending()["url"]
            self.assertEqual(connect.pending()["url"], first)  # the same request, not a new one
            self.assertEqual(connect.finish_login()["status"], "ok")
            self.assertIsNone(connect.pending())
            self.assertEqual(self.srv.persona_posts, 1)
            R3, problem3 = open_researcher()
            self.assertIsNotNone(R3, problem3)
        finally:
            config.save_settings(mode="sandbox")
            connect._PENDING = None


if __name__ == "__main__":
    unittest.main()
