"""Terminal commands:  python -m hypolab <command>

  status            mode, region, credentials, session
  login             enter + verify + save your BRAIN credentials
  live [REGION]     switch every app to your BRAIN account (e.g. `live USA`)
  sandbox           switch every app back to the offline practice market
  logout            delete saved credentials and session
  options           regions / universes / delays / neutralizations your account can use
  cockpit           open the marimo apps (cockpit, dataset scan, quant basics) in your browser
"""
import sys

from . import connect


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "status"
    if cmd == "status":
        connect.status()
    elif cmd == "login":
        connect.login()
    elif cmd == "live":
        connect.go_live(argv[1] if len(argv) > 1 else None)
    elif cmd == "sandbox":
        connect.go_sandbox()
    elif cmd == "logout":
        connect.logout()
    elif cmd == "cockpit":
        import subprocess
        from pathlib import Path
        from . import config
        folder = Path(__file__).resolve().parent.parent / "apps"
        extra = argv[1:]
        if not any(a.startswith("--session-ttl") for a in extra):
            # marimo closes an app 120 s after the browser loses its connection (laptop asleep, Wi-Fi blip) and the
            # tab then says "kernel not found". Keep it alive longer (settings.json: session_ttl_seconds).
            extra += ["--session-ttl", str(int(config.settings().get("session_ttl_seconds", 3600)))]
        return subprocess.call([sys.executable, "-m", "marimo", "run", str(folder)] + extra)
    elif cmd == "options":
        import pandas as pd
        pd.set_option("display.max_colwidth", 120, "display.width", 200)
        print(connect.client().simulation_options().to_string(index=False))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
