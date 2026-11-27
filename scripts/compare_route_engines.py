#!/usr/bin/env python3
"""Compare the supplied six-point route on public Valhalla and OSRM endpoints."""
import json
import os
import math
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

POINTS = [
    (53.904025, 27.552364),
    (53.537565, 26.881842),
    (53.577807, 26.137365),
    (53.498433, 25.650338),
    (53.077671, 25.302761),
    (53.874176, 27.475459),
]
ORIGIN = "https://max8257479-max.github.io"
CLIENT_ID = "max8257479-max.github.io"


def fetch_json(request, timeout=35):
    with urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return response.status, dict(response.headers.items()), json.loads(body)


def valhalla_route():
    locations = [
        {"lat": lat, "lon": lon, "type": "break", "radius": 150}
        for lat, lon in POINTS
    ]
    payload = {
        "locations": locations,
        "costing": "auto",
        "units": "kilometers",
        "language": "ru-RU",
        "directions_type": "none",
        "id": CLIENT_ID,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Client-Id": CLIENT_ID,
        "Origin": ORIGIN,
        "User-Agent": "AnytimeHelloCalculator/1.0 (+https://max8257479-max.github.io/)",
    }
    preflight = Request(
        "https://valhalla1.openstreetmap.de/route",
        method="OPTIONS",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-client-id",
            "User-Agent": headers["User-Agent"],
        },
    )
    try:
        with urlopen(preflight, timeout=20) as response:
            response.read()
            preflight_status, preflight_headers = response.status, dict(response.headers.items())
    except HTTPError as exc:
        preflight_status, preflight_headers = exc.code, dict(exc.headers.items())
    except (URLError, TimeoutError, OSError) as exc:
        preflight_status, preflight_headers = None, {"error": str(exc)}

    request = Request(
        "https://valhalla1.openstreetmap.de/route",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    status, response_headers, data = fetch_json(request)
    trip = data.get("trip") or {}
    legs = trip.get("legs") or []
    if len(legs) != len(POINTS) - 1:
        raise RuntimeError(
            f"Valhalla expected 5 legs, received {len(legs)}; "
            f"status={trip.get('status_message')!r}; response={json.dumps(data)[:1200]}"
        )
    result = []
    for index, leg in enumerate(legs):
        summary = leg.get("summary") or {}
        length_km = float(summary.get("length", -1))
        duration_s = float(summary.get("time", -1))
        if not math.isfinite(length_km) or length_km < 0 or not math.isfinite(duration_s) or duration_s < 0:
            raise RuntimeError(f"Valhalla leg {index} returned invalid summary: {summary!r}")
        result.append({"from": index, "to": index + 1, "distance_km": length_km, "duration_s": duration_s})

    allow_origin = preflight_headers.get("Access-Control-Allow-Origin") or preflight_headers.get("access-control-allow-origin")
    allow_headers = preflight_headers.get("Access-Control-Allow-Headers") or preflight_headers.get("access-control-allow-headers", "")
    return {
        "http_status": status,
        "trip_summary": trip.get("summary"),
        "legs": result,
        "locations": trip.get("locations"),
        "preflight": {
            "status": preflight_status,
            "allow_origin": allow_origin,
            "allow_headers": allow_headers,
        },
    }


def osrm_route():
    coords = ";".join(f"{lon},{lat}" for lat, lon in POINTS)
    url = (
        "https://router.project-osrm.org/route/v1/driving/"
        f"{coords}?overview=false&steps=false&alternatives=false"
    )
    request = Request(url, headers={"User-Agent": "AnytimeHelloCalculator/1.0"})
    status, _, data = fetch_json(request)
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RuntimeError(f"OSRM failed: {data!r}")
    legs = data["routes"][0].get("legs") or []
    if len(legs) != len(POINTS) - 1:
        raise RuntimeError(f"OSRM expected 5 legs, received {len(legs)}")
    return {
        "http_status": status,
        "legs": [
            {
                "from": index,
                "to": index + 1,
                "distance_km": float(leg["distance"]) / 1000,
                "duration_s": float(leg["duration"]),
            }
            for index, leg in enumerate(legs)
        ],
    }



def brouter_route(profile):
    result = []
    for index, (start, end) in enumerate(zip(POINTS, POINTS[1:])):
        lonlats = f"{start[1]},{start[0]}|{end[1]},{end[0]}"
        query = urlencode({
            "lonlats": lonlats,
            "profile": profile,
            "alternativeidx": "0",
            "format": "geojson",
        })
        request = Request(
            "https://brouter.de/brouter?" + query,
            headers={
                "Origin": ORIGIN,
                "User-Agent": "AnytimeHelloCalculator/1.0 (+https://max8257479-max.github.io/)",
            },
        )
        status, response_headers, data = fetch_json(request, timeout=60)
        features = data.get("features") or []
        if not features:
            raise RuntimeError(f"BRouter leg {index} returned no GeoJSON feature: {str(data)[:500]}")
        properties = features[0].get("properties") or {}
        distance_m = float(properties.get("track-length", -1))
        duration_s = float(properties.get("total-time", -1))
        if not math.isfinite(distance_m) or distance_m < 0 or not math.isfinite(duration_s) or duration_s < 0:
            raise RuntimeError(f"BRouter leg {index} returned invalid properties: {properties!r}")
        result.append({
            "from": index,
            "to": index + 1,
            "distance_km": distance_m / 1000,
            "duration_s": duration_s,
            "cors_allow_origin": response_headers.get("Access-Control-Allow-Origin"),
        })
        # Public community service: keep requests deliberately slow.
        time.sleep(1.2)
    return {"http_status": 200, "profile": profile, "legs": result}



def yandex_route(api_key, traffic_mode=None):
    """Call Yandex Router API for the same six points; never print or persist the API key."""
    params = {
        "apikey": api_key,
        "waypoints": "|".join(f"{lat},{lon}" for lat, lon in POINTS),
        "mode": "driving",
    }
    if traffic_mode is not None:
        params["traffic"] = traffic_mode
    request = Request(
        "https://api.routing.yandex.net/v2/route?" + urlencode(params),
        headers={"User-Agent": "AnytimeHelloCalculator/1.0"},
    )
    try:
        status, _, data = fetch_json(request, timeout=45)
    except HTTPError as exc:
        raise RuntimeError(f"Yandex HTTP {exc.code}") from None
    route = data.get("route") or {}
    legs = route.get("legs") or []
    if len(legs) != len(POINTS) - 1:
        raise RuntimeError(
            f"Yandex expected 5 legs, received {len(legs)}; "
            f"traffic_type={data.get('traffic_type')!r}"
        )
    result = []
    for index, leg in enumerate(legs):
        if leg.get("status") != "OK":
            raise RuntimeError(f"Yandex leg {index} status is not OK")
        steps = leg.get("steps") or []
        distance_m = sum(float(step.get("length", 0)) for step in steps)
        duration_s = sum(float(step.get("duration", 0)) for step in steps)
        if not math.isfinite(distance_m) or distance_m < 0 or not math.isfinite(duration_s) or duration_s < 0:
            raise RuntimeError(f"Yandex leg {index} returned invalid metrics")
        result.append({
            "from": index,
            "to": index + 1,
            "distance_km": distance_m / 1000,
            "duration_s": duration_s,
        })
    return {
        "http_status": status,
        "traffic_type": data.get("traffic_type"),
        "legs": result,
    }


def main():
    result = {}
    errors = {}
    for name, fn in (("valhalla", valhalla_route), ("osrm", osrm_route), ("brouter_fast", lambda: brouter_route("car-fast")), ("brouter_eco", lambda: brouter_route("car-eco"))):
        try:
            result[name] = fn()
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
        time.sleep(1.2)

    api_key = os.environ.get("YANDEX_ROUTER_API_KEY", "").strip()
    if api_key:
        for name, traffic_mode in (("yandex_default", None), ("yandex_no_traffic", "disabled")):
            try:
                result[name] = yandex_route(api_key, traffic_mode)
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
                # Do not expose the API key or request URL in logs.
                errors[name] = f"{type(exc).__name__}: {exc}"
            time.sleep(1.2)
    else:
        errors["yandex"] = "Skipped: add YANDEX_ROUTER_API_KEY as a GitHub Actions secret."

    if len(result) >= 2:
        engine_names = [name for name in ("valhalla", "osrm", "brouter_fast", "brouter_eco", "yandex_default", "yandex_no_traffic") if name in result]
        result["comparison"] = []
        for index in range(len(POINTS) - 1):
            row = {"segment": f"{index}→{index + 1}"}
            for name in engine_names:
                leg = result[name]["legs"][index]
                row[name + "_km"] = round(leg["distance_km"], 2)
                row[name + "_minutes"] = round(leg["duration_s"] / 60)
            # Match the calculator's live three-engine median: OSRM, Valhalla, BRouter car-eco.
            median_engines = [name for name in ("osrm", "valhalla", "brouter_eco") if name in result]
            if len(median_engines) == 3:
                distances = sorted(result[name]["legs"][index]["distance_km"] for name in median_engines)
                durations = sorted(result[name]["legs"][index]["duration_s"] for name in median_engines)
                row["calculator_median_km"] = round(distances[1], 2)
                row["calculator_median_minutes"] = round(durations[1] / 60)
            result["comparison"].append(row)

    print(json.dumps({"results": result, "errors": errors}, ensure_ascii=False, indent=2))
    if "valhalla" not in result:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
