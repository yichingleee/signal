// Mirrors Python dataclasses from server/dashboard_snapshot.py

export interface MemberSnapshot {
  symbol: string
  name: string
  price: number
  pct_chg: number
  vwap: number
  vwap_pct_chg: number
  cum_vol_ratio: number
  vol_shrink_ratio: number
  member_rank: number
}

export interface GroupSnapshot {
  group_name: string
  group_rank: number
  avg_pct_chg: number
  vol_ratio: number
  avg_vol_surge: number
  members: MemberSnapshot[]
}

export interface SingleSnapshot {
  symbol: string
  name: string
  group_name: string
  price: number
  pct_chg: number
  vwap: number
  vwap_pct_chg: number
  cum_vol_ratio: number
  vol_shrink_ratio: number
}

export interface VWAPMonitorEntry {
  symbol: string
  name: string
  group_name: string
  price: number
  vwap: number
  vwap_pct: number
  pv_ratio: number
  signal_a_state: string
  status: string
}

export interface PreparingEntry {
  symbol: string
  name: string
  group_name: string
  group_tag: string
  order_price: number
  current_price: number
  distance_pct: number
  vwap: number
  day_low: number
  stop_loss: number
  near_vwap_pv_ratio: number
  side?: 'long' | 'short'
}

export interface ActivePosition {
  symbol: string
  name: string
  group_name: string
  group_tag: string
  entry_price: number
  current_price: number
  pnl_pct: number
  stop_loss: number
  take_profit: number
  day_high: number
  entry_time: string
  side?: 'long' | 'short'
  qty?: number
}

export interface CompletedTrade {
  symbol: string
  name: string
  group_name: string
  group_tag: string
  entry_price: number
  exit_price: number
  pnl_pct: number
  entry_time: string
  exit_time: string
  exit_cause: string
  side?: 'long' | 'short'
}

export interface SignalCounters {
  qualified: number
  not_qualified: number
  holding: number
  take_profit: number
  stop_loss: number
  forbidden: number
}

export interface SignalAMonitorSnapshot {
  preparing: PreparingEntry[]
  entered: ActivePosition[]
  exited: CompletedTrade[]
  counters: SignalCounters
}

export interface DashboardModuleStatus {
  key: string
  label: string
  availability: 'available' | 'unavailable'
  reason: string
  source_equivalent: string
}

export interface SignalBMonitorEntry {
  symbol: string
  name: string
  group_name: string
  forbidden: boolean
  in_buffer_zone: boolean
  in_trade_zone: boolean
  enter_market: boolean
  rolling_low: number
  rolling_sum_ratio: number
  status: string
}

export interface SignalBMonitorSnapshot {
  rows: SignalBMonitorEntry[]
  buffer_zone: number
  trade_zone: number
  triggered: number
  forbidden: number
}

export interface SignalDayHighMonitorEntry {
  symbol: string
  name: string
  group_name: string
  triggered: boolean
  established_high: number
  established_high_time: string
  pullback_confirmed: boolean
  pullback_low: number
  pullback_time: string
  entries: number
  status: string
}

export interface SignalDayHighMonitorSnapshot {
  rows: SignalDayHighMonitorEntry[]
  preparing: PreparingEntry[]
  entered: ActivePosition[]
  exited: CompletedTrade[]
  counters: SignalCounters
  tracking: number
  pullback: number
  triggered: number
  entries: number
}

export interface DashboardSnapshot {
  timestamp: string
  time_raw: number
  tick_count: number
  groups: GroupSnapshot[]
  singles: SingleSnapshot[]
  vwap_monitor: VWAPMonitorEntry[]
  signal_a: SignalAMonitorSnapshot
  signal_b: SignalBMonitorSnapshot
  signal_day_high: SignalDayHighMonitorSnapshot
  modules: DashboardModuleStatus[]
}

export interface StatusResponse {
  mode: 'live' | 'replay'
  tick_count?: number
  last_time_str?: number
  ready?: boolean
  time_range?: {
    min_time: string
    max_time: string
    count: number
  }
}

export interface ReplayStatusResponse {
  enabled: boolean
  ready: boolean
  time_range?: {
    min_time: string
    max_time: string
    count: number
  }
}
