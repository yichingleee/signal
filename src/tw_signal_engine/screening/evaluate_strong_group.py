"""Strong group screening logic - ported from strongGroup.cpp."""

from __future__ import annotations

from dataclasses import dataclass

from tw_signal_engine.config.strategy_config import StrongGroupConfig, TradeMode
from tw_signal_engine.market_data.market_data_records import LinearVolumeTracker
from tw_signal_engine.records.reference_records import ReferenceSymbol
from tw_signal_engine.server.dashboard_snapshot import GroupSnapshot, MemberSnapshot
from tw_signal_engine.state.group_state import GroupRank
from tw_signal_engine.state.symbol_state import IndexData

DAY_PER_MONTH = 20  # Max prior sessions in history window


@dataclass(slots=True)
class MatchInfo:
    group_name: str = ""
    group_rank: int = 0
    member_rank: int = 0
    raw_member_rank: int = 0
    m1_symbol: str = ""
    vol_ratio: float = 0.0
    month_trading_val: int = 0


class StrongGroupEvaluator:
    """Evaluate strong-group qualification on each tick."""

    def __init__(
        self,
        config: StrongGroupConfig,
        symbol_to_groups: dict[str, list[str]],
        group_members: dict[str, set[str]],
        vol_cum: list[LinearVolumeTracker],
        trading_val: list[dict[str, int]],
        f1_map: dict[str, ReferenceSymbol],
        prev_day_limit_up: dict[str, bool],
        trade_mode: TradeMode = "long",
        circuit_breaker_symbols: set[str] | None = None,
    ) -> None:
        self.config = config
        self.symbol_to_groups = symbol_to_groups
        self.group_members = group_members
        self.vol_cum = vol_cum
        self.trading_val = trading_val
        self.f1_map = f1_map
        self.prev_day_limit_up = prev_day_limit_up
        self.trade_mode = trade_mode
        self._num_days = DAY_PER_MONTH

        # Pre-computed data
        self.symbol_is_valid: dict[str, bool] = {}
        self.trading_value_month_avg: dict[str, int] = {}
        self.group_trading_value_month_avg_sum: dict[str, int] = {}
        self.group_member_count: dict[str, int] = {}

        # Precomputed month totals (filled during initialize_validity)
        self._month_total_tv: dict[str, int] = {}
        self._month_avg_tv: dict[str, int] = {}

        # Cached prev_close values (filled on first access)
        self._prev_close_cache: dict[str, float] = {}

        # Runtime state
        self.trading_value_cumu: dict[str, int] = {}
        self.group_trading_value_cumu: dict[str, int] = {}
        self.price_last: dict[str, int] = {}
        self.vol_cumu: dict[str, int] = {}

        # Rankings
        self.group_rank = GroupRank()
        self.group_member_vwap_rank: dict[str, GroupRank] = {}
        self.group_member_raw_vwap_rank: dict[str, GroupRank] = {}

        # Match info for reporting
        self.last_match_info: dict[str, MatchInfo] = {}

    @property
    def _is_short(self) -> bool:
        return self.trade_mode == "short"

    def _ranking_score(self, value: float) -> float:
        return -value if self._is_short else value

    def _vwap_rank_upper_bound(self) -> float:
        if self.config.entry_max_vwap_pct_chg > 0:
            return self.config.entry_max_vwap_pct_chg
        return 0.085

    def initialize_validity(self) -> None:
        """Pre-compute which symbols are valid based on month avg trading val.

        Also precomputes month-total trading value per symbol for O(1) lookup in on_tick.
        """
        num_days = self._num_days
        for group, members in self.group_members.items():
            for symbol in members:
                if symbol not in self.symbol_is_valid:
                    total = sum(self.trading_val[i].get(symbol, 0) for i in range(len(self.trading_val)))
                    avg = total // num_days
                    self._month_total_tv[symbol] = total
                    self._month_avg_tv[symbol] = avg
                    self.trading_value_month_avg[symbol] = avg
                    self.symbol_is_valid[symbol] = avg >= self.config.member_min_month_trading_val

                if self.symbol_is_valid[symbol]:
                    self.group_trading_value_month_avg_sum[group] = (
                        self.group_trading_value_month_avg_sum.get(group, 0) + self.trading_value_month_avg[symbol]
                    )
                    self.group_member_count[group] = self.group_member_count.get(group, 0) + 1

        # Pre-cache prev_close for all known symbols
        for symbol, ref in self.f1_map.items():
            self._prev_close_cache[symbol] = ref.previous_close * 10000

    def _percentage_chg(self, symbol: str, price: int) -> float:
        prev_close = self._prev_close_cache.get(symbol)
        if prev_close is None:
            ref = self.f1_map.get(symbol)
            if ref is None:
                return 0.0
            prev_close = ref.previous_close * 10000
            self._prev_close_cache[symbol] = prev_close
        if prev_close <= 0:
            return 0.0
        return (price - prev_close) / prev_close

    def _group_percentage_chg(self, group: str, weighted_avg: bool) -> float:
        avg_pct = 0.0
        members = self.group_members.get(group, set())
        for symbol in members:
            if weighted_avg:
                group_tv = self.group_trading_value_cumu.get(group, 0)
                ratio = self.trading_value_cumu.get(symbol, 0) / group_tv if group_tv > 0 else 0.0
            else:
                count = self.group_member_count.get(group, 1)
                ratio = 1.0 / count if count > 0 else 0.0

            pct = 0.0
            if symbol in self.price_last:
                pct = self._percentage_chg(symbol, self.price_last[symbol])
            avg_pct += pct * ratio
        return avg_pct

    def _eval_group_validity(self, symbol: str, group: str, group_avg_pct: float) -> bool:
        cond1 = self.trading_value_month_avg.get(symbol, 0) >= self.config.member_min_month_trading_val
        cond2 = self.group_trading_value_month_avg_sum.get(group, 0) >= self.config.group_min_month_trading_val
        if self._is_short:
            cond3 = group_avg_pct < -self.config.group_min_avg_pct_chg
        else:
            cond3 = group_avg_pct > self.config.group_min_avg_pct_chg

        group_tv_cumu = self.group_trading_value_cumu.get(group, 0)
        group_tv_month = self.group_trading_value_month_avg_sum.get(group, 1)
        val_ratio = group_tv_cumu / group_tv_month if group_tv_month > 0 else 0.0
        cond4 = val_ratio > self.config.group_min_val_ratio

        return cond1 and cond2 and cond3 and cond4

    def _monthly_volume_average(self, symbol: str, match_time_us: int) -> int:
        total_vol = sum(self.vol_cum[i].query(symbol, match_time_us) for i in range(len(self.vol_cum)))
        return total_vol // self._num_days if total_vol > 0 else 1

    def on_tick(
        self,
        idx: IndexData,
        symbol: str,
        price: int,
        qty: int,
        match_time_us: int,
        match_time_str: int,
        is_limit_up_locked: bool,
    ) -> bool:
        """Process one tick. Returns True if symbol qualifies as strong-group."""
        if symbol not in self.symbol_to_groups or not self.symbol_is_valid.get(symbol, False):
            return False

        # Raw VWAP rank (minimal filter)
        raw_vwap_pct = self._percentage_chg(symbol, int(idx.vwap))
        upper_bound = self._vwap_rank_upper_bound()
        if self._is_short:
            raw_rank_allowed = not is_limit_up_locked and raw_vwap_pct > -upper_bound
        else:
            raw_rank_allowed = not is_limit_up_locked and raw_vwap_pct < upper_bound
        if raw_rank_allowed:
            for group in self.symbol_to_groups[symbol]:
                if group not in self.group_member_raw_vwap_rank:
                    self.group_member_raw_vwap_rank[group] = GroupRank()
                self.group_member_raw_vwap_rank[group].on_tick(symbol, self._ranking_score(raw_vwap_pct))
        else:
            for group in self.symbol_to_groups[symbol]:
                if group in self.group_member_raw_vwap_rank:
                    self.group_member_raw_vwap_rank[group].erase(symbol)

        is_prev_day_lu = self.config.filter_prev_day_limit_up and self.prev_day_limit_up.get(symbol, False)

        # Update cumulative values
        tv = price * qty
        self.trading_value_cumu[symbol] = self.trading_value_cumu.get(symbol, 0) + tv
        for group in self.symbol_to_groups[symbol]:
            self.group_trading_value_cumu[group] = self.group_trading_value_cumu.get(group, 0) + tv
        self.price_last[symbol] = price
        self.vol_cumu[symbol] = self.vol_cumu.get(symbol, 0) + qty

        vwap_pct = self._percentage_chg(symbol, int(idx.vwap))
        price_pct = self._percentage_chg(symbol, price)

        ans = False
        num_days = self._num_days
        for group in self.symbol_to_groups[symbol]:
            g_pct = self._group_percentage_chg(group, self.config.is_weighted_avg)
            if not self._eval_group_validity(symbol, group, g_pct):
                continue

            self.group_rank.on_tick(group, self._ranking_score(g_pct))

            if not self.group_rank.is_top_n(group, self.config.group_valid_top_n):
                continue

            total_tv = self._month_total_tv.get(symbol, 0)
            vol_cumu = self.vol_cumu.get(symbol, 0)
            group_monthly_tv_ok = total_tv // num_days > self.config.member_strong_trading_val

            group_vol_exempt = (
                self.group_trading_value_month_avg_sum.get(group, 0) > self.config.group_vol_ratio_exempt_threshold
            )
            need_volume_avg_for_filters = (
                self.config.member_cond1_enabled
                and not group_vol_exempt
                and not group_monthly_tv_ok
            )
            avg = None
            if need_volume_avg_for_filters:
                avg = self._monthly_volume_average(symbol, match_time_us)
            cond1 = (
                not self.config.member_cond1_enabled
                or group_vol_exempt
                or group_monthly_tv_ok
                or (
                    vol_cumu / avg >= self.config.member_strong_vol_ratio
                    if avg is not None and avg > 0
                    else False
                )
            )
            if self._is_short:
                cond2 = not self.config.member_cond2_enabled or (price_pct < -0.02 and vwap_pct < -0.01)
            else:
                cond2 = not self.config.member_cond2_enabled or (price_pct > 0.02 and vwap_pct > 0.01)
            member_vwap_chg = self._percentage_chg(symbol, int(idx.vwap))
            if self._is_short:
                cond4 = (
                    not self.config.member_cond4_enabled
                    or member_vwap_chg < -self.config.member_vwap_pct_chg_threshold
                )
            else:
                cond4 = (
                    not self.config.member_cond4_enabled
                    or member_vwap_chg > self.config.member_vwap_pct_chg_threshold
                )

            ref = self.f1_map.get(symbol)
            is_disposition = ref is not None and ref.security == "RR"
            exclude_disp = is_disposition and self.config.exclude_disposition_from_rank
            exclude_prev_lu = is_prev_day_lu and self.config.exclude_prev_limit_up_from_rank

            if group not in self.group_member_vwap_rank:
                self.group_member_vwap_rank[group] = GroupRank()

            if self._is_short:
                outside_trade_zone = vwap_pct <= -upper_bound
            else:
                outside_trade_zone = vwap_pct >= upper_bound
            if is_limit_up_locked or exclude_disp or outside_trade_zone or exclude_prev_lu:
                self.group_member_vwap_rank[group].erase(symbol)
            elif cond1 and cond2 and cond4:
                self.group_member_vwap_rank[group].on_tick(symbol, self._ranking_score(vwap_pct))

                max_chosen = (
                    self.config.top_group_max_select
                    if self.group_rank.is_top_n(group, self.config.top_group_rank_threshold)
                    else self.config.normal_group_max_select
                )

                cnt = 0
                block_disp = self.config.block_disposition_entry and is_disposition
                for _rank_score, member_sym in self.group_member_vwap_rank[group].iter_ranked():
                    cnt += 1
                    if member_sym == symbol and not is_prev_day_lu and not block_disp and not ans:
                        if self._is_short:
                            result = vwap_pct <= -self.config.entry_min_vwap_pct_chg
                            if (
                                self.config.entry_max_vwap_pct_chg > 0
                                and vwap_pct < -self.config.entry_max_vwap_pct_chg
                            ):
                                result = False
                        else:
                            result = vwap_pct >= self.config.entry_min_vwap_pct_chg
                            if self.config.entry_max_vwap_pct_chg > 0 and vwap_pct > self.config.entry_max_vwap_pct_chg:
                                result = False
                        gr = self.group_rank.get_rank(group)
                        if self.config.entry_min_group_rank > 0 and gr < self.config.entry_min_group_rank:
                            result = False
                        raw_rank = -1
                        if group in self.group_member_raw_vwap_rank:
                            raw_rank = self.group_member_raw_vwap_rank[group].get_rank(symbol)
                        if self.config.require_raw_m1 and raw_rank != 1:
                            result = False
                        ans = result

                        if self.config.entry_max_vol_ratio > 0 and avg is None:
                            avg = self._monthly_volume_average(symbol, match_time_us)
                        vr = vol_cumu / avg if avg is not None and avg > 0 else 0.0
                        if self.config.entry_max_vol_ratio > 0 and vr >= self.config.entry_max_vol_ratio:
                            result = False
                            ans = False

                        should_update = (
                            symbol not in self.last_match_info
                            or self.last_match_info[symbol].member_rank == 0
                            or ans
                            or gr < self.last_match_info[symbol].group_rank
                        )
                        if should_update and avg is None:
                            avg = self._monthly_volume_average(symbol, match_time_us)
                            vr = vol_cumu / avg if avg > 0 else 0.0

                        # Update match info
                        if should_update:
                            ranked = self.group_member_vwap_rank[group].iter_ranked()
                            m1 = ranked[0][1] if ranked else ""
                            mtv = total_tv // num_days
                            self.last_match_info[symbol] = MatchInfo(
                                group_name=group,
                                group_rank=gr,
                                member_rank=cnt,
                                raw_member_rank=raw_rank,
                                m1_symbol=m1,
                                vol_ratio=vr,
                                month_trading_val=mtv,
                            )

                    if cnt >= max_chosen:
                        break
            else:
                self.group_member_vwap_rank[group].erase(symbol)

        return ans

    def get_group_limit_up_count(self, group: str) -> int:
        members = self.group_members.get(group, set())
        count = 0
        for sym in members:
            if sym not in self.price_last:
                continue
            ref = self.f1_map.get(sym)
            if ref is None:
                continue
            limit_up = int(ref.limit_up_price * 10000 + 0.5)
            if limit_up > 0 and self.price_last[sym] >= limit_up:
                count += 1
        return count

    def to_snapshot(self, idx_map: dict[str, IndexData]) -> list[GroupSnapshot]:
        """Serialize current group rankings and members to dashboard format."""
        result: list[GroupSnapshot] = []
        for _gain, group_name in self.group_rank.iter_ranked():
            members_ranked = self.group_member_vwap_rank.get(group_name)
            if members_ranked is None:
                continue

            member_snapshots: list[MemberSnapshot] = []
            for rank_idx, (vwap_pct, sym) in enumerate(
                members_ranked.iter_ranked(), 1
            ):
                actual_vwap_pct = -vwap_pct if self._is_short else vwap_pct
                ref = self.f1_map.get(sym)
                name = ref.name if ref else sym
                price_raw = self.price_last.get(sym, 0)
                idx = idx_map.get(sym)
                vwap_raw = idx.vwap if idx else 0.0

                vol_cumu = self.vol_cumu.get(sym, 0)
                month_avg = self._month_avg_tv.get(sym, 0)
                cum_vol_ratio = (
                    vol_cumu / (month_avg / 10000) if month_avg > 0 else 0.0
                )

                member_snapshots.append(
                    MemberSnapshot(
                        symbol=sym,
                        name=name,
                        price=price_raw / 10000,
                        pct_chg=self._percentage_chg(sym, price_raw),
                        vwap=vwap_raw / 10000,
                        vwap_pct_chg=actual_vwap_pct,
                        cum_vol_ratio=cum_vol_ratio,
                        vol_shrink_ratio=0.0,
                        member_rank=rank_idx,
                    )
                )

            avg_pct = self._group_percentage_chg(
                group_name, self.config.is_weighted_avg
            )
            group_tv_cumu = self.group_trading_value_cumu.get(group_name, 0)
            group_tv_month = self.group_trading_value_month_avg_sum.get(
                group_name, 1
            )
            vol_ratio = (
                group_tv_cumu / group_tv_month if group_tv_month > 0 else 0.0
            )

            result.append(
                GroupSnapshot(
                    group_name=group_name,
                    group_rank=self.group_rank.get_rank(group_name),
                    avg_pct_chg=avg_pct,
                    vol_ratio=vol_ratio,
                    avg_vol_surge=0.0,
                    members=member_snapshots,
                )
            )
        return result

    def is_single_allowed(self, symbol: str, max_rank: int) -> bool:
        """Check if a strong-single symbol is also ranked high enough in its groups."""
        groups = self.symbol_to_groups.get(symbol, [])
        if not groups:
            return True

        has_valid_group = False
        for group in groups:
            if self.group_trading_value_month_avg_sum.get(group, 0) < self.config.group_min_month_trading_val:
                continue
            has_valid_group = True
            raw_rank_map = self.group_member_raw_vwap_rank.get(group)
            if raw_rank_map is not None:
                rank = raw_rank_map.get_rank(symbol)
                if 1 <= rank <= max_rank:
                    gr = self.group_rank.get_rank(group)
                    if gr < 0:
                        gr = 0
                    self.last_match_info[symbol] = MatchInfo(
                        group_name=group, group_rank=gr, raw_member_rank=rank
                    )
                    return True
        return not has_valid_group
