from src.services.naturka_parser import parse_naturka
from tests.conftest import REPORT


def on_railway(client, railway_id):
    """Ordinal numbers of the vagons standing on a railway, in order."""
    r = client.get(f"/railways/{railway_id}")
    assert r.status_code == 200, r.text
    return [v["order_number"] for v in r.json()["vagons"]]


def arrive(client, yard):
    r = client.post(
        "/trains/arrive",
        json={"entrance_railway_id": yard["entrance"], "report": REPORT},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_parse_report():
    train = parse_naturka(REPORT)
    assert train.sent_station == 7200
    assert train.train_number == 2058
    assert train.assigned_id == "6980 583 7200"
    assert (train.date.day, train.date.month) == (21, 10)
    assert (train.date.hour, train.date.minute) == (9, 48)
    assert (train.length, train.weight, train.tosish) == (66, 5097, 6)
    assert len(train.vagons) == 8
    first, last = train.vagons[0], train.vagons[-1]
    assert (first.order_number, first.vagon_number) == (1, 29265592)
    assert (first.product_weight, first.given_station) == (67, 72000)
    assert (first.product_type, first.target_station) == (52101, 9008)
    assert (first.ban, first.count_plomba) == (5, 2)
    assert last.extra_data == "000'OXPAHA"
    assert train.vagons[5].extra_data == "000'ПEPECЛ"


def test_parse_marked_report():
    # Marked-up variant: an extra sorting-mark column before the ordinal.
    text = (
        "(:02 7200 2028 6980 595 7200 1 21 10 16 06 049 04079 6 0000 0 0\n"
        "28,5    01 62177712 0201 068 72343  32416 9999 0 0 6 0 00/00 00000  000'OXP\n"
        "НАЗ     02 29310083 0201 067 72223  12202 9999 0 0 5 4 00/00 00000  000'OXP\n"
        "-       03 28053056 0271 068 72000  04302 0308 0 0 6 2 00/00 00000  000'OXPCKO:)\n"
    )
    train = parse_naturka(text)
    assert [v.vagon_number for v in train.vagons] == [62177712, 29310083, 28053056]


def test_full_flow(client, yard):
    train = arrive(client, yard)
    ids = {v["order_number"]: v["id"] for v in train["vagons"]}
    assert on_railway(client, yard["entrance"]) == [1, 2, 3, 4, 5, 6, 7, 8]

    # Whole train: entrance -> sorting 43.
    r = client.post(
        "/movements",
        json={"from_railway_id": yard["entrance"], "to_railway_id": yard["s43"]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "to_sorting"
    assert on_railway(client, yard["entrance"]) == []
    assert on_railway(client, yard["s43"]) == [1, 2, 3, 4, 5, 6, 7, 8]

    # Any vagons: 43 -> back to the entrance -> 47.
    r = client.post(
        "/movements",
        json={"vagon_ids": [ids[6], ids[2], ids[4]], "to_railway_id": yard["s47"]},
    )
    assert r.status_code == 201, r.text
    move = r.json()
    assert move["kind"] == "shunt"
    assert move["from_railway_id"] == yard["s43"]
    assert move["via_railway_id"] == yard["entrance"]
    assert on_railway(client, yard["s43"]) == [1, 3, 5, 7, 8]
    assert on_railway(client, yard["s47"]) == [2, 4, 6]

    # A second cut is appended behind the first one.
    r = client.post(
        "/movements", json={"vagon_ids": [ids[1]], "to_railway_id": yard["s47"]}
    )
    assert r.status_code == 201, r.text
    assert on_railway(client, yard["s47"]) == [2, 4, 6, 1]

    # Sorted vagons: 47 -> departure 23.
    r = client.post(
        "/movements",
        json={"from_railway_id": yard["s47"], "to_railway_id": yard["departure"]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "to_departure"
    assert on_railway(client, yard["departure"]) == [2, 4, 6, 1]
    assert on_railway(client, yard["s47"]) == []

    kinds = [m["kind"] for m in client.get("/movements").json()]
    assert kinds == ["arrival", "to_sorting", "shunt", "shunt", "to_departure"]


def test_connecting_route(client, yard):
    arrive(client, yard)
    for src, dst, kind in [
        ("entrance", "connecting", "to_connecting"),
        ("connecting", "departure", "to_departure"),
    ]:
        r = client.post(
            "/movements",
            json={"from_railway_id": yard[src], "to_railway_id": yard[dst]},
        )
        assert r.status_code == 201, r.text
        assert r.json()["kind"] == kind
    assert len(on_railway(client, yard["departure"])) == 8


def test_rejected_movements(client, yard):
    train = arrive(client, yard)
    ids = {v["order_number"]: v["id"] for v in train["vagons"]}

    def move(**body):
        return client.post("/movements", json=body)

    # Entrance cannot go straight to departure.
    r = move(from_railway_id=yard["entrance"], to_railway_id=yard["departure"])
    assert r.status_code == 409, r.text

    # Train must arrive on an entrance railway.
    r = client.post(
        "/trains/arrive", json={"entrance_railway_id": yard["s43"], "report": REPORT}
    )
    assert r.status_code == 409, r.text

    assert move(vagon_ids=[ids[1]], to_railway_id=yard["s43"]).status_code == 201
    # Vagons standing on different railways cannot move together.
    r = move(vagon_ids=[ids[1], ids[2]], to_railway_id=yard["s47"])
    assert r.status_code == 409, r.text
    # Sorting cannot connect to the connecting railway; departure is final.
    r = move(vagon_ids=[ids[1]], to_railway_id=yard["connecting"])
    assert r.status_code == 409, r.text
    # The pull-back railway must be an entrance railway.
    r = move(
        vagon_ids=[ids[1]], to_railway_id=yard["s47"], via_railway_id=yard["departure"]
    )
    assert r.status_code == 409, r.text
    # Nothing was moved by the rejected requests.
    assert on_railway(client, yard["s43"]) == [1]

    assert move(vagon_ids=[999], to_railway_id=yard["s47"]).status_code == 404
    assert move(to_railway_id=yard["s47"]).status_code == 409
    r = client.post("/railways", json={"code": "43", "length": 70, "type": 2})
    assert r.status_code == 409, r.text
    r = client.post(
        "/trains/arrive",
        json={"entrance_railway_id": yard["entrance"], "report": "garbage"},
    )
    assert r.status_code == 422, r.text
