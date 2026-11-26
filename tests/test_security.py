import json
import re
import subprocess
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


def test_pages_workflow_supports_safe_user_site_rename():
    workflow = (ROOT / ".github" / "workflows" / "update-tariffs.yml").read_text(encoding="utf-8")
    assert "deploy_only:" in workflow
    assert "inputs.deploy_only != true" in workflow
    assert "inputs.deploy_only == true" in workflow
    assert "mkdir -p site/anytime-hello-calculator" in workflow
    assert 'meta http-equiv="refresh" content="0; url=/"' in workflow


def test_final_price_formatter_rounds_to_one_decimal():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    match = re.search(r"const fmtFinalPrice=(n=>\\{.*?\\});", app, re.S)
    assert match is not None
    script = f"const fmtFinalPrice={match.group(1)}; console.log(JSON.stringify([fmtFinalPrice(19.87), fmtFinalPrice(19.84), fmtFinalPrice(20.05), fmtFinalPrice(20), fmtFinalPrice(7.99)]));"
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == ["19,9", "19,8", "20,1", "20,0", "8,0"]


def test_all_final_price_outputs_use_one_decimal_formatter():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    for expected in (
        "fmtFinalPrice(effectiveCost(v,o.cost))",
        "fmtFinalPrice(r.best.cost)",
        "fmtFinalPrice(effective(a))",
        "fmtFinalPrice(a.best.cost)",
        "fmtFinalPrice(payWinner.best.cost)",
        "fmtFinalPrice(best.cost)",
        "fmtFinalPrice(o.cost)",
        "fmtFinalPrice(bonus)",
    ):
        assert expected in app
    # Calculation precision remains unchanged; only displayed totals are rounded.
    assert "const round2=n=>Math.round((n+Number.EPSILON)*100)/100;" in app
    assert "const bonusAmount=(v,cost)=>v.provider==='Anytime'?Math.round(cost*0.10*100)/100:0;" in app
    assert "const effectiveCost=(v,cost)=>v.provider==='Anytime'?Math.round(cost*0.90*100)/100:cost;" in app
