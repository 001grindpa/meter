# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from genlayer import *


HTTPS = "https://"
MAX_PAGE_CHARS = 12000
MIN_TEXT_CHARS = 2
RELEASE_GRACE_DAYS = 1
ZERO = Address("0x0000000000000000000000000000000000000000")

ALLOWED_HOSTS = (
    "coinmarketcap.com",
    "www.coinmarketcap.com",
    "coingecko.com",
    "www.coingecko.com",
    "coindesk.com",
    "www.coindesk.com",
    "cointelegraph.com",
    "www.cointelegraph.com",
    "reuters.com",
    "www.reuters.com",
    "apnews.com",
    "www.apnews.com",
    "bbc.com",
    "www.bbc.com",
    "github.com",
    "www.github.com",
    "gitlab.com",
    "www.gitlab.com",
    "status.coinbase.com",
    "www.coinbase.com",
    "coinbase.com",
)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _host_allowed(url: str) -> bool:
    host = _host(url)
    if not host:
        return False
    for allowed in ALLOWED_HOSTS:
        base = allowed[4:] if allowed.startswith("www.") else allowed
        if host == allowed or host == base or host.endswith("." + base):
            return True
    return False


def _require_https_url(url: str, label: str) -> str:
    cleaned = url.strip()
    if not cleaned.lower().startswith(HTTPS):
        raise gl.vm.UserError(f"{label} must be an https url")
    if not _host_allowed(cleaned):
        raise gl.vm.UserError(f"{label} host is not on the rate allowlist")
    return cleaned


def _require_date(value: str, label: str) -> str:
    cleaned = value.strip()
    try:
        datetime.strptime(cleaned, "%Y-%m-%d")
    except ValueError:
        raise gl.vm.UserError(label + " must be a real calendar date YYYY-MM-DD")
    return cleaned


def _add_days(day: str, days: int) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@gl.evm.contract_interface
class _Wallet:
    class View:
        pass

    class Write:
        pass


def _pay(to: Address, amount: u256) -> None:
    if amount == 0:
        return
    if to == ZERO:
        raise gl.vm.UserError("cannot pay the zero address")
    _Wallet(to).emit_transfer(value=amount)


@allow_storage
@dataclass
class Position:
    borrower: Address
    lender: Address
    asset: str
    threshold: str
    window_start: str
    window_end: str
    release_after: str
    rate_url_a: str
    rate_url_b: str
    collateral: u256
    status: str
    verdict: str
    funds_disposition: str


