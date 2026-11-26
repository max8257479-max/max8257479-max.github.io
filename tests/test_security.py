import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_uses_external_script_and_strict_content_security_policy():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<script src="\\./app\\.js(?:\\?v=\\d+)?" defer></script>', html)
    assert re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html, re.I) is None
    assert "script-src 'self'" in html
    assert "connect-src 'self' https://router.project-osrm.org https://valhalla1.openstreetmap.de https://brouter.de" in html
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
    assert data["totals"]["outerKm"] == 6.0
    assert data["oneLeg"]["outerDriveMinutes"] == 2
    assert data["oneLeg"]["outerKm"] == 1.2
    assert data["oneLeg"]["packageKm"] == 0


def test_route_import_updates_first_and_last_legs_and_keeps_manual_edits_independent():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "$('km').value=totals.totalKm.toFixed(1)" in app
    assert "writeTimePair('driveTime',totals.totalMinutes)" in app
    assert "writeTimePair('firstDrive',totals.firstDriveMinutes)" in app
    assert "$('firstKm').value=totals.firstKm.toFixed(1)" in app
    assert "writeTimePair('lastDrive',totals.lastDriveMinutes)" in app
    assert "$('lastKm').value=totals.lastKm.toFixed(1)" in app
    for key in ("km", "totalDrive", "firstDrive", "firstKm", "lastDrive", "lastKm"):
        assert f"{key}:false" in app
        assert f"changedDuringLoad.includes('{key}')" in app
    assert "function syncTripTimeFromParts()" in app
    assert "tripTimeManual=true" in app
    assert "tripTimeManual=false" in app
    assert "packageTime=t-outerDrive" in app
    assert "packageKm=Math.round((d-outerKm+Number.EPSILON)*10)/10" in app
    assert "outerDrive=firstDrive+lastDrive" in app
    assert "outerKm=Math.round((firstKm+lastKm+Number.EPSILON)*10)/10" in app
    assert "anytimeOptions(v,t,d,drive,park,true)" in app
    assert "helloOptions(v,t,d,drive,park,outerDrive,packageTime,packageKm,mixedValid)" in app
    assert "Auto: время за рулём + места" in app
    assert "Маршрут загружен" in app
    assert "Сравниваю три бесплатных маршрутизатора" in app
    assert "Изменено вручную" in app
    assert 'id="routeCalculate" type="button">Обновить по ссылке</button>' in html
    assert 'id="routeDetails"' in html
    assert 'id="driveTimeHours"' in html and "Время за рулём" in html
    assert 'id="km"' in html and '<label for="km">Км всей поездки</label>' in html
    assert "Километраж поездки" not in html
    assert "Время на места" in html
    assert "Время всей поездки" in html
    assert "Первый участок" in html and 'id="firstKm"' in html
    assert '<label for="firstKm">Км</label>' in html
    assert "Км первого участка" in html
    assert "Километраж" not in html
    assert "Последний участок" in html and 'id="lastKm"' in html
    assert '<label for="lastKm">Км</label>' in html
    assert "Км последнего участка" in html
    assert 'id="outerDriveTotal"' in html and 'id="outerKmTotal"' in html
    assert 'id="driveTimeStatus"' not in html and 'id="driveTimeStatus"' not in app
    assert "Суммарное время движения по всем участкам" not in html
    assert 'id="firstDriveStatus"' not in html and 'id="firstDriveStatus"' not in app
    assert 'id="lastDriveStatus"' not in html and 'id="lastDriveStatus"' not in app
    assert "Время первого участка</small>" not in html
    assert "Время последнего участка</small>" not in html
    assert 'label for="packageTime">Время</label>' in html and 'id="packageTime"' in html
    assert 'label for="packageKm">Км</label>' in html and 'id="packageKm"' in html
    assert "Абонемент (середина пути)" in html
    assert "Суммарно по 1-му и последнему участкам" in html
    assert "с бонусом 10%" not in app
    assert " (с 10% бонусом)" in app
    assert '<label>Время</label><output id="outerDriveTotal"' in html
    assert '<label>Км</label><output id="outerKmTotal"' in html
    assert "Суммарное время 1-го и последнего участков" not in html
    assert "Суммарный километраж 1-го и последнего участков" not in html
    assert "Время всей поездки − суммарное время 1-го и последнего участков" not in html
    assert "const packageKmOutput=$('packageKm')" in app
    assert "packageKmOutput.textContent=packageKm>=0?formatRouteKm(packageKm)+' км':'—'" in app
    assert "packageKm=Math.round((d-outerKm+Number.EPSILON)*10)/10" in app
    assert "Первый и последний участки — минутный тариф, середина — абонемент ч+км" in html
    assert 'class="field timefield trip-total-time-field"' in html
    assert 'label for="tripHours">Время всей поездки</label>' in html
    assert ".trip-inputs{grid-template-columns:repeat(4,minmax(0,1fr))" in html
    assert ".trip-distance-field,.trip-total-time-field{padding:9px 10px" in html
    assert "background:linear-gradient(135deg,#f4f8fc 0%,#f9fbfd 100%)" in html
    assert 'class="hello-summary-row"' in html
    assert ".hello-summary-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))" in html
    assert "@media(max-width:600px){.hello-summary-row{grid-template-columns:1fr}}" in html
    assert "Автоматически: время за рулём + время на места" not in html
    assert "outerDriveHours" not in app and "outerDriveHours" not in html
    assert 'id="outerKm"' not in html
    route_logic = app[app.index("function parseYandexRouteLink"):app.index("// Existing bonus percentage")]
    assert "gapMeters" not in route_logic
    assert "distanceSpread>Math.max(5000" in route_logic


