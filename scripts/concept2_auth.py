"""One-time Concept2 Logbook OAuth helper (optional; only if you row).

Usage:
    1. Register an API application with Concept2 (see the Logbook API documentation,
       https://log.concept2.com/developers/documentation/) with the redirect URI
       http://localhost:8766, and set CONCEPT2_CLIENT_ID and CONCEPT2_CLIENT_SECRET in .env.
    2. Run: python scripts/concept2_auth.py
    3. It opens the auth URL, catches the redirect on http://localhost:8766,
       exchanges the code, and writes CONCEPT2_REFRESH_TOKEN back into .env.

Access is read-only (user:read, results:read); the scopes must match SCOPES in
src/fitness/concept2_sync.py.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
load_dotenv(ENV)

CLIENT_ID = os.environ.get("CONCEPT2_CLIENT_ID")
CLIENT_SECRET = os.environ.get("CONCEPT2_CLIENT_SECRET")
PORT = 8766                      # one up from Strava's 8765 so they can't clash
REDIRECT = f"http://localhost:{PORT}"
SCOPES = "user:read,results:read"

if not CLIENT_ID or not CLIENT_SECRET:
    sys.exit("Set CONCEPT2_CLIENT_ID and CONCEPT2_CLIENT_SECRET in .env first.")

AUTH_URL = (
    "https://log.concept2.com/oauth/authorize"
    f"?client_id={CLIENT_ID}&response_type=code"
    f"&redirect_uri={urllib.parse.quote(REDIRECT, safe='')}"
    f"&scope={urllib.parse.quote(SCOPES, safe='')}"
)

code_holder = {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        if "code" in qs:
            code_holder["code"] = qs["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Got it. You can close this tab.</h1>")
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, *a, **kw):
        pass


print(f"Opening browser: {AUTH_URL}")
webbrowser.open(AUTH_URL)

httpd = HTTPServer(("localhost", PORT), Handler)
while "code" not in code_holder:
    httpd.handle_request()

data = urllib.parse.urlencode({
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "code": code_holder["code"],
    "grant_type": "authorization_code",
    "redirect_uri": REDIRECT,
    "scope": SCOPES,
}).encode()
req = urllib.request.Request(
    "https://log.concept2.com/oauth/access_token", data=data)
resp = json.loads(urllib.request.urlopen(req).read())
print("Got refresh token (not printed).")

sys.path.insert(0, str(ROOT / "src"))
from fitness.envfile import set_env_var  # noqa: E402  (atomic write; keeps the rest of .env)

set_env_var("CONCEPT2_REFRESH_TOKEN", resp["refresh_token"], ENV)
print("Wrote CONCEPT2_REFRESH_TOKEN to .env. Done.")