class Meter(gl.Contract):
    positions: TreeMap[str, Position]
    next_id: u256
    reserved_collateral: u256

    def __init__(self):
        self.next_id = u256(1)
        self.reserved_collateral = u256(0)

    def _id(self) -> str:
        return str(int(self.next_id))

    def _get(self, position_id: str) -> Position:
        if position_id not in self.positions:
            raise gl.vm.UserError("position not found")
        return self.positions[position_id]

    def _extract_page(self, url: str, asset: str, threshold: str, window_start: str, window_end: str) -> dict:
        failed = {"related": False, "window_match": False, "breach": False, "answer": "UNKNOWN"}
        try:
            raw = gl.nondet.web.render(url, mode="text")
            page_text = raw if isinstance(raw, str) else str(raw)
            page_text = page_text[:MAX_PAGE_CHARS]
        except Exception:
            return failed
        prompt = f"""
Decide whether one public rate page shows a threshold breach for an asset inside a date window.

Asset: {asset}
Threshold: {threshold}
Window: {window_start} to {window_end}
Source URL: {url}

Page text:
{page_text}

Return JSON only:
{{
  "related": true or false,
  "window_match": true or false,
  "breach": true or false,
  "answer": "BREACH" or "SAFE" or "UNKNOWN"
}}
Rules:
- related is true only if the page quotes this asset.
- window_match is true only if the quoted print falls inside the window.
- breach is true only if the printed rate is through the threshold in the stated direction.
- answer is BREACH only if related, window_match, and breach.
- answer is SAFE if the page is related, in-window, and clearly not through the threshold.
- UNKNOWN if the page is off-asset, undated, or inconclusive.
"""
        try:
            parsed = gl.nondet.exec_prompt(prompt, response_format="json")
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
        except Exception:
            return failed
        answer = str(parsed.get("answer", "UNKNOWN")).upper()
        if answer not in ("BREACH", "SAFE", "UNKNOWN"):
            answer = "UNKNOWN"
        related = bool(parsed.get("related", False))
        window_match = bool(parsed.get("window_match", False))
        breach = bool(parsed.get("breach", False))
        if not related or not window_match:
            answer = "UNKNOWN"
            breach = False
        if answer == "BREACH" and not breach:
            answer = "UNKNOWN"
        return {
            "related": related,
            "window_match": window_match,
            "breach": breach,
            "answer": answer,
        }

    def _decision(self, item: Position) -> dict:
        try:
            page_a = self._extract_page(
                item.rate_url_a, item.asset, item.threshold, item.window_start, item.window_end
            )
            page_b = self._extract_page(
                item.rate_url_b, item.asset, item.threshold, item.window_start, item.window_end
            )
        except Exception:
            return {"verdict": "UNKNOWN"}
        if (
            page_a["answer"] == "UNKNOWN"
            or page_b["answer"] == "UNKNOWN"
            or not page_a["window_match"]
            or not page_b["window_match"]
        ):
            verdict = "UNKNOWN"
        elif page_a["answer"] != page_b["answer"]:
            verdict = "DISAGREE"
        else:
            verdict = page_a["answer"]
        return {"verdict": verdict}

    def _adjudicate(self, item: Position) -> dict:
        def leader_fn() -> str:
            return json.dumps(self._decision(item), sort_keys=True, separators=(",", ":"))

        def validator_fn(leader_result) -> bool:
            payload = leader_result
            if hasattr(leader_result, "calldata"):
                payload = leader_result.calldata
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode("utf-8", errors="replace")
            if not isinstance(payload, str):
                payload = str(payload)
            try:
                leader = json.loads(payload)
            except Exception:
                return False
            own = self._decision(item)
            return own.get("verdict") == str(leader.get("verdict", "")).upper()

        try:
            raw = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        except Exception:
            return {"verdict": "UNKNOWN"}
        try:
            if isinstance(raw, str):
                return json.loads(raw)
            if hasattr(raw, "calldata"):
                data = raw.calldata
                return json.loads(data if isinstance(data, str) else str(data))
            return json.loads(str(raw))
        except Exception:
            return {"verdict": "UNKNOWN"}

    @gl.public.write.payable
    def open_position(
        self,
        lender: str,
        asset: str,
        threshold: str,
        window_start: str,
        window_end: str,
        rate_url_a: str,
        rate_url_b: str,
    ) -> str:
        if len(asset.strip()) < MIN_TEXT_CHARS or len(threshold.strip()) < MIN_TEXT_CHARS:
            raise gl.vm.UserError("asset and threshold are required")
        window_start = _require_date(window_start, "window_start")
        window_end = _require_date(window_end, "window_end")
        if window_end < window_start:
            raise gl.vm.UserError("window_end must be on or after window_start")
        lender_addr = Address(lender)
        if lender_addr == ZERO:
            raise gl.vm.UserError("lender is required")
        if lender_addr == gl.message.sender_address:
            raise gl.vm.UserError("borrower and lender must be different")
        url_a = _require_https_url(rate_url_a, "rate_url_a")
        url_b = _require_https_url(rate_url_b, "rate_url_b")
        if _host(url_a) == _host(url_b):
            raise gl.vm.UserError("rate sources must come from two different hosts")
        collateral = gl.message.value
        if collateral == u256(0):
            raise gl.vm.UserError("collateral must be greater than zero")
        position_id = self._id()
        self.positions[position_id] = Position(
            borrower=gl.message.sender_address,
            lender=lender_addr,
            asset=asset.strip(),
            threshold=threshold.strip(),
            window_start=window_start,
            window_end=window_end,
            release_after=_add_days(window_end, RELEASE_GRACE_DAYS),
            rate_url_a=url_a,
            rate_url_b=url_b,
            collateral=collateral,
            status="LOCKED",
            verdict="UNRESOLVED",
            funds_disposition="RESERVED",
        )
        self.next_id = self.next_id + u256(1)
        self.reserved_collateral = self.reserved_collateral + collateral
        return position_id

    @gl.public.write
    def liquidate(self, position_id: str) -> str:
        item = self._get(position_id)
        if item.status != "LOCKED":
            raise gl.vm.UserError("position is not locked")
        today = _today_utc()
        if today < item.window_end:
            raise gl.vm.UserError("liquidation cannot open before " + item.window_end)
        if today >= item.release_after:
            raise gl.vm.UserError("liquidation window has closed")
        result = self._adjudicate(item)
        verdict = str(result.get("verdict", "UNKNOWN")).upper()
        if verdict == "BREACH":
            collateral = item.collateral
            lender = item.lender
            item.status = "LIQUIDATED"
            item.verdict = "BREACH"
            item.funds_disposition = "PAID_TO_LENDER"
            self.reserved_collateral = self.reserved_collateral - collateral
            self.positions[position_id] = item
            _pay(lender, collateral)
        else:
            item.verdict = verdict if verdict in ("SAFE", "UNKNOWN", "DISAGREE") else "UNKNOWN"
            self.positions[position_id] = item
        return self.positions[position_id].status

    @gl.public.write
    def release(self, position_id: str) -> None:
        item = self._get(position_id)
        if item.status != "LOCKED":
            raise gl.vm.UserError("collateral is not releasable")
        if _today_utc() < item.release_after:
            raise gl.vm.UserError("collateral cannot release before " + item.release_after)
        collateral = item.collateral
        borrower = item.borrower
        item.status = "RELEASED"
        item.funds_disposition = "RETURNED_TO_BORROWER"
        self.reserved_collateral = self.reserved_collateral - collateral
        self.positions[position_id] = item
        _pay(borrower, collateral)

    @gl.public.view
    def get_position(self, position_id: str) -> str:
        item = self._get(position_id)
        return json.dumps(
            {
                "borrower": item.borrower.as_hex,
                "lender": item.lender.as_hex,
                "asset": item.asset,
                "threshold": item.threshold,
                "window_start": item.window_start,
                "window_end": item.window_end,
                "release_after": item.release_after,
                "rate_url_a": item.rate_url_a,
                "rate_url_b": item.rate_url_b,
                "collateral": str(int(item.collateral)),
                "status": item.status,
                "verdict": item.verdict,
                "funds_disposition": item.funds_disposition,
            },
            sort_keys=True,
        )

    @gl.public.view
    def get_position_count(self) -> str:
        return str(int(self.next_id) - 1)

    @gl.public.view
    def get_reserved_collateral(self) -> str:
        return str(int(self.reserved_collateral))