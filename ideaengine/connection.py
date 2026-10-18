"""Open HYPOLAB for the marimo apps - without ever blocking on a hidden prompt.

A marimo app has no terminal to type into, so input() there would hang the page. The apps reuse the
session saved by the Setup tab's login (or `python -m hypolab login`). If that session has expired they
may log in again silently with your saved credentials; if BRAIN then wants a face scan, they stop and
point you to the Setup tab, which handles the scan with a link and a button.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

from hypolab import config, connect
from hypolab.brain import AuthError, _cred_path
from hypolab.research import Researcher

LOGIN_HELP = ("Log in on the cockpit's Setup tab (it shows the face-scan link and a button), or from a "
              "terminal with `python -m hypolab login`, then reload. Pages never wait on a hidden prompt.")


def _refuse(prompt: str = ""):
    raise AuthError("BRAIN wants input (a face scan or a password). " + LOGIN_HELP)


def has_saved_credentials() -> bool:
    return bool(os.environ.get("BRAIN_EMAIL") and os.environ.get("BRAIN_PASSWORD")) or _cred_path().exists()


def open_researcher(region: Optional[str] = None) -> Tuple[Optional[Researcher], str]:
    """(Researcher, problem). Sandbox mode always works; live mode returns (None, why) instead of prompting.

    An expired session is renewed with the saved credentials. If BRAIN then wants a face scan, the request is kept
    (connect.pending()) and the Setup tab shows its link and a "done" button; other pages reuse the same request."""
    if config.sandbox_mode():
        return Researcher.sandbox(), ""
    brain = connect.client(login_now=False)
    brain.input = _refuse                              # any prompt -> clear error, never a hang
    if brain.seconds_left() < 300:
        if not has_saved_credentials():
            return None, "You are not logged in to BRAIN yet. " + LOGIN_HELP
        try:
            res = connect.resume_saved_login()
        except Exception as e:  # noqa: BLE001
            return None, f"Your BRAIN session expired and could not be renewed ({e}). " + LOGIN_HELP
        if res["status"] == "biometric":
            return None, ("Your BRAIN session expired and BRAIN wants a face scan. Open the **Setup** tab: the "
                          "link and the *I finished the face scan* button are there.")
    try:
        return Researcher.live(region, login=False, sync=False), ""
    except Exception as e:  # noqa: BLE001
        return None, f"Could not open your BRAIN account ({e}). " + LOGIN_HELP
