"""One-off: authorise @poltrendsau to post through Jim's existing X app.

Run this yourself in a terminal (it never prints the tokens):

    cd ~/coding/poltrends && .venv/bin/python scripts/x_authorise.py

1. It reads the app key and secret (X_API_KEY, X_API_SECRET) from the environment or
   ~/.hermes/.env.
2. It opens an X authorisation page. Make sure you are logged in as @poltrendsau there,
   approve the app, and copy the PIN that X shows.
3. Paste the PIN at the hidden prompt.
4. It saves the account's access token and secret to ~/.hermes/.env as
   POLTRENDS_X_ACCESS_TOKEN and POLTRENDS_X_ACCESS_TOKEN_SECRET, then either sets the four
   GitHub Actions secrets with `gh` or walks you through pasting them into GitHub one at a
   time via the clipboard.

Billing: these OAuth calls are not on X's pay-per-use price list; posting is.
"""
from __future__ import annotations

import getpass
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from requests_oauthlib import OAuth1Session

ENV_FILE = Path.home() / ".hermes" / ".env"
REPO = "StewartMedia/polltrends"
EXPECTED = "poltrendsau"
HOSTS = ("https://api.x.com", "https://api.twitter.com")


def env_value(name: str) -> str | None:
    if os.getenv(name):
        return os.environ[name]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def save_env(values: dict[str, str]) -> None:
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    lines = [ln for ln in lines if not any(ln.strip().removeprefix("export ").startswith(f"{k}=") for k in values)]
    lines += [f"{k}={v}" for k, v in values.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n")
    ENV_FILE.chmod(0o600)


def gh_set(name: str, value: str) -> bool:
    r = subprocess.run(["gh", "secret", "set", name, "--repo", REPO], input=value, text=True,
                       capture_output=True)
    return r.returncode == 0


def clipboard_walkthrough(secrets: dict[str, str]) -> None:
    url = f"https://github.com/{REPO}/settings/secrets/actions/new"
    print("\n`gh` cannot set secrets on this repo from this login, so let's do it in the browser.")
    print(f"Log in to GitHub as StewartMedia, then for each secret open:\n  {url}")
    for name, value in secrets.items():
        subprocess.run(["pbcopy"], input=value, text=True, check=True)
        input(f"\n  Name: {name}\n  The value is on your clipboard. Paste it, click 'Add secret', then press Enter here.")
    subprocess.run(["pbcopy"], input="", text=True)
    print("\nClipboard cleared.")


def main() -> int:
    key, secret = env_value("X_API_KEY"), env_value("X_API_SECRET")
    if not key or not secret:
        print("X_API_KEY / X_API_SECRET not found in the environment or ~/.hermes/.env.")
        return 1

    last_error = None
    for host in HOSTS:
        try:
            oauth = OAuth1Session(key, client_secret=secret, callback_uri="oob")
            req = oauth.fetch_request_token(f"{host}/oauth/request_token")
            break
        except Exception as exc:  # try the legacy host before giving up
            last_error = exc
    else:
        print(f"X refused the request token: {last_error}")
        print("Check the app in the X developer console: User authentication settings must be set up "
              "with 'Read and write' permission (any callback URL is fine; this script uses a PIN).")
        return 1

    auth_url = oauth.authorization_url(f"{host}/oauth/authorize")
    print("\nOpening X. Make sure the page says you are signing in as @poltrendsau, approve the app,")
    print("then copy the PIN it shows.\n")
    print(f"  {auth_url}\n")
    webbrowser.open(auth_url)
    pin = getpass.getpass("PIN (hidden): ").strip()

    oauth = OAuth1Session(key, client_secret=secret, resource_owner_key=req["oauth_token"],
                          resource_owner_secret=req["oauth_token_secret"], verifier=pin)
    try:
        acc = oauth.fetch_access_token(f"{host}/oauth/access_token")
    except Exception as exc:
        print(f"X refused the PIN: {exc}")
        return 1

    who = acc.get("screen_name", "?")
    if who.lower() != EXPECTED:
        print(f"\nThat authorised @{who}, not @{EXPECTED}. Nothing saved. Log in as @{EXPECTED} and run again.")
        return 1

    save_env({"POLTRENDS_X_ACCESS_TOKEN": acc["oauth_token"],
              "POLTRENDS_X_ACCESS_TOKEN_SECRET": acc["oauth_token_secret"]})
    print(f"\nAuthorised @{who}. Tokens saved to {ENV_FILE} (not printed).")

    secrets = {"X_API_KEY": key, "X_API_SECRET": secret,
               "X_ACCESS_TOKEN": acc["oauth_token"], "X_ACCESS_TOKEN_SECRET": acc["oauth_token_secret"]}
    if all(gh_set(k, v) for k, v in secrets.items()):
        print(f"GitHub Actions secrets set on {REPO}.")
    else:
        clipboard_walkthrough(secrets)
    print("\nDone. Posting stays in dry-run until the repository variable X_POST_MODE is set to 'live'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
