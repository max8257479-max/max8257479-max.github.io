#!/usr/bin/env python3
"""Daily tariff updater for the Anytime vs Hello calculator.

Hello: parse public official car pages and update only complete, validated records.
Anytime: monitor public secondary pages for signals; do NOT overwrite the full
app tariff matrix from incomplete third-party data. Apply only manually verified
patches from data/anytime_manual.json.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
TARIFFS_PATH = ROOT / "tariffs.json"
MANUAL_PATH = ROOT / "data" / "anytime_manual.json"
WATCH_PATH = ROOT / "data" / "anytime_watch.json"
HELLO_CATALOG = "https://hello.by/cars"
ANYTIME_CATALOG = "https://carsync.by/carsharings/anytime"
TIMEOUT = 35
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CarTariffUpdater/1.0; +https://github.com/)"
}


class ParseError(RuntimeError):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def date_stamp() -> str:
    return now_utc().date().isoformat()


def fetch_html(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def clean_text(html: str) -> tuple[BeautifulSoup, str]:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return soup, text


def number(value: str) -> float:
    return float(value.replace(" ", "").replace(",", "."))


def _duration_minutes(amount: int, unit: str) -> int:
    unit = unit.lower().replace("ё", "е")
    if unit.startswith("мин"):
        return amount
    if unit.startswith("ч"):
        return amount * 60
    if unit.startswith("сут") or unit.startswith("д"):
        return amount * 1440
    raise ParseError(f"Неизвестная единица времени: {unit}")


def _package_label(amount: int, unit: str) -> str:
    unit = unit.lower()
    if unit.startswith("мин"):
        return f"{amount} минут"
    if unit.startswith("ч"):
        return f"{amount} ч."
    return f"{amount} суток"


def parse_hello_page(url: str, html: str, existing_by_url: dict[str, dict]) -> dict:
    soup, text = clean_text(html)

    # Do not silently switch to another customer profile/discount tier.
    if "Я резидент Беларуси" not in text or "Опыт больше 1 года" not in text:
        raise ParseError("На странице не подтверждён профиль: резидент Беларуси, стаж больше 1 года")

    move_match = re.search(r"\b1\s*мин\.?\s*(?:—|–|-)?\s*([\d.,]+)\s*BYN", text, re.I)
    park_match = re.search(r"Стоянка тарифицируется по\s*([\d.,]+)\s*BYN", text, re.I)
    km_matches = re.findall(r"Каждый км по\s*([\d.,]+)\s*BYN", text, re.I)
    if not move_match or not park_match:
        raise ParseError("Не найдены обязательные цены: движение и стоянка")

    km_values = {round(number(x), 4) for x in km_matches}
    if len(km_values) > 1:
        raise ParseError(f"На странице несколько ставок за километр {sorted(km_values)}; схема калькулятора предполагает одну ставку")
    km_rate = next(iter(km_values)) if km_values else None

    section_specs = [
        ("МИНУТЫ И КМ", "ЧАСЫ И КМ"),
        ("ЧАСЫ И КМ", "СУТКИ И КМ"),
        ("СУТКИ И КМ", "Условия"),
    ]
    packages_by_minutes: dict[int, dict] = {}
    for start_marker, end_marker in section_specs:
        start = text.find(start_marker)
        if start < 0:
            continue
        end = text.find(end_marker, start + len(start_marker)) if end_marker else -1
        section = text[start:] if end < 0 else text[start:end]
        pattern = re.compile(
            r"(?<!\d)(\d+)\s*(мин\.?|ч\.?|сут\.?)\s*(?:—|–|-)?\s*([\d.,]+)\s*BYN",
            re.I,
        )
        for match in pattern.finditer(section):
            amount = int(match.group(1))
            unit = match.group(2)
            minutes = _duration_minutes(amount, unit)
            packages_by_minutes[minutes] = {
                "minutes": minutes,
                "price": number(match.group(3)),
                "label": _package_label(amount, unit),
            }

    packages = [packages_by_minutes[k] for k in sorted(packages_by_minutes)]
    if packages and km_rate is None:
        raise ParseError("Найдены абонементы, но не найдена ставка за километр")

    h1 = soup.find("h1")
    model = h1.get_text(" ", strip=True) if h1 else ""
    model = re.sub(r"^(Аренда|Прокат)\s+", "", model, flags=re.I).strip()
    if not model:
        raise ParseError("Не найдено название модели в h1")

    canonical = soup.find("link", rel="canonical")
    canonical_url = canonical.get("href") if canonical and canonical.get("href") else url
    canonical_url = urljoin(url, canonical_url)
    old = existing_by_url.get(canonical_url) or existing_by_url.get(url)
    slug = urlparse(canonical_url).path.rstrip("/").split("/")[-1]
    vehicle_id = old["id"] if old else f"hello-{slug}"

    result = {
        "id": vehicle_id,
        "provider": "Hello",
        "model": model,
        "tag": f"Официальный сайт · {date_stamp()}",
        "move": number(move_match.group(1)),
        "park": number(park_match.group(1)),
        "km": km_rate,
        "packages": packages,
        "source": canonical_url,
        "url": canonical_url,
    }
    # Do not change the visible verification date on every daily run if the
    # actual tariff record is byte-for-byte identical apart from that tag.
    if old:
        old_without_tag = {k: v for k, v in old.items() if k != "tag"}
        new_without_tag = {k: v for k, v in result.items() if k != "tag"}
        if old_without_tag == new_without_tag:
            result["tag"] = old.get("tag", result["tag"])
    return result


def discover_hello_urls(html: str) -> list[str]:
    soup, _ = clean_text(html)
    urls: list[str] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        parsed = urlparse(href)
        path = parsed.path if parsed.scheme else href.split("?", 1)[0]
        if not path.startswith("/cars/") or path.rstrip("/") == "/cars":
            continue
        full = urljoin(HELLO_CATALOG, href)
        if full not in seen:
            seen.add(full)
            urls.append(full)
    return urls


def scrape_hello(existing: list[dict]) -> tuple[list[dict], list[str]]:
    catalog_html = fetch_html(HELLO_CATALOG)
    urls = discover_hello_urls(catalog_html)
    if not urls:
        raise ParseError("Каталог Hello не вернул ссылки на страницы автомобилей")

    existing_by_url = {v.get("url"): v for v in existing if v.get("provider") == "Hello" and v.get("url")}
    existing_by_url.update({v.get("source"): v for v in existing if v.get("provider") == "Hello" and v.get("source")})
    scraped: list[dict] = []
    errors: list[str] = []
    for url in urls:
        try:
            parsed = parse_hello_page(url, fetch_html(url), existing_by_url)
            scraped.append(parsed)
        except Exception as exc:  # keep other successfully parsed models
            errors.append(f"{url}: {exc}")

    if not scraped:
        raise ParseError("Не удалось разобрать ни одной страницы Hello. " + "; ".join(errors[:3]))

    # Keep old entries if the catalogue temporarily hides them or a page parser fails.
    by_id = {v["id"]: v for v in existing if v.get("provider") != "Hello"}
    for v in existing:
        if v.get("provider") == "Hello":
            by_id[v["id"]] = v
    for v in scraped:
        by_id[v["id"]] = v
    result = list(by_id.values())
    result.sort(key=lambda v: (0 if v.get("provider") == "Anytime" else 1, v.get("model", "").casefold(), v.get("id", "")))
    return result, errors


def parse_anytime_public_page(url: str, html: str) -> dict:
    soup, text = clean_text(html)
    h1 = soup.find("h1")
    model = h1.get_text(" ", strip=True) if h1 else ""
    model = re.sub(r"\s+в каршеринге Минска$", "", model, flags=re.I).strip()
    if not model:
        raise ParseError("Не найдено название модели Anytime")

    # CarSync's summary line provides the published minute rate.
    move_match = re.search(r"Минута аренды\s*([\d.,]+)\s*рубля", text, re.I)
    if not move_match:
        move_match = re.search(r"Минута аренды\s*([\d.,]+)\s*BYN", text, re.I)
    move = number(move_match.group(1)) if move_match else None

    # The tariff row exposes both minute values; map the value that differs from
    # the summary movement rate to parking. This is only a secondary-source signal.
    rate_row = re.search(
        r"Минута аренды\s*([\d.,]+)\s*BYN\s+за минуту стоянки\s*([\d.,]+)\s*BYN",
        text,
        re.I,
    )
    park = None
    if rate_row and move is not None:
        first, second = number(rate_row.group(1)), number(rate_row.group(2))
        if abs(first - move) < 0.0001 and abs(second - move) >= 0.0001:
            park = second
        elif abs(second - move) < 0.0001 and abs(first - move) >= 0.0001:
            park = first

    tariffs_start = text.find(f"Тарифы {model}")
    tariff_text = text[tariffs_start:] if tariffs_start >= 0 else text
    specials = {}
    package_specs = [
        ("2h", r"2\s*часа\s+[\d.,]+\s*BYN\s+за минуту\s+([\d.,]+)\s*BYN"),
        ("24h", r"1\s*сут(?:ки|ок)?\s+[\d.,]+\s*BYN\s+за минуту\s+([\d.,]+)\s*BYN"),
        ("48h", r"2\s*сут(?:ок|ки)?\s+[\d.,]+\s*BYN\s+за минуту\s+([\d.,]+)\s*BYN"),
    ]
    for key, pattern in package_specs:
        match = re.search(pattern, tariff_text, re.I)
        if match:
            specials[key] = number(match.group(1))

    return {
        "model": model,
        "url": url,
        "move": move,
        "park": park,
        "specials": specials,
    }


def discover_anytime_urls(html: str) -> list[str]:
    soup, _ = clean_text(html)
    urls = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        path = urlparse(href).path if urlparse(href).scheme else href.split("?", 1)[0]
        if "/carsharings/anytime/models/" not in path:
            continue
        full = urljoin(ANYTIME_CATALOG, href)
        if full not in seen:
            seen.add(full)
            urls.append(full)
    return urls


def scrape_anytime_watch(existing: list[dict]) -> dict:
    catalog_html = fetch_html(ANYTIME_CATALOG)
    urls = discover_anytime_urls(catalog_html)
    if not urls:
        raise ParseError("Каталог CarSync не вернул ссылки на модели Anytime")

    known = [v for v in existing if v.get("provider") == "Anytime"]
    known_by_model = {re.sub(r"\s+", " ", v.get("model", "")).casefold(): v for v in known}
    models = []
    pending = []
    for url in urls:
        try:
            candidate = parse_anytime_public_page(url, fetch_html(url))
            current = known_by_model.get(re.sub(r"\s+", " ", candidate["model"]).casefold())
            candidate["status"] = "known_model" if current else "new_model_candidate"
            candidate["comparison"] = {}
            if current:
                for field in ("move", "park"):
                    new_value = candidate.get(field)
                    old_value = current.get(field)
                    if new_value is not None and old_value is not None:
                        candidate["comparison"][field] = {
                            "calculator": old_value,
                            "public_source": new_value,
                            "differs": abs(float(old_value) - float(new_value)) > 0.0001,
                        }
                for key, new_price in candidate.get("specials", {}).items():
                    old_special = current.get("specials", {}).get(key)
                    if old_special and old_special.get("price") is not None:
                        candidate["comparison"][f"specials.{key}.price"] = {
                            "calculator": old_special["price"],
                            "public_source": new_price,
                            "differs": abs(float(old_special["price"]) - float(new_price)) > 0.0001,
                        }
                if any(x.get("differs") for x in candidate["comparison"].values()):
                    pending.append({"model": candidate["model"], "reason": "Расхождение со снимком приложения; нужна ручная проверка", "url": url})
            else:
                pending.append({"model": candidate["model"], "reason": "Новая модель обнаружена, но полной матрицы тарифов для калькулятора нет", "url": url})
            models.append(candidate)
        except Exception as exc:
            pending.append({"url": url, "reason": f"Не удалось разобрать страницу: {exc}"})

    models.sort(key=lambda x: x["model"].casefold())
    pending.sort(key=lambda x: x.get("model", x.get("url", "")).casefold())
    return {
        "schemaVersion": 1,
        "source": "CarSync — независимый справочник, не официальный источник Anytime",
        "sourceUrl": ANYTIME_CATALOG,
        "note": "Эти значения используются только для обнаружения изменений. Они не заменяют тарифную матрицу из приложения и не подставляются в калькулятор автоматически.",
        "models": models,
        "pendingReview": pending,
    }


def deep_merge(base: dict, patch: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def validate_anytime_vehicle(v: dict) -> None:
    required = [
        "id", "provider", "model", "move", "park", "freeBooking", "hourBases",
        "hourKms", "hourKmRate", "customExcessMin", "customExcessKm", "specials",
        "specialKm", "specialExcessDrive", "specialExcessPark", "day0", "dayExact", "dayKms",
    ]
    missing = [key for key in required if key not in v]
    if missing:
        raise ParseError(f"Неполная ручная запись Anytime {v.get('id', '?')}: отсутствуют {missing}")
    if v.get("provider") != "Anytime":
        raise ParseError(f"Ручная запись {v.get('id')} должна иметь provider=Anytime")
    if not isinstance(v.get("hourBases"), dict) or not isinstance(v.get("hourKms"), dict):
        raise ParseError(f"Неверная структура часовых тарифов: {v.get('id')}")


def apply_manual_anytime(vehicles: list[dict]) -> tuple[list[dict], bool]:
    if not MANUAL_PATH.exists():
        return vehicles, False
    manual = json.loads(MANUAL_PATH.read_text(encoding="utf-8"))
    patches = manual.get("vehicles", {})
    if not isinstance(patches, dict):
        raise ParseError("data/anytime_manual.json: поле vehicles должно быть объектом")

    result = copy.deepcopy(vehicles)
    by_id = {v["id"]: i for i, v in enumerate(result)}
    changed = False
    for vehicle_id, patch in patches.items():
        if not isinstance(patch, dict):
            raise ParseError(f"Ручное обновление {vehicle_id} должно быть объектом")
        patch = copy.deepcopy(patch)
        patch.setdefault("id", vehicle_id)
        if vehicle_id in by_id:
            merged = deep_merge(result[by_id[vehicle_id]], patch)
            validate_anytime_vehicle(merged)
            if merged != result[by_id[vehicle_id]]:
                result[by_id[vehicle_id]] = merged
                changed = True
        else:
            validate_anytime_vehicle(patch)
            result.append(patch)
            by_id[vehicle_id] = len(result) - 1
            changed = True
    return result, changed


def load_json(path: Path, default):
    if not path.exists():
        return copy.deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_if_changed(path: Path, data) -> bool:
    serialized = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == serialized:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")
    return True


def main() -> int:
    if not TARIFFS_PATH.exists():
        print("ERROR: tariffs.json не найден", file=sys.stderr)
        return 1
    data = json.loads(TARIFFS_PATH.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != 1 or not isinstance(data.get("vehicles"), list):
        print("ERROR: неизвестная структура tariffs.json", file=sys.stderr)
        return 1

    original_vehicles = copy.deepcopy(data["vehicles"])
    vehicles = copy.deepcopy(data["vehicles"])
    hello_errors: list[str] = []
    try:
        vehicles, hello_errors = scrape_hello(vehicles)
        print(f"Hello: разобрано {sum(1 for v in vehicles if v.get('provider') == 'Hello')} моделей; ошибок страниц: {len(hello_errors)}")
    except Exception as exc:
        print(f"WARNING: Hello не обновлён: {exc}")

    try:
        vehicles, manual_changed = apply_manual_anytime(vehicles)
    except Exception as exc:
        print(f"ERROR: ручное обновление Anytime не применено: {exc}", file=sys.stderr)
        return 1

    watch_changed = False
    try:
        watch = scrape_anytime_watch(vehicles)
        watch_changed = write_json_if_changed(WATCH_PATH, watch)
        print(f"Anytime: проверено публичных моделей {len(watch['models'])}; кандидатов на ручную проверку: {len(watch['pendingReview'])}")
    except Exception as exc:
        print(f"WARNING: публичная проверка Anytime не выполнена: {exc}")

    data_changed = vehicles != original_vehicles
    if data_changed:
        data["vehicles"] = vehicles
        data.setdefault("meta", {})["dataUpdatedAt"] = date_stamp()
        data["meta"].setdefault("providers", {}).setdefault("hello", {})["mode"] = "official_daily_scrape"
        data["meta"].setdefault("providers", {}).setdefault("anytime", {})["mode"] = "hybrid"
        write_json_if_changed(TARIFFS_PATH, data)
        print(f"tariffs.json обновлён: {date_stamp()}")
    else:
        print("tariffs.json: подтверждённых изменений нет; текущие цены сохранены")

    if watch_changed:
        print("anytime_watch.json: сохранены новые/изменившиеся публичные сигналы")
    if hello_errors:
        print("Hello: страницы, требующие проверки:")
        for error in hello_errors[:20]:
            print(" - " + error)
    if not data_changed and not watch_changed and not manual_changed:
        print("Итог: без изменений; ежедневная проверка завершена без уведомлений и коммитов.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())