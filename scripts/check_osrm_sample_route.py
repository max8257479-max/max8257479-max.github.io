#!/usr/bin/env python3
"""One-request smoke test for the supplied six-point Yandex route via public OSRM."""
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

POINTS = [
    (53.904025, 27.552364),
    (53.537565, 26.881842),
    (53.577807, 26.137365),
    (53.498433, 25.650338),
    (53.077671, 25.302761),
    (53.874176, 27.475459),
]


def main() -> int:
    coordinates = ";".join(f"{lon},{lat}" for lat, lon in POINTS)
    url = (
        "https://router.project-osrm.org/route/v1/driving/"
        f"{coordinates}?overview=false&steps=false&alternatives=false"
    )
    request = Request(url, headers={"User-Agent": "AnytimeHelloCalculator/1.0"})
    payload = None
    for attempt in range(2):
        try:
            with urlopen(request, timeout=25) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504):
                print(f"SKIPPED: public OSRM temporarily returned HTTP {exc.code}.")
                return 0
            raise
        except (URLError, TimeoutError, OSError) as exc:
            if attempt == 0:
                time.sleep(2)
                continue
            print(f"SKIPPED: public OSRM could not be reached from this runner: {exc}")
            return 0

    if payload is None:
        print("SKIPPED: no OSRM response.")
        return 0
    if payload.get("code") != "Ok":
        print(f"FAIL: OSRM route response code is {payload.get('code')!r}.")
        return 1

    routes = payload.get("routes") or []
    if not routes:
        print("FAIL: OSRM returned no routes.")
        return 1
    legs = routes[0].get("legs") or []
    if len(legs) != len(POINTS) - 1:
        print(f"FAIL: expected 5 legs for 6 points, received {len(legs)}.")
        return 1

    for index, leg in enumerate(legs):
        distance = leg.get("distance")
        duration = leg.get("duration")
        if not isinstance(distance, (int, float)) or distance < 0:
            print(f"FAIL: leg {index} has invalid distance.")
            return 1
        if not isinstance(duration, (int, float)) or duration < 0:
            print(f"FAIL: leg {index} has invalid duration.")
            return 1

    total_m = sum(float(leg["distance"]) for leg in legs)
    total_s = sum(float(leg["duration"]) for leg in legs)
    middle_m = sum(float(leg["distance"]) for leg in legs[1:-1])
    outer_s = (
        float(legs[0]["duration"])
        if len(legs) == 1
        else float(legs[0]["duration"]) + float(legs[-1]["duration"])
    )
    result = {
        "points": len(POINTS),
        "legs": len(legs),
        "total_km_0_1": round(total_m / 100) / 10,
        "total_drive_minutes": round(total_s / 60),
        "outer_drive_minutes": round(outer_s / 60),
        "middle_package_km_0_1": round(middle_m / 100) / 10,
        "segments": [
            {
                "from": index,
                "to": index + 1,
                "distance_km": round(float(leg["distance"]) / 100) / 10,
                "duration_minutes": round(float(leg["duration"]) / 60),
            }
            for index, leg in enumerate(legs)
        ],
    }
    print("PASS: supplied six-point route was returned by OSRM.")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
