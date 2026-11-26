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
    match = re.search(r"const fmtFinalPrice=(n=>[{].*?[}]);", app, re.S)
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


def test_yandex_route_parser_and_leg_summaries():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    start = app.index("function parseYandexRouteLink(raw){")
    end = app.index("function formatRouteKm(value){", start)
    pure_helpers = app[start:end]
    sample = (
        "https://yandex.by/maps/?ll=26.413707%2C53.464815&mode=routes"
        "&rtext=53.904025%2C27.552364~53.537565%2C26.881842"
        "~53.577807%2C26.137365~53.498433%2C25.650338"
        "~53.077671%2C25.302761~53.874176%2C27.475459"
        "&rtt=auto&ruri=ymapsbm1%3A%2F%2Forg%3Foid%3D1209008281~~~~~&z=9.09"
    )
    script = f"""
{pure_helpers}
const sample = {json.dumps(sample)};
const countLink = n => 'https://yandex.by/maps/?mode=routes&rtext=' +
  Array.from({{length:n}}, (_,i) => (53 + i/1000) + ',' + (27 + i/1000)).join('~');
const points = parseYandexRouteLink(sample);
const counts = [2,3,8].map(n => parseYandexRouteLink(countLink(n)).length);
const legs = [
  {{distance:1000.2,duration:60.4}},
  {{distance:2000.4,duration:120.5}},
  {{distance:3000.5,duration:180.2}},
  {{distance:4000.3,duration:240.1}},
  {{distance:5000.4,duration:300.4}}
];
const totals = summarizeRouteLegs(legs);
const oneLeg = summarizeRouteLegs([{{distance:1234,duration:119}}]);
console.log(JSON.stringify({{points,counts,totals,oneLeg}}));
"""
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    assert len(data["points"]) == 6
    assert data["points"][0] == {"lat": 53.904025, "lon": 27.552364}
    assert data["points"][-1] == {"lat": 53.874176, "lon": 27.475459}
    assert data["counts"] == [2, 3, 8]
    assert data["totals"]["totalKm"] == 15.0
    assert data["totals"]["packageKm"] == 9.0
    assert data["totals"]["totalMinutes"] == 15
    assert data["totals"]["outerDriveMinutes"] == 6
    assert data["oneLeg"]["outerDriveMinutes"] == 2
    assert data["oneLeg"]["packageKm"] == 0


def test_route_import_updates_all_four_inputs_and_keeps_manual_edits_independent():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for field in ("km", "hours", "minutes", "driveHours", "driveMinutes", "helloPackageKm"):
        assert f"$('{field}').value=" in app
    for key in ("km", "rentalTime", "outerDrive", "packageKm"):
        assert f"{key}:false" in app
    assert "markRouteFieldManual(key);calcAll();" in app
    assert "Object.keys(routeFieldManual).forEach(key=>routeFieldManual[key]=false);" in app
    assert "routeFieldEditVersion[key]++" in app
    assert "changedDuringLoad.includes('km')" in app
    assert "changedDuringLoad.includes('rentalTime')" in app
    assert "changedDuringLoad.includes('outerDrive')" in app
    assert "changedDuringLoad.includes('packageKm')" in app
    assert "routeInputTimer=setTimeout" in app
    assert "calculateRouteFromYandexLink(true,snapshot)" in app
    assert "Маршрут загружен" in app
    assert "Загружаем маршрут" in app
    assert "Изменено вручную" in app
    assert "Не удалось получить данные маршрута" in app
    assert 'id="routeCalculate" type="button">Обновить по ссылке</button>' in html
    assert 'id="parking"' in html and "Время на остановках" in html
    assert 'id="routeDetails"' in html
    route_logic = app[app.index("function parseYandexRouteLink"):app.index("// Existing bonus percentage")]
    assert "gapMeters" not in route_logic
    assert "500" not in route_logic
