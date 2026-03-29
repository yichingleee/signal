"""Strong single stock screening logic."""

from __future__ import annotations

from tw_signal_engine.config.strategy_config import StrongSingleConfig
from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.screening.top_volume_pool import TopKVolumeTracker
from tw_signal_engine.server.dashboard_snapshot import SingleSnapshot
from tw_signal_engine.state.symbol_state import IndexData

DAY_PER_MONTH = 20


class StrongSingleEvaluator:
    """Evaluate whether a symbol qualifies as strong-single on each tick."""

    def __init__(
        self,
        config: StrongSingleConfig,
        vol_cum: list[LinearVolumeTracker],
        trading_val: list[dict[str, int]],
        f1_map: dict[str, ReferenceSymbol],
    ) -> None:
        self.config = config
        self.vol_cum = vol_cum
        self.trading_val = trading_val
        self.f1_map = f1_map
        self._num_days = DAY_PER_MONTH
        self.top_tracker = TopKVolumeTracker(config.monitor_pool_size)
        self.symbol_is_valid: dict[str, bool] = {}
        self.forbidden: dict[str, bool] = {}
        self._vol_cumu: dict[str, int] = {}
        self._max_price_amp: dict[str, float] = {}
        self._qualified: dict[str, bool] = {}

        # Precomputed month totals (filled during initialize_validity / _is_symbol_valid)
        self._month_total_tv: dict[str, int] = {}
        self._month_avg_tv: dict[str, int] = {}

        # Cached prev_close values
        self._prev_close_cache: dict[str, float] = {}

    def initialize_validity(self, symbols: set[str] | None = None) -> set[str]:
        """Pre-compute monthly-trading-value validity for replay universe construction."""
        candidates = symbols if symbols is not None else set(self.f1_map.keys())
        for symbol in candidates:
            self._is_symbol_valid(symbol)

        # Pre-cache prev_close for all known symbols
        for symbol, ref in self.f1_map.items():
            self._prev_close_cache[symbol] = ref.previous_close * 10000

        return {symbol for symbol, is_valid in self.symbol_is_valid.items() if is_valid}

    def _is_symbol_valid(self, symbol: str) -> bool:
        if symbol not in self.symbol_is_valid:
            total = sum(self.trading_val[i].get(symbol, 0) for i in range(len(self.trading_val)))
            num_days = self._num_days
            avg = total // num_days
            self._month_total_tv[symbol] = total
            self._month_avg_tv[symbol] = avg
            self.symbol_is_valid[symbol] = avg >= self.config.min_month_trading_val
        return self.symbol_is_valid[symbol]

    def on_tick(
        self, idx: IndexData, symbol: str, price: int, qty: int,
        match_time_us: int, match_time_str: int,
    ) -> bool:
        if not self.config.enabled:
            self._qualified[symbol] = False
            return False

        if not self._is_symbol_valid(symbol):
            self._qualified[symbol] = False
            return False

        self._vol_cumu[symbol] = self._vol_cumu.get(symbol, 0) + qty

        self.top_tracker.on_tick(symbol, qty * price)
        in_pool = self.top_tracker.in_pool(symbol)

        cond1 = self._eval_price_cond(idx, symbol, price)
        cond2 = self._eval_vol_cond(idx, symbol, match_time_us)
        cond3 = self._eval_vwap_cond(idx, symbol, price, match_time_str)
        cond4 = self._eval_extreme_filter(symbol, price)

        result = in_pool and cond1 and cond2 and cond3 and cond4
        self._qualified[symbol] = result
        return result

    def _eval_price_cond(self, idx: IndexData, symbol: str, price: int) -> bool:
        if idx.day_low <= 0:
            return False
        price_amp = (idx.day_high - idx.day_low) / idx.day_low
        self._max_price_amp[symbol] = max(price_amp, self._max_price_amp.get(symbol, 0.0))

        prev_close = self._prev_close_cache.get(symbol)
        if prev_close is None:
            ref = self.f1_map.get(symbol)
            if ref is None:
                return False
            prev_close = ref.previous_close * 10000
            self._prev_close_cache[symbol] = prev_close
        if prev_close <= 0:
            return False
        cond2 = (idx.day_high - prev_close) / prev_close > self.config.day_high_increase_threshold
        return cond2  # cond1 is always False in C++

    def _eval_vol_cond(self, idx: IndexData, symbol: str, match_time_us: int) -> bool:
        total_vol = sum(self.vol_cum[i].query(symbol, match_time_us) for i in range(len(self.vol_cum)))
        num_days = self._num_days
        avg = total_vol // num_days if total_vol > 0 else 1

        vol_cumu = self._vol_cumu.get(symbol, 0)
        cond1 = (vol_cumu / avg) >= self.config.vol_increase_month_ratio if avg > 0 else False

        cum_vol_yesterday = self.vol_cum[0].query(symbol, match_time_us) if self.vol_cum else 0
        cond2 = (
            (vol_cumu / cum_vol_yesterday) >= self.config.vol_increase_yesterday_ratio
            if cum_vol_yesterday > 0 else False
        )

        # Use precomputed month total trading value
        total_tv = self._month_total_tv.get(symbol, 0)
        cond3 = total_tv // num_days > self.config.strong_month_trading_val

        return cond1 or cond2 or cond3

    def _eval_vwap_cond(self, idx: IndexData, symbol: str, price: int, match_time_str: int) -> bool:
        if self.forbidden.get(symbol, False):
            return False
        if match_time_str >= self.config.vwap_floor_start_time:
            if price <= idx.vwap * self.config.vwap_floor_ratio:
                self.forbidden[symbol] = True
        return not self.forbidden.get(symbol, False)

    def _eval_extreme_filter(self, symbol: str, price: int) -> bool:
        prev_close = self._prev_close_cache.get(symbol)
        if prev_close is None:
            ref = self.f1_map.get(symbol)
            if ref is None:
                return True
            prev_close = ref.previous_close * 10000
            self._prev_close_cache[symbol] = prev_close
        if prev_close <= 0:
            return True
        pct_chg = (price - prev_close) / prev_close
        return pct_chg < self.config.extreme_price_increase_limit

    def to_snapshot(
        self,
        idx_map: dict[str, IndexData],
        last_price: dict[str, int],
        symbol_to_group: dict[str, str] | None = None,
    ) -> list[SingleSnapshot]:
        """Serialize currently-qualified strong-single symbols for dashboard usage."""
        result: list[SingleSnapshot] = []
        for symbol, qualified in self._qualified.items():
            if not qualified:
                continue
            idx = idx_map.get(symbol)
            if idx is None:
                continue
            ref = self.f1_map.get(symbol)
            if ref is None:
                continue
            prev_close = self._prev_close_cache.get(symbol, ref.previous_close * 10000)
            price_raw = last_price.get(symbol, 0)
            vwap_raw = idx.vwap
            pct_chg = (price_raw - prev_close) / prev_close if prev_close > 0 else 0.0
            vwap_pct_chg = (vwap_raw - prev_close) / prev_close if prev_close > 0 else 0.0
            month_avg = self._month_avg_tv.get(symbol, 0)
            cum_vol_ratio = self._vol_cumu.get(symbol, 0) / (month_avg / 10000) if month_avg > 0 else 0.0
            result.append(
                SingleSnapshot(
                    symbol=symbol,
                    name=ref.name,
                    group_name=(symbol_to_group or {}).get(symbol, ""),
                    price=price_raw / 10000,
                    pct_chg=pct_chg,
                    vwap=vwap_raw / 10000,
                    vwap_pct_chg=vwap_pct_chg,
                    cum_vol_ratio=cum_vol_ratio,
                    vol_shrink_ratio=0.0,
                )
            )

        result.sort(key=lambda s: s.vwap_pct_chg, reverse=True)
        return result
