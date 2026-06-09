#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from argparse import ArgumentParser
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

DEFAULT_API_BASE_URL = "https://api.staging-event-market.critterhaus.net"
DEFAULT_NOTES_DIR = Path("docs/operations/soak-notes")
EXPECTED_SOURCES = ("open_meteo", "kalshi_markets", "kalshi_resolution")
Severity = Literal["warning", "intervention"]


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
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.fp is not None:
                body = exc.read().decode("utf-8")
                if body:
                    payload = json.loads(body)
                    if exc.code == 503 and isinstance(payload, dict):
                        return payload
            raise


@dataclass(frozen=True)
class SoakFinding:
    severity: Severity
    code: str
    message: str


@dataclass(frozen=True)
class SoakState:
    source_unhealthy_checks: dict[str, int]


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


def _load_state(path: Path | None) -> SoakState:
    if path is None or not path.exists():
        return SoakState(source_unhealthy_checks={})
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_counts = payload.get("source_unhealthy_checks", {})
    return SoakState(
        source_unhealthy_checks={
            str(name): int(count)
            for name, count in raw_counts.items()
            if isinstance(name, str) and isinstance(count, int | float | str)
        }
    )


def _save_state(path: Path | None, state: SoakState) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"source_unhealthy_checks": state.source_unhealthy_checks},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def update_soak_state(
    snapshot: dict[str, Any],
    previous: SoakState,
    parked_sources: set[str] | None = None,
) -> SoakState:
    parked = parked_sources or set()
    counts = dict(previous.source_unhealthy_checks)
    sources = {str(source.get("name")): source for source in snapshot["sources"]}
    for name in EXPECTED_SOURCES:
        source = sources.get(name)
        is_healthy = (
            name in parked
            or (
                source is not None
                and source.get("enabled") is True
                and source.get("status") == "ok"
            )
        )
        counts[name] = 0 if is_healthy else counts.get(name, 0) + 1
    return SoakState(source_unhealthy_checks=counts)


def evaluate_snapshot(
    snapshot: dict[str, Any],
    state: SoakState | None = None,
    parked_sources: set[str] | None = None,
    paused_strategies: set[str] | None = None,
    max_open_notional_cents: int | None = None,
) -> list[SoakFinding]:
    findings: list[SoakFinding] = []
    parked = parked_sources or set()
    expected_paused = paused_strategies or set()
    counts = state.source_unhealthy_checks if state is not None else {}
    health = snapshot["health"]

    if health.get("status") != "ok":
        findings.append(
            SoakFinding(
                "intervention",
                "api-health",
                f"/healthz status is {health.get('status')!r}; "
                "pause the system if this is unexpected.",
            )
        )

    scheduler = health.get("scheduler_cycle")
    if not scheduler:
        findings.append(
            SoakFinding(
                "warning",
                "scheduler-missing",
                "/healthz did not include scheduler cycle health.",
            )
        )
    elif scheduler.get("status") != "ok":
        findings.append(
            SoakFinding(
                "intervention",
                "scheduler-cycle",
                f"Scheduler cycle status is {scheduler.get('status')!r}.",
            )
        )

    sources = {str(source.get("name")): source for source in snapshot["sources"]}
    for name in EXPECTED_SOURCES:
        if name in parked:
            continue
        source = sources.get(name)
        if source is None:
            findings.append(
                SoakFinding(
                    "intervention",
                    "source-missing",
                    f"{name} is missing from /v1/sources.",
                )
            )
            continue
        if source.get("enabled") is not True:
            findings.append(
                SoakFinding(
                    "intervention",
                    "source-disabled",
                    f"{name} is disabled but expected to be enabled for the soak.",
                )
            )
        if source.get("status") != "ok":
            unhealthy_checks = counts.get(name, 1)
            severity: Severity = "intervention" if unhealthy_checks > 2 else "warning"
            findings.append(
                SoakFinding(
                    severity,
                    "source-unhealthy",
                    f"{name} status is {source.get('status')!r} "
                    f"for {unhealthy_checks} snapshot check(s).",
                )
            )
        if not source.get("lastSuccessAt"):
            findings.append(
                SoakFinding(
                    "warning",
                    "source-no-success",
                    f"{name} has no recorded lastSuccessAt.",
                )
            )

    for strategy in snapshot["strategies"]:
        name = str(strategy.get("name") or "-")
        state_value = strategy.get("state")
        if name not in expected_paused and state_value != "active":
            findings.append(
                SoakFinding(
                    "intervention",
                    "strategy-not-active",
                    f"{name} state is {state_value!r}; strategies should be active unless noted.",
                )
            )

    for signal in snapshot["signals"]:
        outcome = str(signal.get("outcome") or "")
        if "stale" in outcome and not outcome.startswith("rejected"):
            findings.append(
                SoakFinding(
                    "intervention",
                    "stale-input-order",
                    f"{signal.get('strategyName') or '-'} produced stale-input "
                    f"outcome {outcome!r}.",
                )
            )

    if max_open_notional_cents is not None:
        open_positions = [row for row in snapshot["positions"] if row.get("status") == "open"]
        open_notional = sum(int(row.get("costBasisCents") or 0) for row in open_positions)
        if open_notional > max_open_notional_cents:
            findings.append(
                SoakFinding(
                    "intervention",
                    "open-exposure-cap",
                    f"Open paper cost basis {cents(open_notional)} exceeds "
                    f"cap {cents(max_open_notional_cents)}.",
                )
            )

    return findings


