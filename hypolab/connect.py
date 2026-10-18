"""Connect hypolab to your WorldQuant BRAIN account - the one place to do it.

On the cockpit's Setup tab (begin_login / finish_login), or in a terminal (`python -m hypolab login`):

    from hypolab import connect
    connect.status()              # what mode you are in, whether credentials are saved, session time left
    connect.login()               # asks email + password (hidden), checks them with BRAIN, saves them (mode 600)
    connect.go_live("USA")        # every app now uses your BRAIN account, region USA
    connect.go_sandbox()          # back to the offline practice market
    connect.logout()              # delete saved credentials and session

Your password is stored only in ~/.hypolab/credentials.json, readable only by you (chmod 600), and never in a
notebook or app. If you prefer not to store it, set BRAIN_EMAIL / BRAIN_PASSWORD in the shell before starting marimo.
"""
from __future__ import annotations

import getpass
import json
import os
from typing import Optional

from . import config
from .brain import AuthError, BrainClient, _cred_path, _session_path, _write_private


_CLIENT: Optional[BrainClient] = None     # one logged-in client per Python session, shared by every step


def _creds_source() -> str:
    if os.environ.get("BRAIN_EMAIL") and os.environ.get("BRAIN_PASSWORD"):
        return f"environment variables (BRAIN_EMAIL={os.environ['BRAIN_EMAIL']})"
    p = _cred_path()
    if p.exists():
        try:
            return f"saved file {p} (email {json.loads(p.read_text()).get('email', '?')})"
        except (OSError, json.JSONDecodeError):
            return f"saved file {p} (unreadable - run connect.login() again)"
    return "none yet - run connect.login()"


def status() -> dict:
    """Print and return where you stand: mode, region, credentials, session."""
    st = config.settings()
    sess = "none"
    if _session_path().exists():
        b = BrainClient(verbose=False)
        left = b.seconds_left()
        sess = f"cached, about {left / 3600:.1f} h left (checked locally)" if left > 0 else "expired - next call logs in again"
    info = {"mode": st.get("mode", "sandbox"), "live_region": st.get("live_region", "USA"),
            "credentials": _creds_source(), "session": sess, "data folder": str(config.HOME)}
    for k, v in info.items():
        print(f"{k:>12}: {v}")
    if info["mode"] != "live":
        print("\nYou are in SANDBOX mode (practice data). When ready: connect.login(), then connect.go_live('USA').")
    return info


def login(email: Optional[str] = None, save: bool = True) -> BrainClient:
    """Ask for your BRAIN email and password, verify them by logging in, and (by default) save them.

    For terminals: the password prompt hides what you type. (The cockpit uses begin_login/finish_login.)
    If BRAIN asks for biometrics, a link is printed: open it, do the face scan, then press ENTER in the box.
    """
    global _CLIENT
    email = (email or input("BRAIN email: ")).strip()
    pw = getpass.getpass("BRAIN password (hidden): ")
    brain = BrainClient(credentials=(email, pw))
    try:
        brain.login(force=True)
    except AuthError as e:
        print(f"Login failed: {e}\nNothing was saved. Check the email/password on platform.worldquantbrain.com.")
        raise
    _CLIENT = brain
    if save:
        _write_private(_cred_path(), {"email": email, "password": pw})
        print(f"Credentials verified and saved to {_cred_path()} (readable only by you).")
    else:
        print("Logged in for this session only (credentials not saved).")
    return brain


# ---------------------------------------------------------------- login from a web page (the cockpit)
_PENDING: Optional[dict] = None     # a login waiting for the face scan: {client, url, email, password, save}


