from core.domain.strategy import (
    DEFAULT_CONFIDENCE_FLOOR,
    DEFAULT_CORRELATION_CAP_PCT,
    DEFAULT_DISAGREEMENT_THRESHOLD,
    DEFAULT_EXPOSURE_CAP_PCT,
    DEFAULT_MAX_DISAGREEMENT_F,
    DEFAULT_MIN_EDGE,
    DEFAULT_SPREAD_MARGIN_MULTIPLIER,
    DEFAULT_WIDE_SPREAD_THRESHOLD,
    WEATHER_ENSEMBLE_DISAGREEMENT,
    WEATHER_STALE_QUOTE,
    effective_strategy_config,
)


def _baseline_config() -> dict[str, object]:
    return {
        "min_bankroll_cents": 10_000,
        "min_tradeable_bankroll_cents": 5_000,
        "max_drawdown_pct_from_hwm": 30,
        "auto_resume_on_deposit": True,
        "max_input_age_seconds": 900,
    }


def test_effective_strategy_config_applies_universal_defaults() -> None:
    config = effective_strategy_config(
        _baseline_config(),
        strategy_name=WEATHER_ENSEMBLE_DISAGREEMENT,
    )
    assert config.confidence_floor == DEFAULT_CONFIDENCE_FLOOR
    assert config.exposure_cap_pct == DEFAULT_EXPOSURE_CAP_PCT
    assert config.correlation_cap_pct == DEFAULT_CORRELATION_CAP_PCT


def test_effective_strategy_config_applies_ensemble_defaults() -> None:
    config = effective_strategy_config(
        _baseline_config(),
        strategy_name=WEATHER_ENSEMBLE_DISAGREEMENT,
    )
    assert config.disagreement_threshold == DEFAULT_DISAGREEMENT_THRESHOLD
    assert config.spread_margin_multiplier == DEFAULT_SPREAD_MARGIN_MULTIPLIER
    assert config.wide_spread_threshold is None


def test_effective_strategy_config_applies_stale_quote_defaults() -> None:
    config = effective_strategy_config(
        _baseline_config(),
        strategy_name=WEATHER_STALE_QUOTE,
    )
    assert config.wide_spread_threshold == DEFAULT_WIDE_SPREAD_THRESHOLD
    assert config.disagreement_threshold is None
    assert config.spread_margin_multiplier is None


def test_effective_strategy_config_applies_min_edge_and_max_disagreement_defaults() -> None:
    ensemble_config = effective_strategy_config(
        _baseline_config(),
        strategy_name=WEATHER_ENSEMBLE_DISAGREEMENT,
    )
    assert ensemble_config.min_edge == DEFAULT_MIN_EDGE
    assert ensemble_config.max_disagreement_f == DEFAULT_MAX_DISAGREEMENT_F

    stale_quote_config = effective_strategy_config(
        _baseline_config(),
        strategy_name=WEATHER_STALE_QUOTE,
    )
    assert stale_quote_config.min_edge == DEFAULT_MIN_EDGE
    assert stale_quote_config.max_disagreement_f is None


def test_effective_strategy_config_preserves_explicit_values() -> None:
    raw = {
        **_baseline_config(),
        "confidenceFloor": 0.7,
        "exposureCapPct": 0.10,
        "correlationCapPct": 0.05,
        "disagreementThreshold": 3.0,
    }
    config = effective_strategy_config(raw, strategy_name=WEATHER_ENSEMBLE_DISAGREEMENT)
    assert config.confidence_floor == 0.7
    assert config.exposure_cap_pct == 0.10
    assert config.correlation_cap_pct == 0.05
    assert config.disagreement_threshold == 3.0
