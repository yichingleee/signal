"""Convert raw INI dict to validated NormalizedStrategyConfig."""

from __future__ import annotations

from typing import cast

from tw_signal_engine.config.strategy_config import (
    ExecutionConfig,
    LiveConfig,
    NormalizedStrategyConfig,
    SignalAConfig,
    SignalAShortConfig,
    SignalBConfig,
    StrategyGlobalConfig,
    StrongGroupConfig,
    StrongSingleConfig,
    TradeMode,
    validate_execution_split_invariants,
)


def _bool(v: str) -> bool:
    return v.strip().lower() == "true"


def _get(d: dict[str, str], key: str, default: str = "") -> str:
    return d.get(key, default).strip()


def _min_to_us(minutes: float) -> float:
    return minutes * 60 * 1_000_000 + 0.01


def normalize_strategy_config(raw: dict[str, dict[str, str]]) -> NormalizedStrategyConfig:
    """Build a NormalizedStrategyConfig from raw INI sections."""
    strat_raw = raw.get("Strategy", {})
    trade_mode = _get(strat_raw, "trade_mode", "long").lower()
    if trade_mode not in {"long", "short"}:
        raise ValueError(f"Invalid Strategy.trade_mode: {trade_mode}")
    trade_mode_typed = cast(TradeMode, trade_mode)

    strategy = StrategyGlobalConfig(
        trade_mode=trade_mode_typed,
        market_rally_disable_threshold=float(_get(strat_raw, "market_rally_disable_threshold", "0.02")),
        market_open_min_chg=float(_get(strat_raw, "market_open_min_chg", "0.0")),
    )

    # Also read single_group_rank_filter from StrongSignal section
    ss_raw = raw.get("StrongSignal", {})
    if v := _get(ss_raw, "single_group_rank_filter"):
        strategy.single_group_rank_filter = _bool(v)
    if v := _get(ss_raw, "single_max_member_rank"):
        strategy.single_max_member_rank = int(v)

    # SignalA
    sa_raw = raw.get("SignalA", {})
    signal_a = SignalAConfig(
        enabled=_bool(_get(sa_raw, "enabled", "false")),
        vwap_near_ratio=float(_get(sa_raw, "vwap_near_ratio", "1.005")),
        short_vwap_near_ratio=float(_get(sa_raw, "short_vwap_near_ratio", "0.993")),
        bounce_ratio=float(_get(sa_raw, "bounce_ratio", "0.006")),
        entry_start_time=int(_get(sa_raw, "entry_start_time", "92000000000")),
        entry_end_time=int(_get(sa_raw, "entry_end_time", "110000000000")),
        pre_condition_start_time=int(_get(sa_raw, "pre_condition_start_time", "91500000000")),
        pre_condition_vwap_ratio=float(_get(sa_raw, "pre_condition_vwap_ratio", "0.993")),
        short_pre_condition_vwap_ratio=float(_get(sa_raw, "short_pre_condition_vwap_ratio", "1.007")),
        trade_zone_max_increase_ratio=float(_get(sa_raw, "trade_zone_max_increase_ratio", "0.085")),
        max_near_to_entry_us=int(float(_get(sa_raw, "max_near_to_entry_sec", "0")) * 1_000_000),
    )

    # SignalAShort (new independent short signal)
    sas_raw = raw.get("SignalAShort", {})
    signal_a_short = SignalAShortConfig(
        enabled=_bool(_get(sas_raw, "enabled", "false")),
        vwap_near_ratio=float(_get(sas_raw, "vwap_near_ratio", _get(sa_raw, "short_vwap_near_ratio", "0.993"))),
        bounce_ratio=float(_get(sas_raw, "bounce_ratio", _get(sa_raw, "bounce_ratio", "0.006"))),
        entry_start_time=int(_get(sas_raw, "entry_start_time", _get(sa_raw, "entry_start_time", "92000000000"))),
        entry_end_time=int(_get(sas_raw, "entry_end_time", _get(sa_raw, "entry_end_time", "110000000000"))),
        pre_condition_start_time=int(
            _get(sas_raw, "pre_condition_start_time", _get(sa_raw, "pre_condition_start_time", "91500000000"))
        ),
        pre_condition_vwap_ratio=float(
            _get(
                sas_raw,
                "pre_condition_vwap_ratio",
                _get(sa_raw, "short_pre_condition_vwap_ratio", "1.007"),
            )
        ),
        trade_zone_max_increase_ratio=float(
            _get(sas_raw, "trade_zone_max_increase_ratio", _get(sa_raw, "trade_zone_max_increase_ratio", "0.085"))
        ),
        max_near_to_entry_us=int(
            float(_get(sas_raw, "max_near_to_entry_sec", _get(sa_raw, "max_near_to_entry_sec", "0"))) * 1_000_000
        ),
    )

    # SignalB
    sb_raw = raw.get("SignalB", {})
    signal_b = SignalBConfig(
        enabled=_bool(_get(sb_raw, "enabled", "false")),
        supports_short=_bool(_get(sb_raw, "supports_short", "false")),
    )
    if signal_b.enabled:
        signal_b.vol_contract_ratio = float(_get(sb_raw, "vol_contract_ratio", "0"))
        signal_b.rolling_low_duration_us = _min_to_us(float(_get(sb_raw, "ROLLING_LOW_DURATION", "0")))
        signal_b.rolling_sum_short_duration_us = _min_to_us(float(_get(sb_raw, "ROLLING_SUM_SHORT_DURATION", "0")))
        signal_b.rolling_sum_long_duration_us = _min_to_us(float(_get(sb_raw, "ROLLING_SUM_LONG_DURATION", "0")))
        signal_b.pre_condition_vwap_ratio = float(_get(sb_raw, "pre_condition_vwap_ratio", "0"))
        signal_b.track_zone_vwap_ratio = float(_get(sb_raw, "track_zone_vwap_ratio", "0"))
        signal_b.track_zone_day_high_ratio = float(_get(sb_raw, "track_zone_day_high_ratio", "0"))
        signal_b.buffer_zone_duration_us = int(float(_get(sb_raw, "buffer_zone_duration_min", "0")) * 60_000_000)
        signal_b.buffer_zone_exit_price_ratio = float(_get(sb_raw, "buffer_zone_exit_price_ratio", "0"))
        signal_b.buffer_zone_rolling_low_increase_ratio = float(
            _get(sb_raw, "buffer_zone_rolling_low_increase_ratio", "0")
        )
        signal_b.trade_zone_duration_us = int(float(_get(sb_raw, "trade_zone_duration_min", "0")) * 60_000_000)
        signal_b.trade_zone_eval_price_ratio = float(_get(sb_raw, "trade_zone_eval_price_ratio", "0"))
        signal_b.trade_zone_eval_tick_add = int(_get(sb_raw, "trade_zone_eval_tick_add", "0"))
        signal_b.trade_zone_eval_day_high_increase_ratio = float(
            _get(sb_raw, "trade_zone_eval_day_high_increase_ratio", "0")
        )
        signal_b.trade_zone_exit_tick_sub = int(_get(sb_raw, "trade_zone_exit_tick_sub", "0"))
        signal_b.pre_condition_start_time = int(_get(sb_raw, "pre_condition_start_time", "0"))
        signal_b.buffer_zone_start_time = int(_get(sb_raw, "buffer_zone_start_time", "0"))
        signal_b.buffer_zone_end_time = int(_get(sb_raw, "buffer_zone_end_time", "0"))
        signal_b.trade_zone_start_time = int(_get(sb_raw, "trade_zone_start_time", "0"))

    # StrongGroup
    sg_raw = raw.get("StrongGroup", {})
    order_raw = raw.get("Order", {})
    strong_group = StrongGroupConfig(
        enabled=_bool(_get(sg_raw, "enabled", "false")),
        member_min_month_trading_val=int(_get(sg_raw, "member_min_month_trading_val", "0")),
        group_min_month_trading_val=int(_get(sg_raw, "group_min_month_trading_val", "0")),
        group_min_avg_pct_chg=float(_get(sg_raw, "group_min_avg_pct_chg", "0")),
        group_min_val_ratio=float(_get(sg_raw, "group_min_val_ratio", "0")),
        member_strong_vol_ratio=float(_get(sg_raw, "member_strong_vol_ratio", "0")),
        member_strong_trading_val=int(_get(sg_raw, "member_strong_trading_val", "0")),
        top_group_rank_threshold=int(_get(sg_raw, "top_group_rank_threshold", "0")),
        top_group_max_select=int(_get(sg_raw, "top_group_max_select", "0")),
        top_group_min_select=int(_get(sg_raw, "top_group_min_select", "0")),
        normal_group_max_select=int(_get(sg_raw, "normal_group_max_select", "0")),
        normal_group_min_select=int(_get(sg_raw, "normal_group_min_select", "0")),
        member_vwap_pct_chg_threshold=float(_get(sg_raw, "member_vwap_pct_chg_threshold", "0")),
        group_valid_top_n=int(_get(sg_raw, "group_valid_top_n", "0")),
        is_weighted_avg=_bool(_get(sg_raw, "is_weighted_avg", "false")),
        group_vol_ratio_exempt_threshold=int(_get(sg_raw, "group_vol_ratio_exempt_threshold", "0")),
        filter_prev_day_limit_up=_bool(_get(order_raw, "filter_prev_day_limit_up", "true")),
        exclude_prev_limit_up_from_rank=_bool(_get(sg_raw, "exclude_prev_limit_up_from_rank", "false")),
        exclude_disposition_from_rank=_bool(_get(sg_raw, "exclude_disposition_from_rank", "true")),
        member_cond1_enabled=_bool(_get(sg_raw, "member_cond1_enabled", "true")),
        member_cond2_enabled=_bool(_get(sg_raw, "member_cond2_enabled", "true")),
        member_cond4_enabled=_bool(_get(sg_raw, "member_cond4_enabled", "true")),
        entry_min_vwap_pct_chg=float(_get(sg_raw, "entry_min_vwap_pct_chg", "0")),
        entry_max_vwap_pct_chg=float(_get(sg_raw, "entry_max_vwap_pct_chg", "0")),
        entry_min_group_rank=int(_get(sg_raw, "entry_min_group_rank", "0")),
        require_raw_m1=_bool(_get(sg_raw, "require_raw_m1", "false")),
        block_disposition_entry=_bool(_get(sg_raw, "block_disposition_entry", "true")),
        entry_max_vol_ratio=float(_get(sg_raw, "entry_max_vol_ratio", "0")),
        entry_min_month_trading_val=int(_get(sg_raw, "entry_min_month_trading_val", "0")),
    )

    # StrongSingle
    strong_single = StrongSingleConfig(enabled=_bool(_get(ss_raw, "enabled", "false")))
    if strong_single.enabled:
        strong_single.monitor_pool_size = int(_get(ss_raw, "monitor_pool_size", "200"))
        strong_single.min_month_trading_val = int(_get(ss_raw, "min_month_trading_val", "0"))
        strong_single.price_amplitude_threshold = float(_get(ss_raw, "price_amplitude_threshold", "0"))
        strong_single.day_high_increase_threshold = float(_get(ss_raw, "day_high_increase_threshold", "0"))
        strong_single.vol_increase_month_ratio = float(_get(ss_raw, "vol_increase_month_ratio", "0"))
        strong_single.vol_increase_yesterday_ratio = float(_get(ss_raw, "vol_increase_yesterday_ratio", "0"))
        strong_single.strong_month_trading_val = int(_get(ss_raw, "strong_month_trading_val", "0"))
        strong_single.vwap_floor_start_time = int(_get(ss_raw, "vwap_floor_start_time", "0"))
        strong_single.vwap_floor_ratio = float(_get(ss_raw, "vwap_floor_ratio", "0"))
        strong_single.extreme_price_increase_limit = float(_get(ss_raw, "extreme_price_increase_limit", "0"))

    # Execution (Order section)
    tp_offsets = _get(order_raw, "take_profit_tick_offsets", "-1,0,1,2,3")
    tp_pcts_str = _get(order_raw, "take_profit_pcts", "")
    execution = ExecutionConfig(
        position_cash=float(_get(order_raw, "position_cash", "10000000")),
        disposition_stocks_enabled=_bool(_get(order_raw, "disposition_stocks_enabled", "false")),
        filter_prev_day_limit_up=_bool(_get(order_raw, "filter_prev_day_limit_up", "true")),
        stop_loss_ratio_a=float(_get(order_raw, "stop_loss_ratio_a", "0.997")),
        stop_loss_ratio_b=float(_get(order_raw, "stop_loss_ratio_b", "0.997")),
        bailout_ratio=float(_get(order_raw, "bailout_ratio", "0.985")),
        max_entry_price=float(_get(order_raw, "max_entry_price", "0")),
        no_entry_friday=_bool(_get(order_raw, "no_entry_friday", "false")),
        max_0050_entry_chg=float(_get(order_raw, "max_0050_entry_chg", "0")),
        max_0050_intra_chg=float(_get(order_raw, "max_0050_intra_chg", "99")),
        position_scale_nth=float(_get(order_raw, "position_scale_nth", "1.0")),
        entry_time_limit=int(_get(order_raw, "entry_time_limit", "130000000000")),
        exit_time_limit=int(_get(order_raw, "exit_time_limit", "132500000000")),
        take_profit_splits=int(_get(order_raw, "take_profit_splits", "5")),
        take_profit_tick_offsets=[int(x) for x in tp_offsets.split(",") if x.strip()],
        take_profit_pcts=[float(x) for x in tp_pcts_str.split(",") if x.strip()] if tp_pcts_str else [],
        reserve_limit_up_splits=int(_get(order_raw, "reserve_limit_up_splits", "0")),
        tp_base_entry=_bool(_get(order_raw, "tp_base_entry", "true")),
        commission_rate=float(_get(order_raw, "commission_rate", "0")),
        tax_rate=float(_get(order_raw, "tax_rate", "0")),
        slippage_bps=float(_get(order_raw, "slippage_bps", "0")),
    )
    validate_execution_split_invariants(execution)

    # Live config (optional section)
    live_raw = raw.get("Live", {})
    live = LiveConfig(
        enabled=_bool(_get(live_raw, "enabled", "false")),
        redis_host=_get(live_raw, "redis_host", "192.168.100.130") or "192.168.100.130",
        redis_port=int(_get(live_raw, "redis_port", "6379")),
        redis_db=int(_get(live_raw, "redis_db", "0")),
        socket_timeout=int(_get(live_raw, "socket_timeout", "5")),
        reconnect_delay=float(_get(live_raw, "reconnect_delay", "5.0")),
        reorder_buffer_ms=int(_get(live_raw, "reorder_buffer_ms", "100")),
    )

    return NormalizedStrategyConfig(
        strategy=strategy,
        signal_a=signal_a,
        signal_a_short=signal_a_short,
        signal_b=signal_b,
        strong_group=strong_group,
        strong_single=strong_single,
        execution=execution,
        live=live,
    )
