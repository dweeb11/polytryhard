import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "staging_soak_snapshot.py"
    spec = importlib.util.spec_from_file_location("staging_soak_snapshot", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


snapshot_script = _load_script()
cents = snapshot_script.cents
render_snapshot = snapshot_script.render_snapshot


def test_cents_formats_none_and_values() -> None:
    assert cents(None) == "$0.00"
    assert cents(12345) == "$123.45"


def test_render_snapshot_includes_operational_sections() -> None:
    output = render_snapshot(
        {
            "captured_at": "2026-06-04T00:00:00+00:00",
            "health": {
                "status": "ok",
                "dbShared": "ok",
                "dbPerEnv": "ok",
                "schedulerCycle": {"status": "ok", "lastSuccessAt": "2026-06-04T00:00:00Z"},
            },
            "sources": [
                {
                    "name": "kalshi_markets",
                    "enabled": True,
                    "status": "ok",
                    "lastSuccessAt": "2026-06-04T00:00:00Z",
                    "rowsLastRun": 10,
                    "lastError": None,
                }
            ],
            "strategies": [
                {
                    "name": "weather_ensemble_disagreement",
                    "state": "active",
                    "bankrollCents": 25000,
                    "bankrollHwmCents": 25000,
                    "kellyFraction": 0.25,
                }
            ],
            "signals": [
                {
                    "strategyName": "weather_ensemble_disagreement",
                    "outcome": "order_placed",
                },
                {
                    "strategyName": "weather_ensemble_disagreement",
                    "outcome": "rejected_stale_inputs",
                },
            ],
            "positions": [
                {
                    "strategyName": "weather_ensemble_disagreement",
                    "status": "open",
                    "realizedPnlCents": None,
                    "unrealizedPnlCents": 125,
                }
            ],
            "cash_events": {
                "weather_ensemble_disagreement": [
                    {
                        "kind": "deposit",
                        "amountCents": 25000,
                        "balanceAfterCents": 25000,
                    }
                ]
            },
            "eval_roster": [
                {
                    "strategyName": "weather_ensemble_disagreement",
                    "nTrades": 1,
                    "hitRate": 1.0,
                    "brierScore": 0.1,
                    "pnlCents": 125,
                    "posteriorEdgeCiLow": -0.02,
                }
            ],
        }
    )

    assert "Health" in output
    assert "Sources" in output
    assert "Signals (latest 2)" in output
    assert "Positions (latest 1)" in output
    assert "Recent cash events" in output
    assert "Eval roster" in output
    assert "weather_ensemble_disagreement" in output
    assert "order_placed" in output
    assert "$250.00" in output
