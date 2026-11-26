import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_uses_external_script_and_strict_content_security_policy():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert '<script src="./app.js" defer></script>' in html
    assert re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html, re.I) is None
    assert "script-src 'self'" in html
    assert "connect-src 'self' https://router.project-osrm.org" in html
    assert "require-trusted-types-for 'script'" in html
    assert 'name="referrer" content="no-referrer"' in html


def test_frontend_has_no_string_to_html_or_dynamic_code_sinks():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    forbidden = (".innerHTML", ".outerHTML", "insertAdjacentHTML(", "eval(", "new Function(")
    for token in forbidden:
        assert token not in app


def test_frontend_has_no_inline_event_handlers():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert re.search(r"\son[a-z]+\s*=", html, re.I) is None
