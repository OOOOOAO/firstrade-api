"""Offline checks for option close codes and device-trust rotation.

Run: python tests/offline.py   (needs requests and pyotp; touches no network)
"""

import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs

import requests
from requests.adapters import BaseAdapter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firstrade import account, order  # noqa: E402


class FakeFirstrade(BaseAdapter):
    """Answers api3x requests from a route table and records them."""

    def __init__(self, routes: dict) -> None:
        super().__init__()
        self.routes = routes
        self.sent: list[requests.PreparedRequest] = []

    def send(self, request, **kwargs):  # noqa: ANN001, ANN003, ANN201, ARG002
        self.sent.append(request)
        resp = requests.Response()
        resp.status_code = 200
        resp._content = json.dumps(self.routes.get((request.method, request.path_url.split("?")[0]), {})).encode()
        resp.headers["Content-Type"] = "application/json"
        resp.url = request.url
        resp.request = request
        return resp

    def close(self) -> None:
        pass


def fake_session(routes: dict, **kwargs: object) -> tuple[account.FTSession, FakeFirstrade]:
    ft = account.FTSession(username="u", password="p", **kwargs)
    fake = FakeFirstrade(routes)
    ft.session.mount("https://", fake)
    return ft, fake


def check_trusted_login_adopts_rotated_ftat() -> None:
    with tempfile.TemporaryDirectory() as d:
        saved = Path(d, "ft_cookiesu.json")
        saved.write_text(json.dumps("OLD"))
        ft, fake = fake_session(
            {("POST", "/sess/login"): {"ftat": "NEW", "sid": "S1", "error": ""}},
            profile_path=d,
            save_session=True,
        )
        assert ft.login() is False
        assert fake.sent[1].headers["ftat"] == "OLD", "saved trust was not presented"
        assert ft.session.headers["ftat"] == "NEW", ft.session.headers["ftat"]
        assert ft.session.headers["sid"] == "S1"
        assert json.loads(saved.read_text()) == "NEW", saved.read_text()


def check_option_transaction_codes() -> None:
    ft, fake = fake_session({("POST", "/private/option_order"): {"error": "", "result": {}}})
    cases = [
        (order.OrderType.BUY_OPTION, "BO"),
        (order.OrderType.SELL_OPTION, "SO"),
        (order.OrderType.SELL_TO_CLOSE, "SC"),
        (order.OrderType.BUY_TO_CLOSE, "BC"),
    ]
    for order_type, code in cases:
        order.Order(ft).place_option_order(
            account="1",
            option_symbol="ABCD260116C00003000",
            price_type=order.PriceType.LIMIT,
            order_type=order_type,
            contracts=1,
            duration=order.Duration.DAY,
            price=0.01,
            dry_run=True,
        )
        sent = parse_qs(fake.sent[-1].body)
        assert sent["transaction"] == [code], (order_type, sent["transaction"])
        assert sent["preview"] == ["true"]


if __name__ == "__main__":
    check_trusted_login_adopts_rotated_ftat()
    check_option_transaction_codes()
    print("ok")
