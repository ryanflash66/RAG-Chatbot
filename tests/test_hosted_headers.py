"""Tests for the security headers Vercel adds to every response (hosted/vercel.json); no network."""

import base64
import hashlib
import json
import re
from pathlib import Path

HOSTED = Path(__file__).resolve().parent.parent / "hosted"


def _headers():
    config = json.loads((HOSTED / "vercel.json").read_text(encoding="utf-8"))
    every = [rule for rule in config["headers"] if rule["source"] == "/(.*)"]
    assert len(every) == 1, "one rule covers every path: the page, the CDN's public/ files and /api"
    return {h["key"]: h["value"] for h in every[0]["headers"]}


def test_every_response_refuses_framing_and_sniffing():
    headers = _headers()
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "object-src 'none'" in headers["Content-Security-Policy"]
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_the_enforced_policy_does_not_restrict_scripts_until_the_report_only_one_is_clean():
    # Scripts and styles are only reported for now: an enforced script-src that
    # missed something would blank the page, and there is no check of it before deploy.
    enforced = _headers()["Content-Security-Policy"]
    assert "script-src" not in enforced and "default-src" not in enforced


def test_the_report_only_policy_allows_the_react_pages_inline_script():
    # web/index.html's dark-mode script runs before the bundle; changing it changes
    # its hash, which must be updated in vercel.json or the policy reports it.
    page = (HOSTED / "web" / "index.html").read_text(encoding="utf-8")
    inline = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert inline, "web/index.html has an inline script"
    policy = _headers()["Content-Security-Policy-Report-Only"]
    for script in inline:
        digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode()
        assert f"'sha256-{digest}'" in policy
    assert "'unsafe-eval'" not in policy
    assert "connect-src 'self'" in policy
