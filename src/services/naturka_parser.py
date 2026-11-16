"""Parser for the naturka report (message 02).

The first line describes the train, every following line one vagon::

    (:02 7200 2058 6980 583 7200 1 21 10 09 48 066 05097 6 0000 0 0
     01 29265592 0201 067 72000  52101 9008 0 0 5 2 00/00 00000  000'OXP
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from src.db.models.naturka_train import NaturkaTrain
from src.db.models.naturka_vagon import NaturkaVagon


class NaturkaParseError(ValueError):
    pass


_HEADER_RE = re.compile(
    r"\(:\s*02\s+(?P<sent_station>\d+)\s+(?P<train_number>\d+)\s+"
    r"(?P<index>\d+\s+\d+\s+\d+)\s+(?P<condition>\d)\s+"
    r"(?P<day>\d{2})\s+(?P<month>\d{2})\s+(?P<hour>\d{2})\s+(?P<minute>\d{2})\s+"
    r"(?P<length>\d{3})\s+(?P<weight>\d+)\s+(?P<tosish>\d)\s+"
    r"(?P<past>\d)(?P<yon>\d)(?P<tepa>\d)(?P<extra>\d)\s+"
    r"(?P<animal>\d)\s+(?P<extra2>\d)"
)

# Not anchored at the line start: a marked-up report has an extra column
# (sorting mark such as "28,5", "НАЗ", "-") before the ordinal number.
_VAGON_RE = re.compile(
    r"(?<!\S)(?P<order>\d{2})\s+(?P<number>\d{8})\s+(?P<country>\d{4})\s+"
    r"(?P<weight>\d{3})\s+(?P<given>\d{5})\s+(?P<product>\d{5})\s+"
    r"(?P<target>\d{4})\s+(?P<condition>\d)\s+(?P<importance>\d)\s+"
    r"(?P<ban>\d)\s+(?P<plomba>\d)\s+(?P<cont_loaded>\d{2})/(?P<cont_empty>\d{2})\s+"
    r"(?P<through>\d{5})\s+(?P<extra>\d{3}'.*)$"
)


def _report_date(day: int, month: int, hour: int, minute: int) -> datetime:
    """The report carries no year: take the most recent matching date."""
    now = datetime.now(timezone.utc)
    try:
        date = datetime(now.year, month, day, hour, minute, tzinfo=timezone.utc)
        if date > now + timedelta(days=1):
            date = date.replace(year=now.year - 1)
    except ValueError as exc:
        raise NaturkaParseError(f"invalid date in report header: {exc}") from exc
    return date


def parse_naturka(text: str) -> NaturkaTrain:
    """Build a NaturkaTrain with its vagons (not yet added to a session)."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    header = next(
        (m for m in (_HEADER_RE.search(line) for line in lines) if m), None
    )
    if header is None:
        raise NaturkaParseError("report header '(:02 ...' not found")

    h = header.groupdict()
    train = NaturkaTrain(
        sent_station=int(h["sent_station"]),
        train_number=int(h["train_number"]),
        assigned_id=" ".join(h["index"].split()),
        train_condition=int(h["condition"]),
        date=_report_date(
            int(h["day"]), int(h["month"]), int(h["hour"]), int(h["minute"])
        ),
        length=int(h["length"]),
        weight=int(h["weight"]),
        tosish=int(h["tosish"]),
        tepa=int(h["tepa"]),
        yon=int(h["yon"]),
        past=int(h["past"]),
        animal=int(h["animal"]),
        extra=h["extra"],
        extra2=h["extra2"],
    )

    for line in lines:
        if line.endswith(":)"):
            line = line[:-2].rstrip()
        m = _VAGON_RE.search(line)
        if m is None:
            continue
        v = m.groupdict()
        train.vagons.append(
            NaturkaVagon(
                order_number=int(v["order"]),
                vagon_number=int(v["number"]),
                vagoon_country=int(v["country"]),
                product_weight=int(v["weight"]),
                given_station=int(v["given"]),
                product_type=int(v["product"]),
                target_station=int(v["target"]),
                vagon_condition=int(v["condition"]),
                product_importance=int(v["importance"]),
                ban=int(v["ban"]),
                count_plomba=int(v["plomba"]),
                count_container=int(v["cont_loaded"]) + int(v["cont_empty"]),
                through_station=int(v["through"]),
                extra_data=v["extra"].strip(),
                date=train.date,
            )
        )

    if not train.vagons:
        raise NaturkaParseError("report contains no vagon lines")
    orders = [vagon.order_number for vagon in train.vagons]
    if len(set(orders)) != len(orders):
        raise NaturkaParseError("report contains duplicate vagon ordinal numbers")
    return train
