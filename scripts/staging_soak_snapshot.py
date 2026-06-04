#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DEFAULT_API_BASE_URL = "https://api.staging-event-market.critterhaus.net"


@dataclass(frozen=True)
class ApiClient:
    base_url: str
    token: str

    def get(self, path: str, params: dict[str, str] | None = None) -> Any:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"{self.base_url.rstrip('/')}{path}{query}"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.token}"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))


def cents(value: int | float | None) -> str:
    return f"${((value or 0) / 100):,.2f}"


def pct(value: int | float | None) -> str:
    return "-" if value is None else f"{float(value) * 100:.1f}%"


def _count_by(rows: list[dict[str, Any]], key: str) -> Counter[str]:
    return Counter(str(row.get(key) or "-") for row in rows)


def _sum_by(rows: list[dict[str, Any]], group_key: str, value_key: str) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for row in rows:
        totals[str(row.get(group_key) or "-")] += int(row.get(value_key) or 0)
    return dict(totals)


def fetch_snapshot(client: ApiClient) -> dict[str, Any]:
    health = client.get("/healthz")
    sources = client.get("/v1/sources")
    strategies = client.get("/v1/strategies")
    signals = client.get("/v1/signals", {"limit": "200"})
    positions = client.get("/v1/positions", {"limit": "200"})
    eval_roster = client.get("/v1/eval")
    cash_events = {
        strategy["name"]: client.get(
            f"/v1/strategies/{urllib.parse.quote(strategy['name'])}/cash-events",
            {"limit": "20"},
        )
        for strategy in strategies
    }
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "health": health,
        "sources": sources,
        "strategies": strategies,
        "signals": signals,
        "positions": positions,
        "eval_roster": eval_roster,
        "cash_events": cash_events,
    }


def render_snapshot(snapshot: dict[str, Any]) -> str:
    health = snapshot["health"]
    sources = snapshot["sources"]
    strategies = snapshot["strategies"]
    signals = snapshot["signals"]
    positions = snapshot["positions"]
    eval_roster = snapshot["eval_roster"]
    cash_events = snapshot["cash_events"]

    lines = [
        f"M6 staging soak snapshot @ {snapshot['captured_at']}",
        "",
        "Health",
        f"- API: {health.get('status')} shared_db={health.get('dbShared')} "
        f"per_env_db={health.get('dbPerEnv')}",
    ]
    scheduler = health.get("schedulerCycle")
    if scheduler:
        lines.append(
            f"- Scheduler: {scheduler.get('status')} last_success={scheduler.get('lastSuccessAt')}"
        )

    lines.extend(["", "Sources"])
    for source in sources:
        lines.append(
            f"- {source.get('name')}: enabled={source.get('enabled')} "
            f"status={source.get('status')} last_success={source.get('lastSuccessAt')} "
            f"rows={source.get('rowsLastRun')} error={source.get('lastError') or '-'}"
        )

    lines.extend(["", "Strategies"])
    for strategy in strategies:
        lines.append(
            f"- {strategy.get('name')}: state={strategy.get('state')} "
            f"bankroll={cents(strategy.get('bankrollCents'))} "
            f"hwm={cents(strategy.get('bankrollHwmCents'))} "
            f"kelly={pct(strategy.get('kellyFraction'))}"
        )

    signal_by_strategy = _count_by(signals, "strategyName")
    signal_by_outcome = _count_by(signals, "outcome")
    lines.extend(["", f"Signals (latest {len(signals)})"])
    lines.append(f"- By strategy: {dict(signal_by_strategy)}")
    lines.append(f"- By outcome: {dict(signal_by_outcome)}")

    open_positions = [row for row in positions if row.get("status") == "open"]
    realized_by_strategy = _sum_by(positions, "strategyName", "realizedPnlCents")
    unrealized_by_strategy = _sum_by(open_positions, "strategyName", "unrealizedPnlCents")
    lines.extend(["", f"Positions (latest {len(positions)})"])
    lines.append(f"- Open: {len(open_positions)}")
    lines.append(f"- Realized P&L by strategy: {realized_by_strategy}")
    lines.append(f"- Unrealized P&L by strategy: {unrealized_by_strategy}")

    lines.extend(["", "Recent cash events"])
    for strategy_name, events in cash_events.items():
        latest = events[0] if events else None
        latest_text = (
            f"{latest.get('kind')} {cents(latest.get('amountCents'))} "
            f"balance={cents(latest.get('balanceAfterCents'))}"
            if latest
            else "-"
        )
        lines.append(f"- {strategy_name}: count={len(events)} latest={latest_text}")

    lines.extend(["", "Eval roster"])
    for row in eval_roster:
        lines.append(
            f"- {row.get('strategyName')}: trades={row.get('nTrades')} "
            f"hit_rate={pct(row.get('hitRate'))} brier={row.get('brierScore')} "
            f"pnl={cents(row.get('pnlCents'))} edge_ci_low={row.get('posteriorEdgeCiLow')}"
        )

    return "\n".join(lines)


def _client_from_env() -> ApiClient:
    token = os.environ.get("SOAK_API_TOKEN") or os.environ.get("CONTROL_PLANE_TOKEN")
    if not token:
        raise RuntimeError("Set SOAK_API_TOKEN or CONTROL_PLANE_TOKEN")
    return ApiClient(
        base_url=os.environ.get("SOAK_API_BASE_URL", DEFAULT_API_BASE_URL),
        token=token,
    )


def main() -> int:
    try:
        print(render_snapshot(fetch_snapshot(_client_from_env())))
    except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"snapshot failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
