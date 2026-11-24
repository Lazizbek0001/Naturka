"""Справочник ЖД станций с сайта alta.ru/railway: дороги и станции дороги (код ЕСР + название).

Код станции в натурке — первые 4 цифры кода ЕСР (5-я цифра — контрольная): Бекабад ЕСР 72610 → 7261.
"""
import html
import re
import time
import urllib.request

BASE = "https://www.alta.ru/railway/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Naturka/1.0"
TTL = 6 * 3600
_cache: dict[str, tuple[float, object]] = {}


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ru"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def _cached(key: str, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s)).strip().replace("''", '"')


def roads() -> list[dict]:
    """Все дороги: [{code: "73", name: "Узбекская железная дорога"}]."""
    def load():
        page = _get(BASE)
        out, seen = [], set()
        for code, name in re.findall(r'class="pRailway_item"\s+href="/railway/(\d+)/">([^<]+)', page):
            if code not in seen:
                seen.add(code)
                out.append({"code": code, "name": _text(name)})
        if not out:
            raise ValueError("На alta.ru не найден список дорог (сайт изменился?)")
        return out
    return _cached("roads", load)


def road_stations(road: str) -> list[dict]:
    """Станции дороги: [{esr: "72610", code: 7261, name: "Бекабад"}]."""
    if not re.fullmatch(r"\d{1,3}", road):
        raise ValueError("Неверный код дороги")

    def load():
        page = _get(f"{BASE}{road}/")
        by_code: dict[int, dict] = {}
        for esr, name in re.findall(r'href="/railway/station/(\d{5,6})/">([^<]+)', page):
            st = {"esr": esr, "code": int(esr[:4]), "name": _text(name)}
            # у нескольких пунктов могут совпадать первые 4 цифры (74320 Ахунбабаева и 74321 Акбарабад):
            # код натурки — основной станции, у которой код ЕСР оканчивается на 0
            old = by_code.get(st["code"])
            if old is None or (not old["esr"].endswith("0") and esr.endswith("0")):
                by_code[st["code"]] = st
        if not by_code:
            raise ValueError(f"На alta.ru у дороги {road} не найдено станций")
        return sorted(by_code.values(), key=lambda s: s["code"])
    return _cached(f"road:{road}", load)