def render_findings(findings: list[SoakFinding]) -> str:
    if not findings:
        return "Soak automation checks\n- OK: no warnings or intervention triggers."
    lines = ["Soak automation checks"]
    for finding in findings:
        lines.append(f"- {finding.severity.upper()} [{finding.code}]: {finding.message}")
    return "\n".join(lines)


def write_snapshot_artifacts(
    snapshot: dict[str, Any],
    rendered_snapshot: str,
    findings: list[SoakFinding],
    notes_dir: Path,
) -> tuple[Path, Path]:
    captured_at = str(snapshot["captured_at"])
    note_date = captured_at[:10]
    notes_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = notes_dir / f"{note_date}.md"
    json_path = notes_dir / f"{note_date}-snapshot.json"
    markdown_path.write_text(
        f"{rendered_snapshot}\n\n{render_findings(findings)}\n",
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(
            {
                "snapshot": snapshot,
                "findings": [finding.__dict__ for finding in findings],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return markdown_path, json_path


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
    ]
    if health.get("status") != "ok":
        lines.extend(
            [
                f"*** DEGRADED: API status={health.get('status')} ***",
                "",
            ]
        )
    lines.extend(
        [
            "Health",
            f"- API: {health.get('status')} shared_db={health.get('db_shared')} "
            f"per_env_db={health.get('db_per_env')}",
        ]
    )
    scheduler = health.get("scheduler_cycle")
    if scheduler:
        lines.append(
            f"- Scheduler: {scheduler.get('status')} "
            f"last_success={scheduler.get('last_success_at')}"
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


def _parse_args(argv: list[str] | None) -> Any:
    parser = ArgumentParser(description="Capture and evaluate the M6 staging soak snapshot.")
    parser.add_argument(
        "--write-notes",
        action="store_true",
        help="Write dated Markdown and JSON snapshot artifacts under --notes-dir.",
    )
    parser.add_argument(
        "--notes-dir",
        type=Path,
        default=DEFAULT_NOTES_DIR,
        help=f"Directory for dated soak notes. Defaults to {DEFAULT_NOTES_DIR}.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=None,
        help="Optional JSON state file for repeated-check threshold tracking.",
    )
    parser.add_argument(
        "--parked-source",
        action="append",
        default=[],
        help="Source deliberately parked in soak notes; may be passed more than once.",
    )
    parser.add_argument(
        "--paused-strategy",
        action="append",
        default=[],
        help="Strategy deliberately paused in soak notes; may be passed more than once.",
    )
    parser.add_argument(
        "--max-open-notional-cents",
        type=int,
        default=None,
        help="Fail checks when total open paper position cost basis exceeds this amount.",
    )
    parser.add_argument(
        "--fail-on-intervention",
        action="store_true",
        help="Exit 2 when automation checks find an intervention trigger.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    state_path = args.state_file
    if state_path is None and args.write_notes:
        state_path = args.notes_dir / ".staging-soak-state.json"
    try:
        snapshot = fetch_snapshot(_client_from_env())
        previous_state = _load_state(state_path)
        current_state = update_soak_state(
            snapshot,
            previous_state,
            set(args.parked_source),
        )
        findings = evaluate_snapshot(
            snapshot,
            current_state,
            parked_sources=set(args.parked_source),
            paused_strategies=set(args.paused_strategy),
            max_open_notional_cents=args.max_open_notional_cents,
        )
        rendered_snapshot = render_snapshot(snapshot)
        print(rendered_snapshot)
        print()
        print(render_findings(findings))
        if args.write_notes:
            markdown_path, json_path = write_snapshot_artifacts(
                snapshot,
                rendered_snapshot,
                findings,
                args.notes_dir,
            )
            _save_state(state_path, current_state)
            print()
            print(f"Wrote soak notes: {markdown_path} and {json_path}")
    except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"snapshot failed: {exc}", file=sys.stderr)
        return 1
    if args.fail_on_intervention and any(
        finding.severity == "intervention" for finding in findings
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
