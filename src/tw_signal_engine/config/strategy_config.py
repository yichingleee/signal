"""Validated strategy configuration models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

TradeMode = Literal["long", "short"]


class SignalAConfig(BaseModel):
    enabled: bool = False
    vwap_near_ratio: float = 1.005
    short_vwap_near_ratio: float = 0.993
    bounce_ratio: float = 0.006
    entry_start_time: int = 92000000000
    entry_end_time: int = 110000000000
    pre_condition_start_time: int = 91500000000
    pre_condition_vwap_ratio: float = 0.993
    short_pre_condition_vwap_ratio: float = 1.007
    trade_zone_max_increase_ratio: float = 0.085
    max_near_to_entry_us: int = 0  # converted from seconds


class SignalBConfig(BaseModel):
    enabled: bool = False
    vol_contract_ratio: float = 0.0
    rolling_low_duration_us: float = 0.0
    rolling_sum_short_duration_us: float = 0.0
    rolling_sum_long_duration_us: float = 0.0
    pre_condition_vwap_ratio: float = 0.0
    track_zone_vwap_ratio: float = 0.0
    track_zone_day_high_ratio: float = 0.0
    buffer_zone_duration_us: int = 0
    buffer_zone_exit_price_ratio: float = 0.0
    buffer_zone_rolling_low_increase_ratio: float = 0.0
    trade_zone_duration_us: int = 0
    trade_zone_eval_price_ratio: float = 0.0
    trade_zone_eval_tick_add: int = 0
    trade_zone_eval_day_high_increase_ratio: float = 0.0
    trade_zone_exit_tick_sub: int = 0
    pre_condition_start_time: int = 0
    buffer_zone_start_time: int = 0
    buffer_zone_end_time: int = 0
    trade_zone_start_time: int = 0


class StrongGroupConfig(BaseModel):
    enabled: bool = False
    member_min_month_trading_val: int = 0
    group_min_month_trading_val: int = 0
    group_min_avg_pct_chg: float = 0.0
    group_min_val_ratio: float = 0.0
    member_strong_vol_ratio: float = 0.0
    member_strong_trading_val: int = 0
    top_group_rank_threshold: int = 0
    top_group_max_select: int = 0
    top_group_min_select: int = 0
    normal_group_max_select: int = 0
    normal_group_min_select: int = 0
    member_vwap_pct_chg_threshold: float = 0.0
    group_valid_top_n: int = 0
    is_weighted_avg: bool = False
    group_vol_ratio_exempt_threshold: int = 0
    filter_prev_day_limit_up: bool = True
    exclude_prev_limit_up_from_rank: bool = False
    exclude_disposition_from_rank: bool = True
    member_cond1_enabled: bool = True
    member_cond2_enabled: bool = True
    member_cond4_enabled: bool = True
    entry_min_vwap_pct_chg: float = 0.0
    entry_max_vwap_pct_chg: float = 0.0
    entry_min_group_rank: int = 0
    require_raw_m1: bool = False
    block_disposition_entry: bool = True
    entry_max_vol_ratio: float = 0.0
    entry_min_month_trading_val: int = 0


class StrongSingleConfig(BaseModel):
    enabled: bool = False
    monitor_pool_size: int = 200
    min_month_trading_val: int = 0
    price_amplitude_threshold: float = 0.0
    day_high_increase_threshold: float = 0.0
    vol_increase_month_ratio: float = 0.0
    vol_increase_yesterday_ratio: float = 0.0
    strong_month_trading_val: int = 0
    vwap_floor_start_time: int = 0
    vwap_floor_ratio: float = 0.0
    extreme_price_increase_limit: float = 0.0


class ExecutionConfig(BaseModel):
    position_cash: float = 10_000_000.0
    disposition_stocks_enabled: bool = False
    filter_prev_day_limit_up: bool = True
    stop_loss_ratio_a: float = 0.997
    stop_loss_ratio_b: float = 0.997
    bailout_ratio: float = 0.985
    max_entry_price: float = 0.0
    no_entry_friday: bool = False
    max_0050_entry_chg: float = 0.0
    max_0050_intra_chg: float = 99.0
    position_scale_nth: float = 1.0
    entry_time_limit: int = 130_000_000_000
    exit_time_limit: int = 132_500_000_000
    take_profit_splits: int = 5
    take_profit_tick_offsets: list[int] = [-1, 0, 1, 2, 3]
    take_profit_pcts: list[float] = []
    reserve_limit_up_splits: int = 0
    tp_base_entry: bool = True
    # Cost model (default 0 = no costs)
    commission_rate: float = 0.0
    tax_rate: float = 0.0
    slippage_bps: float = 0.0


class StrategyGlobalConfig(BaseModel):
    trade_mode: TradeMode = "long"
    market_rally_disable_threshold: float = 0.02
    market_open_min_chg: float = 0.0
    single_group_rank_filter: bool = True
    single_max_member_rank: int = 1


class LiveConfig(BaseModel):
    enabled: bool = False
    redis_host: str = "192.168.100.130"
    redis_port: int = 6379
    redis_db: int = 0
    socket_timeout: int = 5
    reconnect_delay: float = 5.0
    reorder_buffer_ms: int = 100


class NormalizedStrategyConfig(BaseModel):
    """Top-level config container, produced by normalize_strategy_config."""

    strategy: StrategyGlobalConfig = StrategyGlobalConfig()
    signal_a: SignalAConfig = SignalAConfig()
    signal_b: SignalBConfig = SignalBConfig()
    strong_group: StrongGroupConfig = StrongGroupConfig()
    strong_single: StrongSingleConfig = StrongSingleConfig()
    execution: ExecutionConfig = ExecutionConfig()
    live: LiveConfig = LiveConfig()
