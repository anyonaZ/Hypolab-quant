"""A careful client for the WorldQuant BRAIN API.

Written from the official "BRAIN API" documentation in your zip, fixing the
problems found in the zip's ``ace_lib.py`` versions:

* login success is HTTP **201** (the Modular ``start_session`` treated anything
  but 200 as "wrong password", deleted your credentials and recursed);
* biometrics (persona) flow handled once, cleanly, with a clear prompt;
* the session cookie is cached as JSON with 0600 permissions - not a pickle
  (unpickling files is a code-execution risk) - and refreshed before expiry;
* ``/data-fields`` and ``/data-sets`` are fully paginated (the Gold
  ``get_datafields`` fetched only the first page without a search term);
* 429 / Retry-After / 5xx are retried with back-off; one bad expression does
  not silently cancel a batch because every payload is linted first
  (see ``research.py``);
* nothing is ever submitted unless you call ``submit(alpha_id, confirm=...)``
  yourself with the exact confirmation string;
* alpha descriptions are written from the idea card - not the zip's
  placeholder template ("Idea: Define the core anomaly...") that was stamped on
  every alpha.
"""
from __future__ import annotations

import getpass
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional
from urllib.parse import urljoin

import pandas as pd
import requests

from . import config

API = os.environ.get("BRAIN_API_URL", "https://api.worldquantbrain.com")
PLATFORM = os.environ.get("BRAIN_URL", "https://platform.worldquantbrain.com")


class BrainError(RuntimeError):
    pass


class AuthError(BrainError):
    pass


def _cred_path() -> Path:
    return config.HOME / "credentials.json"


def _session_path() -> Path:
    return config.HOME / "session.json"


def _write_private(path: Path, payload: dict):
    config.ensure_home()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def record_quota(headers) -> Optional[dict]:
    """Save BRAIN's simulation quota from a POST /simulations response (BRAIN_RULES S-3).

    Headers: X-Ratelimit-Limit (daily limit), -Remaining, -Reset (seconds until reset).
    Written to ~/.hypolab/quota.json so every app can show the real remaining count.
    """
    try:
        h = {k.lower(): v for k, v in dict(headers or {}).items()}
        if "x-ratelimit-remaining" not in h:
            return None
        q = {"limit": int(float(h.get("x-ratelimit-limit", 0) or 0)),
             "remaining": int(float(h["x-ratelimit-remaining"])),
             "reset_at": time.time() + float(h.get("x-ratelimit-reset", 0) or 0),
             "seen_at": time.time()}
        config.ensure_home()
        (config.HOME / "quota.json").write_text(json.dumps(q))
        return q
    except (TypeError, ValueError, OSError):
        return None


def quota() -> Optional[dict]:
    """Last known BRAIN quota, or None if never seen / already reset."""
    try:
        q = json.loads((config.HOME / "quota.json").read_text())
    except (OSError, ValueError):
        return None
    if time.time() >= q.get("reset_at", 0):
        return None
    return q


def make_payload(expression: str, region: str = "USA", universe: Optional[str] = None, delay: int = 1,
                 decay: int = 0, neutralization: str = "SUBINDUSTRY", truncation: float = 0.08,
                 pasteurization: str = "ON", nan_handling: str = "OFF", unit_handling: str = "VERIFY",
                 max_trade: Optional[str] = None, test_period: str = "P2Y", visualization: bool = False,
                 instrument_type: str = "EQUITY") -> dict:
    """A REGULAR simulation request (see the API PDF: POST /simulations).

    test_period="P2Y" keeps the last two years of the in-sample window aside as a
    'test' slice. Choose between variants using the TRAIN numbers only, then look at
    the test slice once at the end (WorldQuant's own anti-overfitting advice).
    """
    reg = config.REGION_DEFAULTS.get(region, {})
    universe = universe or reg.get("universe") or (None if region in config.REGION_DEFAULTS else "TOP3000")
    if not universe:
        raise ValueError(f"HYPOLAB does not know {region}'s universes yet: press 'Download operators + "
                         f"simulation options' on the cockpit's Account tab (live mode), then try again.")
    return {
        "type": "REGULAR",
        "settings": {
            "instrumentType": instrument_type, "region": region,
            "universe": universe, "delay": int(delay), "decay": int(decay),
            "neutralization": neutralization, "truncation": float(truncation), "pasteurization": pasteurization,
            "unitHandling": unit_handling, "nanHandling": nan_handling,
            "maxTrade": max_trade or reg.get("max_trade", "OFF"), "language": "FASTEXPR",
            "visualization": bool(visualization), "testPeriod": test_period,
        },
        "regular": expression,
    }