def begin_login(email: str, password: str, save: bool = True) -> dict:
    """Step 1 of a login without a terminal. Returns {"status": "ok"} or {"status": "biometric", "url": ...}.

    Credentials are saved (mode 600) only once BRAIN has accepted them, exactly as in login()."""
    global _CLIENT, _PENDING
    brain = BrainClient(credentials=(email.strip(), password), verbose=False)
    res = brain.begin_login()                         # raises AuthError on a wrong password; nothing saved
    if res["status"] == "biometric":
        _PENDING = {"client": brain, "url": res["url"], "email": email.strip(), "password": password, "save": save}
        return {"status": "biometric", "url": res["url"]}
    return _accept(brain, email.strip(), password, save)


def pending() -> Optional[dict]:
    """The login waiting for a face scan, if any: {"status": "biometric", "url": ...}."""
    return {"status": "biometric", "url": _PENDING["url"]} if _PENDING else None


def resume_saved_login() -> dict:
    """Renew an expired session with the SAVED credentials, never prompting.

    Returns {"status": "ok"} or {"status": "biometric", "url": ...}. A face-scan request is started at most once:
    while one is waiting, every caller gets the same link (each new attempt would make BRAIN open a new one)."""
    global _PENDING
    if _PENDING is not None:
        return {"status": "biometric", "url": _PENDING["url"]}
    brain = BrainClient(verbose=False)
    email, password = brain._credentials()           # env vars or ~/.hypolab/credentials.json (callers check first)
    brain._given_credentials = (email, password)
    res = brain.begin_login()                        # raises AuthError if BRAIN refuses the password
    if res["status"] == "biometric":
        _PENDING = {"client": brain, "url": res["url"], "email": email, "password": password, "save": False}
        return {"status": "biometric", "url": res["url"]}
    return _accept(brain, email, password, save=False)


def finish_login() -> dict:
    """Step 2, after the face scan. {"status": "ok"}, or {"status": "waiting"} if BRAIN has not seen it yet."""
    global _PENDING
    if _PENDING is None:
        return {"status": "none", "detail": "no login is waiting for a face scan"}
    res = _PENDING["client"].finish_biometric(_PENDING["url"])
    if res["status"] != "ok":
        return {"status": "waiting", "url": _PENDING["url"]}
    p, _PENDING = _PENDING, None
    return _accept(p["client"], p["email"], p["password"], p["save"])


def _accept(brain: BrainClient, email: str, password: str, save: bool) -> dict:
    global _CLIENT
    _CLIENT = brain
    if save:
        _write_private(_cred_path(), {"email": email, "password": password})
    return {"status": "ok", "hours_left": round(brain.seconds_left() / 3600, 1), "saved": bool(save)}


def client(login_now: bool = True) -> BrainClient:
    """The logged-in BrainClient for this Python session.

    Reuses the client from connect.login() (or a valid saved session) - so you do the face scan once,
    not once per step."""
    global _CLIENT
    if _CLIENT is not None and _CLIENT.seconds_left() > 600:
        return _CLIENT
    b = _CLIENT or BrainClient()
    if login_now:
        b.login()
    _CLIENT = b
    return b


def go_live(region: Optional[str] = None) -> dict:
    """Switch every app to your BRAIN account (and optionally set the region they use)."""
    changes = {"mode": "live"}
    if region:
        changes["live_region"] = region.upper()
    st = config.save_settings(**changes)
    print(f"LIVE mode on - the apps will use your BRAIN account, region {st['live_region']}. "
          "Reload any app page that is already open.")
    if "none yet" in _creds_source():
        print("Note: no credentials saved yet - run connect.login() first, or log in on the cockpit's Setup tab.")
    return st


def go_sandbox() -> dict:
    st = config.save_settings(mode="sandbox")
    print("SANDBOX mode on - the apps use the offline practice market. Your credentials are kept.")
    return st


def logout(forget_credentials: bool = True):
    """Delete the cached session and (by default) the saved credentials."""
    global _CLIENT
    _CLIENT = None
    for p in [_session_path()] + ([_cred_path()] if forget_credentials else []):
        if p.exists():
            p.unlink()
            print(f"deleted {p}")
    print("Logged out.")
