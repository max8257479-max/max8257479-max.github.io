#!/usr/bin/env python3
"""Compare the supplied six-point route on public Valhalla and OSRM endpoints."""
import json
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


def main():
    result = {}
    errors = {}
    for name, fn in (("valhalla", valhalla_route), ("osrm", osrm_route)):
        try:
            result[name] = fn()
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
        time.sleep(1.2)

    if "valhalla" in result and "osrm" in result:
        result["comparison"] = []
        for v, o in zip(result["valhalla"]["legs"], result["osrm"]["legs"]):
            result["comparison"].append({
                "segment": f'{v["from"]}→{v["to"]}',
                "valhalla_km": round(v["distance_km"], 2),
                "osrm_km": round(o["distance_km"], 2),
                "distance_delta_km": round(v["distance_km"] - o["distance_km"], 2),
                "valhalla_minutes": round(v["duration_s"] / 60),
                "osrm_minutes": round(o["duration_s"] / 60),
            })

    print(json.dumps({"results": result, "errors": errors}, ensure_ascii=False, indent=2))
    if "valhalla" not in result:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
