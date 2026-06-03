from enum import StrEnum


class StrategyState(StrEnum):
    SEEDED = "seeded"
    ACTIVE = "active"
    LOW_BANKROLL_PAUSED = "low_bankroll_paused"
    DRAWDOWN_PAUSED = "drawdown_paused"
    OPERATOR_PAUSED = "operator_paused"
    DECOMMISSIONED = "decommissioned"


class SystemState(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


class PositionSide(StrEnum):
    YES = "yes"
    NO = "no"


class PositionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    RESOLVED = "resolved"


class CashEventKind(StrEnum):
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    REALIZED_PNL = "realized_pnl"
    FEE = "fee"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"


class EvalWindow(StrEnum):
    D7 = "7d"
    D30 = "30d"
    ALL = "all"


class SignalOutcome(StrEnum):
    ORDER_PLACED = "order_placed"
    REJECTED_KELLY_ZERO = "rejected_kelly_zero"
    REJECTED_EXPOSURE_CAP = "rejected_exposure_cap"
    REJECTED_CORRELATION_CAP = "rejected_correlation_cap"
    REJECTED_BELOW_THRESHOLD = "rejected_below_threshold"
    REJECTED_BELOW_MIN_POSITION = "rejected_below_min_position"
    REJECTED_MARKET_CLOSED = "rejected_market_closed"
    REJECTED_STALE_INPUTS = "rejected_stale_inputs"
    REJECTED_SYSTEM_PAUSED = "rejected_system_paused"