def test_summarize_route_legs_separates_first_and_last_segments():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    start = app.index("function summarizeRouteLegs(")
    end = app.index("function medianRouteValue(", start)
    helper = app[start:end]
    script = f"""
{helper}
const multi=summarizeRouteLegs([
 {{distance:12500,duration:600}},
 {{distance:20000,duration:1200}},
 {{distance:7500,duration:300}}
]);
const one=summarizeRouteLegs([{{distance:12345,duration:678}}]);
console.log(JSON.stringify({{multi,one}}));
"""
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    assert data["multi"]["firstKm"] == 12.5
    assert data["multi"]["lastKm"] == 7.5
    assert data["multi"]["outerKm"] == 20.0
    assert data["multi"]["firstDriveMinutes"] == 10
    assert data["multi"]["lastDriveMinutes"] == 5
    assert data["multi"]["outerDriveMinutes"] == 15
    assert data["multi"]["packageKm"] == 20.0
    assert data["one"]["firstKm"] == 12.3
    assert data["one"]["lastKm"] == 0
    assert data["one"]["outerKm"] == 12.3
    assert data["one"]["firstDriveMinutes"] == 11
    assert data["one"]["lastDriveMinutes"] == 0
    assert data["one"]["outerDriveMinutes"] == 11


def test_hello_mixed_tariff_uses_summed_first_last_segments_and_middle_time_distance():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    start = app.index("function helloOptions(")
    end = app.index("const timeText=", start)
    helper = app[start:end]
    script = f"""
const round2=n=>Math.round((n+Number.EPSILON)*100)/100;
const fmt=n=>Number(n).toFixed(2);
const timeText=m=>[Math.floor(m/60)?Math.floor(m/60)+' ч':'',m%60?m%60+' мин':''].filter(Boolean).join(' ')||'0 ч';
{helper}
const vehicle={{move:0.37,park:0.17,km:0.53,packages:[
  {{minutes:180,price:19,label:'3 ч.'}},
  {{minutes:360,price:29,label:'6 ч.'}},
  {{minutes:540,price:39,label:'9 ч.'}}
]}};
const options=helloOptions(vehicle,240,100,180,60,30,210,80,true).filter(o=>o.mixed);
console.log(JSON.stringify(options.map(o=>({{minutes:o.packageTime,km:o.packageKm,extra:o.extra,cost:o.cost,over:o.over}}))));
"""
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    assert [item["minutes"] for item in data] == [210, 210, 210]
    assert [item["km"] for item in data] == [80, 80, 80]
    assert data[0]["extra"] == 30
    assert data[0]["over"] > 0
    assert data[0]["cost"] == 81.89
    assert data[1]["extra"] == 0


def test_three_engine_route_consensus_uses_per_leg_median_and_flags_disagreement():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    start = app.index("function medianRouteValue(values){")
    end = app.index("function formatRouteKm(value){", start)
    helpers = app[start:end]
    script = f"""
{helpers}
const results = {{
  osrm: {{legs:[
    {{distance:76666.9,duration:4779.4}},
    {{distance:70758.4,duration:5742.6}},
    {{distance:40397.6,duration:2432}},
    {{distance:77820.7,duration:5167.1}},
    {{distance:192457.9,duration:8339.5}}
  ]}},
  valhalla: {{legs:[
    {{distance:76461,duration:5848.342}},
    {{distance:66202,duration:5498.93}},
    {{distance:40336,duration:2483.209}},
    {{distance:103366,duration:6045.259}},
    {{distance:192218,duration:8965.836}}
  ]}},
  brouter: {{legs:[
    {{distance:64542,duration:3240}},
    {{distance:60140,duration:2940}},
    {{distance:40364,duration:2160}},
    {{distance:103560,duration:5400}},
    {{distance:192460,duration:8760}}
  ]}}
}};
const result = combineRouteEngineResults(results, 5);
console.log(JSON.stringify({{
  names: result.names,
  distances: result.legs.map(leg => leg.distance),
  durations: result.legs.map(leg => leg.duration),
  warnings: result.comparisons.map(item => item.warning),
  spreads: result.comparisons.map(item => item.distanceSpread)
}}));
"""
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    assert data["names"] == ["osrm", "valhalla", "brouter"]
    assert data["distances"] == [76461, 66202, 40364, 103366, 192457.9]
    assert data["durations"] == [4779.4, 5498.93, 2432, 5400, 8760]
    assert data["warnings"] == [True, True, False, True, False]
    assert data["spreads"][3] > 25000


def test_route_import_uses_three_free_public_engines_without_api_keys():
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "https://router.project-osrm.org/route/v1/driving/" in app
    assert "https://valhalla1.openstreetmap.de/route" in app
    assert "X-Client-Id':'max8257479-max.github.io'" in app
    assert "https://brouter.de/brouter?" in app
    assert "profile:'car-eco'" in app
    assert "Math.max(5000,distance*0.10)" in app
    assert "Сравниваю три бесплатных маршрутизатора" in app
    assert "Медиана результатов" in html
    assert all(f">{name}</a>" in html for name in ("OSRM", "Valhalla", "BRouter"))
    assert "Сверка трёх бесплатных маршрутизаторов" not in html
    assert "медиана результатов" not in html
