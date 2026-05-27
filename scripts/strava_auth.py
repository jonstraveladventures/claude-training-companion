"""One-time Strava OAuth helper.

Usage:
    1. Make sure STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET are set in .env
    2. Run: python scripts/strava_auth.py
    3. Follow the printed instructions — it opens the auth URL, catches the
       redirect on http://localhost:8765, exchanges the code, and writes
       STRAVA_REFRESH_TOKEN back into .env.
"""
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import urllib.request
import urllib.parse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
load_dotenv(ENV)

CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET")
PORT = 8765
REDIRECT = f"http://localhost:{PORT}"

if not CLIENT_ID or not CLIENT_SECRET:
    sys.exit("Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in .env first.")

AUTH_URL = (
    "https://www.strava.com/oauth/authorize"
    f"?client_id={CLIENT_ID}&response_type=code&redirect_uri={REDIRECT}"
    "&approval_prompt=force&scope=read,activity:read_all,profile:read_all"
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


print(f"IMPORTANT: set Authorization Callback Domain to 'localhost' in your Strava app settings.")
print(f"Opening browser: {AUTH_URL}")
webbrowser.open(AUTH_URL)

httpd = HTTPServer(("localhost", PORT), Handler)
while "code" not in code_holder:
    httpd.handle_request()

code = code_holder["code"]
print(f"Received code: {code[:10]}…")

data = urllib.parse.urlencode({
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "code": code,
    "grant_type": "authorization_code",
}).encode()
req = urllib.request.Request("https://www.strava.com/oauth/token", data=data)
import json
resp = json.loads(urllib.request.urlopen(req).read())
refresh = resp["refresh_token"]
print(f"Refresh token: {refresh}")

lines = ENV.read_text().splitlines()
out = []
replaced = False
for line in lines:
    if line.startswith("STRAVA_REFRESH_TOKEN="):
        out.append(f"STRAVA_REFRESH_TOKEN={refresh}")
        replaced = True
    else:
        out.append(line)
if not replaced:
    out.append(f"STRAVA_REFRESH_TOKEN={refresh}")
ENV.write_text("\n".join(out) + "\n")
print("Wrote STRAVA_REFRESH_TOKEN to .env. Done.")