class BrainClient:
    """Usage::

        brain = BrainClient()      # reads ~/.hypolab/credentials.json or BRAIN_EMAIL/BRAIN_PASSWORD
        brain.login()              # prints a link if biometrics are required
        brain.whoami()
    """

    def __init__(self, base_url: str = API, timeout: float = 60.0, verbose: bool = True,
                 input_fn: Optional[Callable[[str], str]] = None, credentials: Optional[tuple] = None):
        self._given_credentials = credentials
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.verbose = verbose
        self.input = input_fn or (lambda prompt: input(prompt))   # looked up at call time
        self.s = requests.Session()
        self.expiry_ts = 0.0
        self.user_id: Optional[str] = None
        self._load_session()

    # ------------------------------------------------------------ auth
    def _log(self, msg: str):
        if self.verbose:
            print(msg)

    def _credentials(self) -> tuple:
        if self._given_credentials:
            return self._given_credentials
        email, pw = os.environ.get("BRAIN_EMAIL"), os.environ.get("BRAIN_PASSWORD")
        if email and pw:
            return email, pw
        p = _cred_path()
        if p.exists():
            d = json.loads(p.read_text())
            return d["email"], d["password"]
        print("No saved BRAIN credentials. (Tip: log in on the cockpit's Setup tab or with `python -m hypolab login` "
              "once, and you will not be asked again.)")
        email = self.input("BRAIN email: ").strip()
        pw = getpass.getpass("BRAIN password: ")
        return email, pw

    def _load_session(self):
        """Reuse a saved session only if it has not expired; cookies are restored WITH their domain/path.

        (Bug fixed here: restoring a cookie without its domain left a stale 't' cookie next to the fresh one
        BRAIN sets at login; the request then carried 't=OLD; t=NEW', BRAIN read the old one, answered 401,
        and every call asked for biometrics again.)"""
        p = _session_path()
        if not p.exists():
            return
        try:
            d = json.loads(p.read_text())
            expiry = float(d.get("expiry_ts", 0))
            if expiry - time.time() < 60:
                return                       # expired: start clean, never mix old cookies with a new login
            for c in d.get("cookies", []) if isinstance(d.get("cookies"), list) else []:
                self.s.cookies.set(c["name"], c["value"], domain=c.get("domain", ""), path=c.get("path", "/"))
            self.expiry_ts = expiry
            self.user_id = d.get("user_id")
        except (json.JSONDecodeError, OSError, ValueError, KeyError, TypeError):
            pass

    def _save_session(self):
        cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path} for c in self.s.cookies]
        _write_private(_session_path(), {"cookies": cookies, "expiry_ts": self.expiry_ts, "user_id": self.user_id})

    def seconds_left(self) -> float:
        return max(0.0, self.expiry_ts - time.time())

    def whoami(self) -> dict:
        r = self.s.get(self.base + "/authentication", timeout=self.timeout)
        self._last_whoami_status = r.status_code
        if r.status_code == 200:
            try:
                d = r.json()
            except ValueError:
                d = {}
            expiry = (d.get("token") or {}).get("expiry")
            # BRAIN sessions last 4 h; if the field is missing, assume that rather than "0 h"
            self.expiry_ts = time.time() + (float(expiry) if expiry else 4 * 3600.0)
            self.user_id = d.get("user", {}).get("id", self.user_id)
            self._save_session()
            return d
        return {}

    # Login in two steps, so a web page (the marimo cockpit) can show the face-scan link and a "done" button
    # instead of waiting on input(). login() below chains them for terminals.
    def begin_login(self) -> dict:
        """POST the credentials. Returns {"status": "ok"} or {"status": "biometric", "url": <face-scan link>}."""
        email, pw = self._credentials()
        self.s.cookies.clear()               # a fresh login starts with an empty cookie jar
        self.expiry_ts = 0.0
        r = self.s.post(self.base + "/authentication", auth=(email, pw), timeout=self.timeout)
        if r.status_code == 401 and r.headers.get("WWW-Authenticate") == "persona":
            return {"status": "biometric", "url": urljoin(r.url, r.headers["Location"])}
        if r.status_code == 401:
            detail = ""
            try:
                detail = r.json().get("detail", "")
            except ValueError:
                pass
            raise AuthError(f"login refused ({detail or 'invalid credentials'}). Your saved credentials were NOT "
                            "deleted; fix ~/.hypolab/credentials.json or the BRAIN_EMAIL/BRAIN_PASSWORD variables.")
        if r.status_code not in (200, 201):
            raise AuthError(f"unexpected login response {r.status_code}: {r.text[:200]}")
        return self._login_done()

    def finish_biometric(self, url: str) -> dict:
        """After the face scan: {"status": "ok"}, or {"status": "waiting"} if BRAIN has not registered it yet."""
        rr = self.s.post(url, timeout=self.timeout)
        if rr.status_code != 201:
            return {"status": "waiting"}
        return self._login_done()

    def _login_done(self) -> dict:
        info = self.whoami()
        if not info:
            raise AuthError(f"BRAIN accepted the login but the session check failed "
                            f"(GET /authentication -> {getattr(self, '_last_whoami_status', '?')}). "
                            "Run connect.logout(forget_credentials=False) and try again.")
        self._last_login = time.time()
        self._log(f"Logged in. Session valid for {self.seconds_left() / 3600:.1f} h")
        return {"status": "ok", "info": info}

    def login(self, force: bool = False) -> dict:
        if not force and self.seconds_left() > 600 and self.whoami():
            self._log(f"BRAIN session active - {self.seconds_left() / 3600:.1f} h left")
            return {"user": {"id": self.user_id}}
        res = self.begin_login()
        if res["status"] == "biometric":
            url = res["url"]
            print("\nBiometric check required. Open this link, complete the scan, then come back:\n" + url)
            for attempt in range(5):
                self.input("Press ENTER after completing the scan... ")
                res = self.finish_biometric(url)
                if res["status"] == "ok":
                    break
                print("BRAIN has not registered the scan yet. Wait until the page says it is done, then press ENTER.")
            else:
                raise AuthError("biometric authentication was not completed")
        return res["info"]

    def ensure(self):
        if self.seconds_left() < 300:
            self.login()

    # --------------------------------------------------------- transport
    def _req(self, method: str, path: str, retries: int = 6, **kw) -> requests.Response:
        url = path if path.startswith("http") else self.base + path
        kw.setdefault("timeout", self.timeout)
        relogged = False
        for attempt in range(retries):
            try:
                r = self.s.request(method, url, **kw)
            except (requests.ConnectionError, requests.Timeout) as e:
                wait = min(60, 2 ** attempt)
                self._log(f"network problem ({type(e).__name__}); retrying in {wait}s")
                time.sleep(wait)
                continue
            if r.status_code == 401 and not relogged:
                relogged = True
                if time.time() - getattr(self, "_last_login", 0) < 120:
                    raise AuthError(f"{method} {path}: BRAIN rejected a session that was created moments ago "
                                    f"(401: {r.text[:200]}). Not asking for biometrics again in a loop.")
                self.login(force=True)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                wait = float(r.headers.get("Retry-After", min(60, 2 ** attempt)) or 5)
                self._log(f"BRAIN busy ({r.status_code}); waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            return r
        raise BrainError(f"{method} {path} failed after {retries} attempts")

    def _get_json(self, path: str, **kw):
        r = self._req("GET", path, **kw)
        if r.status_code >= 400:
            raise BrainError(f"GET {path}: {r.status_code} {r.text[:300]}")
        try:
            return r.json()
        except ValueError:
            # under load BRAIN can answer with an HTML page and status 200 (seen in WQ's own notebook)
            time.sleep(5)
            return self._req("GET", path, **kw).json()

    def _poll(self, path: str, max_wait: float = 3600) -> requests.Response:
        """GET until no Retry-After header (BRAIN's async pattern)."""
        start = time.time()
        while True:
            r = self._req("GET", path)
            ra = r.headers.get("Retry-After")
            if not ra or float(ra) == 0:
                return r
            if time.time() - start > max_wait:
                raise BrainError(f"timed out waiting for {path}")
            time.sleep(float(ra))

    def _paged(self, path: str, params: dict, page: int = 50, max_items: int = 100000) -> List[dict]:
        out, offset, total = [], 0, None
        while total is None or offset < total:
            p = dict(params, limit=page, offset=offset)
            d = self._get_json(path, params=p)
            rows = d.get("results", [])
            total = int(d.get("count", len(rows)))
            out.extend(rows)
            if not rows or len(out) >= max_items:
                break
            offset += len(rows)
        return out

    # ---------------------------------------------------------- metadata
    def sync_simulation_options(self) -> pd.DataFrame:
        """Download the region/universe/delay/neutralization options of THIS account and cache them."""
        df = self.simulation_options()
        if not df.empty:
            config.save_sim_options(df.to_dict("records"))
        return df

    def simulation_options(self) -> pd.DataFrame:
        """Valid region/universe/delay/neutralization combinations for YOUR account."""
        d = self._req("OPTIONS", "/simulations").json()
        ch = d["actions"]["POST"]["settings"]["children"]
        by_label = {v.get("label"): v for v in ch.values() if isinstance(v, dict)}
        regions = by_label["Region"]["choices"]["instrumentType"]["EQUITY"]
        rows = []
        for reg in regions:
            r = reg["value"]
            try:
                delays = [x["value"] for x in by_label["Delay"]["choices"]["instrumentType"]["EQUITY"]["region"][r]]
                univs = [x["value"] for x in by_label["Universe"]["choices"]["instrumentType"]["EQUITY"]["region"][r]]
                neuts = [x["value"] for x in by_label["Neutralization"]["choices"]["instrumentType"]["EQUITY"]["region"][r]]
            except (KeyError, TypeError):
                continue
            rows.append({"region": r, "delays": delays, "universes": univs, "neutralizations": neuts})
        return pd.DataFrame(rows)

    def datasets(self, region: str, universe: str, delay: int = 1, instrument_type: str = "EQUITY") -> List[dict]:
        return self._paged("/data-sets", {"instrumentType": instrument_type, "region": region, "delay": delay,
                                          "universe": universe})

    def datafields(self, region: str, universe: str, delay: int = 1, dataset_id: Optional[str] = None,
                   search: Optional[str] = None, instrument_type: str = "EQUITY") -> List[dict]:
        p = {"instrumentType": instrument_type, "region": region, "delay": delay, "universe": universe}
        if dataset_id:
            p["dataset.id"] = dataset_id
        if search:
            p["search"] = search
        return self._paged("/data-fields", p)

    def operators(self) -> List[dict]:
        return self._get_json("/operators")

    # ---------------------------------------------------------- simulate
    def _run_batch(self, payloads: List[dict], on_submitted: Optional[Callable[[List[dict], str], None]] = None
                   ) -> List[dict]:
        self.ensure()
        body = payloads[0] if len(payloads) == 1 else payloads
        r = self._req("POST", "/simulations", json=body)
        record_quota(r.headers)
        if r.status_code // 100 != 2:
            msg = r.text[:500]
            return [{"ok": False, "alpha_id": None, "status": "REJECTED", "error": msg, "payload": p} for p in payloads]
        loc = r.headers["Location"]
        if on_submitted:
            # BRAIN has accepted (and counted) the simulation: remember where its result will be, so a shutdown
            # while polling does not cost a second simulation (HYPOLAB 1.4.1 resume).
            try:
                on_submitted(payloads, loc)
            except Exception:  # noqa: BLE001 - bookkeeping must never break a simulation
                pass
        return self.collect(loc, payloads)

    def peek(self, loc: str, payloads: List[dict]) -> Optional[List[dict]]:
        """One look at an accepted simulation: its result(s) if finished, None while BRAIN is still running it."""
        r = self._req("GET", loc)
        if r.status_code == 404:
            return [{"ok": False, "alpha_id": None, "status": "GONE", "error": "BRAIN no longer has this simulation",
                     "payload": p} for p in payloads]
        ra = r.headers.get("Retry-After")
        if ra and float(ra) > 0:
            return None
        return self.collect(loc, payloads, max_wait=60)

    def collect(self, loc: str, payloads: List[dict], max_wait: float = 3600) -> List[dict]:
        """Poll a simulation BRAIN already accepted (its Location URL) until it finishes, and read the result(s)."""
        done = self._poll(loc, max_wait=max_wait).json()
        if len(payloads) == 1:
            ok = done.get("status") in ("COMPLETE", "WARNING") and done.get("alpha")
            return [{"ok": bool(ok), "alpha_id": done.get("alpha"), "status": done.get("status"),
                     "error": done.get("message", ""), "payload": payloads[0]}]
        out = []
        children = done.get("children", [])
        if not children:
            return [{"ok": False, "alpha_id": None, "status": done.get("status", "ERROR"),
                     "error": done.get("message", "multi-simulation failed"), "payload": p} for p in payloads]
        for i, child in enumerate(children):
            c = self._get_json(f"/simulations/{child}")
            p = payloads[i] if i < len(payloads) else {}
            ok = c.get("status") in ("COMPLETE", "WARNING") and c.get("alpha")
            out.append({"ok": bool(ok), "alpha_id": c.get("alpha"), "status": c.get("status"),
                        "error": c.get("message", ""), "payload": p})
        return out

    def simulate(self, payloads: List[dict], batch_size: Optional[int] = None,
                 concurrency: Optional[int] = None, progress: Callable[[str], None] = print,
                 on_submitted: Optional[Callable[[List[dict], str], None]] = None) -> List[dict]:
        """Simulate payloads (already linted!). Returns one dict per payload with
        ok / alpha_id / status / error. Multi-simulation needs identical region+delay."""
        st = config.settings()
        batch_size = max(1, min(10, batch_size or st["multi_sim_batch"]))
        concurrency = max(1, min(3, concurrency or st["concurrent_simulations"]))
        groups: Dict[tuple, List[dict]] = {}
        for p in payloads:
            key = (p["settings"]["region"], p["settings"]["delay"], p["settings"]["universe"])
            groups.setdefault(key, []).append(p)
        batches = []
        for g in groups.values():
            batches += [g[i:i + batch_size] for i in range(0, len(g), batch_size)]
        results: List[dict] = []
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            for i, res in enumerate(ex.map(lambda b: self._run_batch(b, on_submitted), batches), 1):
                results.extend(res)
                if progress:
                    progress(f"batch {i}/{len(batches)} done: {sum(r['ok'] for r in res)}/{len(res)} ok")
        return results

    # ------------------------------------------------------------ results
    def alpha(self, alpha_id: str) -> dict:
        return self._poll(f"/alphas/{alpha_id}").json()

    def checks(self, alpha_id: str) -> pd.DataFrame:
        """The authoritative submission checks (includes correlation checks; can be slow)."""
        d = self._poll(f"/alphas/{alpha_id}/check").json()
        return pd.DataFrame(d.get("is", {}).get("checks", []))

    def recordset(self, alpha_id: str, name: str = "pnl") -> pd.DataFrame:
        d = self._poll(f"/alphas/{alpha_id}/recordsets/{name}").json()
        if not d.get("records"):
            return pd.DataFrame()
        cols = [p["name"] for p in d["schema"]["properties"]]
        df = pd.DataFrame(d["records"], columns=cols)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        return df

    def pnl(self, alpha_id: str) -> pd.Series:
        df = self.recordset(alpha_id, "pnl")
        return df["pnl"] if "pnl" in df.columns else pd.Series(dtype=float)

    def yearly_stats(self, alpha_id: str) -> pd.DataFrame:
        return self.recordset(alpha_id, "yearly-stats")

    def correlations(self, alpha_id: str, kind: str = "self") -> dict:
        """kind: 'self' (vs your alphas) or 'prod' (vs the production pool)."""
        d = self._poll(f"/alphas/{alpha_id}/correlations/{kind}").json()
        recs = d.get("records") or []
        cols = [p["name"] for p in d.get("schema", {}).get("properties", [])]
        return {"max": d.get("max"), "min": d.get("min"), "table": pd.DataFrame(recs, columns=cols or None)}

    def set_properties(self, alpha_id: str, name: Optional[str] = None, tags: Optional[List[str]] = None,
                       color: Optional[str] = None, description: Optional[str] = None,
                       category: Optional[str] = None) -> int:
        body = {}
        if name is not None:
            body["name"] = name
        if tags is not None:
            body["tags"] = tags
        if color is not None:
            body["color"] = color
        if category is not None:
            body["category"] = category
        if description is not None:
            body["regular"] = {"description": description}
        r = self._req("PATCH", f"/alphas/{alpha_id}", json=body)
        return r.status_code

    def submit(self, alpha_id: str, confirm: str = "") -> dict:
        """Submit ONE alpha. You must pass confirm=f"SUBMIT {alpha_id}". Submissions are permanent."""
        if confirm != f"SUBMIT {alpha_id}":
            raise BrainError(f'Refusing to submit. Re-run with confirm="SUBMIT {alpha_id}" after reading the '
                             "submission gate report.")
        r = self._req("POST", f"/alphas/{alpha_id}/submit")
        while r.headers.get("Retry-After"):
            time.sleep(float(r.headers["Retry-After"]))
            r = self._req("GET", f"/alphas/{alpha_id}/submit")
        return {"status_code": r.status_code, "body": r.text[:500]}

    # ---------------------------------------------------------- account
    def my_alphas(self, status: Optional[str] = None, region: Optional[str] = None, max_items: int = 2000) -> List[dict]:
        p = {"order": "-dateCreated"}
        if status:
            p["status"] = status
        if region:
            p["settings.region"] = region
        return self._paged("/users/self/alphas", p, page=100, max_items=max_items)

    def submitted_alphas(self, since: Optional[str] = None, until: Optional[str] = None,
                         max_items: int = 20000) -> List[dict]:
        """Every alpha you have SUBMITTED (regular and super), newest first, with code and settings.

        since / until: ISO datetimes (e.g. "2026-10-01T00:00:00-04:00"); BRAIN filters on dateSubmitted.
        Without `since`, everything ever submitted is returned (unsubmitted simulations are left out)."""
        params = {"order": "-dateSubmitted", "dateSubmitted>": since or "2000-01-01T00:00:00-05:00"}
        if until:
            params["dateSubmitted<"] = until
        rows = self._paged("/users/self/alphas", params, page=100, max_items=max_items)
        return [a for a in rows if a.get("dateSubmitted")]

    def diversity(self) -> pd.DataFrame:
        """Submitted-alpha counts by region / delay / data category (your pyramid map)."""
        uid = self.user_id or "self"
        d = self._get_json(f"/users/{uid}/activities/diversity", params={"grouping": "region,delay,dataCategory"})
        rows = []
        raw = d.get("alphas", []) if isinstance(d, dict) else []
        for a in raw:
            cat = a.get("dataCategory") or {}
            if not isinstance(cat, dict):
                cat = {"id": cat}
            delay = a.get("delay")
            if delay is None and isinstance(a.get("settings"), dict):
                delay = a["settings"].get("delay")
            category = str(cat.get("id") or cat.get("name") or "").lower()
            # BRAIN also sends subtotals: category null = all categories of a region+delay; category and delay
            # null = the whole region. They are totals, not an "Other" cell (seen live on 2026-10-10).
            kind = "cell" if category else ("region_delay_total" if delay is not None else "region_total")
            div = a.get("dataDiversity") or {}
            rows.append({"region": a.get("region"), "delay": delay, "category": category,
                         "alphas": a.get("alphaCount", 0), "kind": kind,
                         "diversity_check": div.get("check") if isinstance(div, dict) else None})
        df = pd.DataFrame(rows, columns=["region", "delay", "category", "alphas", "kind", "diversity_check"])
        df.attrs["raw_sample"] = raw[:20]      # BRAIN's own rows, shown on the cockpit for checking
        return df

    def pyramid_multipliers(self) -> pd.DataFrame:
        try:
            d = self._get_json("/users/self/activities/pyramid-multipliers")
        except BrainError:
            return pd.DataFrame()
        rows = d.get("pyramids") or d.get("results") or d.get("records") or []
        return pd.json_normalize(rows) if rows else pd.json_normalize(d)

    def platform_link(self, alpha_id: str) -> str:
        return f"{PLATFORM}/alpha/{alpha_id}"


def summarize_alpha(alpha_json: dict) -> dict:
    """Flatten the important IS / train / test numbers of GET /alphas/{id}."""
    def block(name):
        b = alpha_json.get(name) or {}
        return {k: b.get(k) for k in ("sharpe", "fitness", "turnover", "returns", "drawdown", "margin",
                                      "longCount", "shortCount") if k in b}
    st = alpha_json.get("settings", {})
    out = {"alpha_id": alpha_json.get("id"), "expression": (alpha_json.get("regular") or {}).get("code"),
           "region": st.get("region"), "universe": st.get("universe"), "delay": st.get("delay"),
           "neutralization": st.get("neutralization"), "decay": st.get("decay"), "truncation": st.get("truncation")}
    for name in ("is", "train", "test"):
        for k, v in block(name).items():
            out[f"{name}_{k}"] = v
    checks = (alpha_json.get("is") or {}).get("checks") or []
    out["checks"] = checks
    out["failed"] = [c.get("name") for c in checks if c.get("result") == "FAIL"]
    out["pending"] = [c.get("name") for c in checks if c.get("result") == "PENDING"]
    return out
