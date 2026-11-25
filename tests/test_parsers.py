import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from update_tariffs import parse_hello_page, parse_anytime_public_page


def test_parse_hello_page():
    html = '''
    <html><head><link rel="canonical" href="https://hello.by/cars/volkswagen-polo"></head>
    <body><h1>Аренда Volkswagen Polo</h1>
    <div>Я резидент Беларуси Опыт больше 1 года МИНУТЫ
    Действует скидка 37% Стоимость указана с учетом скидки.
    1 мин. — 0.32 BYN 0.51 BYN Стоянка тарифицируется по 0.15 BYN
    МИНУТЫ И КМ 30 мин. — 5.90 BYN 60 мин. — 9.90 BYN 120 мин. — 15.90 BYN
    Каждый км по 0.47 BYN ЧАСЫ И КМ 3 ч. — 19.00 BYN 6 ч. — 29.00 BYN 9 ч. — 39.00 BYN
    Каждый км по 0.47 BYN СУТКИ И КМ 1 сут. — 49.00 BYN 2 сут. — 96.00 BYN
    Каждый км по 0.47 BYN Условия</div></body></html>'''
    result = parse_hello_page("https://hello.by/cars/volkswagen-polo", html, {})
    assert result["model"] == "Volkswagen Polo"
    assert result["move"] == 0.32
    assert result["park"] == 0.15
    assert result["km"] == 0.47
    assert [p["minutes"] for p in result["packages"]] == [30, 60, 120, 180, 360, 540, 1440, 2880]
    assert result["packages"][0]["price"] == 5.90


def test_parse_anytime_public_page():
    html = '''<html><body><h1>Volkswagen Polo в каршеринге Минска</h1>
    <p>Минута аренды 0,33 рубля.</p>
    <h2>Тарифы Volkswagen Polo</h2>
    <p>Минута аренды 0.17 BYN за минуту стоянки 0.33 BYN</p>
    <p>2 часа 0.067 BYN за минуту 7.99 BYN</p>
    <p>1 сутки 0.020 BYN за минуту 28.50 BYN</p>
    <p>2 суток 0.019 BYN за минуту 54.90 BYN</p></body></html>'''
    result = parse_anytime_public_page("https://carsync.by/carsharings/anytime/models/volkswagen-polo", html)
    assert result["model"] == "Volkswagen Polo"
    assert result["move"] == 0.33
    assert result["park"] == 0.17
    assert result["specials"] == {"2h": 7.99, "24h": 28.50, "48h": 54.90}