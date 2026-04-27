import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import { getSocket, disconnectSocket } from '../api/socket'
import type {
  DashboardSnapshot,
  DashboardModuleStatus,
  ReplayStatusResponse,
  SignalAMonitorSnapshot,
  SignalBMonitorSnapshot,
  SignalCounters,
  SignalDayHighEntryRow,
  SignalDayHighExitRow,
  SignalDayHighLogicSnapshot,
  SignalDayHighMonitorSnapshot,
  SignalDayHighMonitorEntry,
  SignalDayHighPhase,
  SignalDayHighSelectionRow,
} from '../types/dashboard'

function hhmmToMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number)
  return h * 60 + m
}

function minutesToHHMM(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`
}

const DEFAULT_MODULES: DashboardModuleStatus[] = [
  { key: 'strong-groups', label: 'Strong Groups', availability: 'available', reason: '', source_equivalent: 'StockScreening strong groups' },
  { key: 'burst-groups', label: 'Burst Groups', availability: 'unavailable', reason: 'This engine has no burst-group evaluator.', source_equivalent: 'StockScreening burst groups' },
  { key: 'intraday-burst', label: 'Intraday Burst Stocks', availability: 'unavailable', reason: 'This engine has no intraday burst-stock evaluator.', source_equivalent: 'StockScreening intraday burst stocks' },
  { key: 'strong-stocks', label: 'Strong Stocks', availability: 'available', reason: '', source_equivalent: 'StockScreening strong stocks' },
  { key: 'vwap-watchlist', label: 'VWAP Watchlist', availability: 'available', reason: '', source_equivalent: 'StockScreening VWAP watchlist' },
  { key: 'signal-a-family', label: 'Signal A / SignalAShort', availability: 'available', reason: '', source_equivalent: 'signal SignalA and SignalAShort' },
  { key: 'signal-b', label: 'Signal B', availability: 'available', reason: '', source_equivalent: 'signal SignalB' },
  { key: 'signal-c-summary', label: 'Signal C Summary', availability: 'unavailable', reason: 'Signal C is not implemented in this engine.', source_equivalent: 'StockScreening Signal C' },
  { key: 'day-high-summary', label: 'SignalDayHigh', availability: 'available', reason: '', source_equivalent: 'signal SignalDayHigh' },
]

const EMPTY_SIGNAL_COUNTERS: SignalCounters = {
  qualified: 0,
  not_qualified: 0,
  holding: 0,
  take_profit: 0,
  stop_loss: 0,
  forbidden: 0,
}

const EMPTY_DAY_HIGH_LOGIC: SignalDayHighLogicSnapshot = {
  selection_rows: [],
  entry_rows: [],
  exit_rows: [],
  funnel: {
    selected: 0,
    armed: 0,
    blocked: 0,
    entered: 0,
    holding: 0,
    exited: 0,
    block_reasons: {},
  },
}

function toSignalDayHighPhase(raw: unknown): SignalDayHighPhase {
  const value = typeof raw === 'string' ? raw : ''
  if (value === 'tracking' || value === 'pullback' || value === 'triggered' || value === 'holding' || value === 'exited') {
    return value
  }
  return 'tracking'
}

function toString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function toNumber(value: unknown): number {
  return typeof value === 'number' ? value : 0
}

function toBoolean(value: unknown): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value !== 0
  if (typeof value === 'string') {
    return value.toLowerCase() === 'true' || value === '1'
  }
  return false
}

function normalizeSignalDayHighRows(rawRows: unknown): SignalDayHighMonitorEntry[] {
  if (!Array.isArray(rawRows)) return []

  return rawRows
    .map((entry) => {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return null
      const row = entry as Record<string, unknown>
      const phase = toSignalDayHighPhase(row.phase ?? row.status)
      const triggered =
        typeof row.triggered === 'boolean'
          ? row.triggered
          : row.triggered === 1
            ? true
            : row.triggered === '1'
              ? true
              : false

      return {
        symbol: typeof row.symbol === 'string' ? row.symbol : '',
        name: typeof row.name === 'string' ? row.name : '',
        group_name: typeof row.group_name === 'string' ? row.group_name : '',
        triggered,
        established_high: toNumber(row.established_high),
        established_high_time: toString(row.established_high_time),
        pullback_confirmed: toBoolean(row.pullback_confirmed),
        pullback_low: toNumber(row.pullback_low),
        pullback_time: toString(row.pullback_time),
        last_trigger_high: toNumber(row.last_trigger_high),
        last_trigger_high_time: toString(row.last_trigger_high_time),
        last_trigger_pullback_low: toNumber(row.last_trigger_pullback_low),
        last_trigger_pullback_time: toString(row.last_trigger_pullback_time),
        trigger_time: toString(row.trigger_time),
        phase,
        entries: toNumber(row.entries),
        status: toString(row.status) || phase,
      }
    })
    .filter((row): row is SignalDayHighMonitorEntry => row !== null)
}

function normalizeSignalDayHighPhaseCounts(source: Record<string, unknown> | null): {
  tracking: number
  pullback: number
  triggered: number
  holding: number
  exited: number
} {
  if (!source || typeof source !== 'object') {
    return { tracking: 0, pullback: 0, triggered: 0, holding: 0, exited: 0 }
  }
  return {
    tracking: toNumber(source.tracking),
    pullback: toNumber(source.pullback),
    triggered: toNumber(source.triggered),
    holding: toNumber(source.holding),
    exited: toNumber(source.exited),
  }
}

function normalizeSignalDayHighSelectionRows(rawRows: unknown): SignalDayHighSelectionRow[] {
  if (!Array.isArray(rawRows)) return []
  return rawRows
    .map((entry) => {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return null
      const row = entry as Record<string, unknown>
      return {
        symbol: toString(row.symbol),
        name: toString(row.name),
        group_name: toString(row.group_name),
        selected: toBoolean(row.selected),
        rejection_reason: toString(row.rejection_reason),
        group_rank: toNumber(row.group_rank),
        member_rank: toNumber(row.member_rank),
        raw_member_rank: toNumber(row.raw_member_rank),
        m1_symbol: toString(row.m1_symbol),
        current_price: toNumber(row.current_price),
        vwap: toNumber(row.vwap),
        vwap_pct_chg: toNumber(row.vwap_pct_chg),
        month_trading_val: toNumber(row.month_trading_val),
        vol_ratio: toNumber(row.vol_ratio),
        is_disposition: toBoolean(row.is_disposition),
        is_prev_day_limit_up: toBoolean(row.is_prev_day_limit_up),
        pass_symbol_valid: row.pass_symbol_valid === undefined ? true : toBoolean(row.pass_symbol_valid),
        pass_group_validity: row.pass_group_validity === undefined ? true : toBoolean(row.pass_group_validity),
        pass_group_rank: toBoolean(row.pass_group_rank),
        pass_entry_min_group_rank:
          row.pass_entry_min_group_rank === undefined ? true : toBoolean(row.pass_entry_min_group_rank),
        pass_member_rank: toBoolean(row.pass_member_rank),
        pass_raw_rank: toBoolean(row.pass_raw_rank),
        pass_vwap_band: toBoolean(row.pass_vwap_band),
        pass_disposition_block: toBoolean(row.pass_disposition_block),
        pass_prev_day_limit_up: toBoolean(row.pass_prev_day_limit_up),
        pass_entry_max_vol_ratio:
          row.pass_entry_max_vol_ratio === undefined ? true : toBoolean(row.pass_entry_max_vol_ratio),
      }
    })
    .filter((row): row is SignalDayHighSelectionRow => row !== null)
}

function normalizeSignalDayHighEntryRows(rawRows: unknown): SignalDayHighEntryRow[] {
  if (!Array.isArray(rawRows)) return []
  return rawRows
    .map((entry) => {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return null
      const row = entry as Record<string, unknown>
      return {
        symbol: toString(row.symbol),
        name: toString(row.name),
        group_name: toString(row.group_name),
        phase: toSignalDayHighPhase(row.phase),
        trigger_time: toString(row.trigger_time),
        current_price: toNumber(row.current_price),
        established_high: toNumber(row.established_high),
        pullback_low: toNumber(row.pullback_low),
        day_high_group_limit_up_count: toNumber(row.day_high_group_limit_up_count),
        day_high_group_limit_up_limit: toNumber(row.day_high_group_limit_up_limit),
        day_high_group_limit_up_passed: toBoolean(row.day_high_group_limit_up_passed),
        filter_entry_time_limit: toBoolean(row.filter_entry_time_limit),
        filter_prev_day_limit_up: toBoolean(row.filter_prev_day_limit_up),
        filter_no_entry_friday: toBoolean(row.filter_no_entry_friday),
        filter_max_0050_entry_chg: toBoolean(row.filter_max_0050_entry_chg),
        filter_max_0050_intra_chg: toBoolean(row.filter_max_0050_intra_chg),
        filter_volatility_pause: toBoolean(row.filter_volatility_pause),
        filter_already_holding: toBoolean(row.filter_already_holding),
        filter_single_forbidden: toBoolean(row.filter_single_forbidden),
        filter_max_entry_price: toBoolean(row.filter_max_entry_price),
        allowed: toBoolean(row.allowed),
        entered: toBoolean(row.entered),
        block_reason: toString(row.block_reason),
      }
    })
    .filter((row): row is SignalDayHighEntryRow => row !== null)
}

function normalizeSignalDayHighExitRows(rawRows: unknown): SignalDayHighExitRow[] {
  if (!Array.isArray(rawRows)) return []
  return rawRows
    .map((entry) => {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return null
      const row = entry as Record<string, unknown>
      return {
        symbol: toString(row.symbol),
        name: toString(row.name),
        group_name: toString(row.group_name),
        status: row.status === 'closed' ? 'closed' : 'open',
        entry_price: toNumber(row.entry_price),
        current_price: toNumber(row.current_price),
        pnl_pct: toNumber(row.pnl_pct),
        entry_time: toString(row.entry_time),
        exit_time: toString(row.exit_time),
        stop_basis: toString(row.stop_basis),
        stop_anchor: toNumber(row.stop_anchor),
        stop_price: toNumber(row.stop_price),
        time_exit_deadline: toString(row.time_exit_deadline),
        take_profit_enabled: toBoolean(row.take_profit_enabled),
        bailout_enabled: toBoolean(row.bailout_enabled),
        hold_overnight_on_limit_up: toBoolean(row.hold_overnight_on_limit_up),
        currently_limit_up_locked: toBoolean(row.currently_limit_up_locked),
        overnight_eligible_now: toBoolean(row.overnight_eligible_now),
        final_leave_cause: toString(row.final_leave_cause),
      }
    })
    .filter((row): row is SignalDayHighExitRow => row !== null)
}

function normalizeSignalDayHighLogic(raw: unknown): SignalDayHighLogicSnapshot {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return EMPTY_DAY_HIGH_LOGIC
  }
  const source = raw as Record<string, unknown>
  const funnelRaw =
    source.funnel && typeof source.funnel === 'object' && !Array.isArray(source.funnel)
      ? (source.funnel as Record<string, unknown>)
      : null
  const blockReasonsRaw =
    funnelRaw?.block_reasons && typeof funnelRaw.block_reasons === 'object' && !Array.isArray(funnelRaw.block_reasons)
      ? (funnelRaw.block_reasons as Record<string, unknown>)
      : {}
  const block_reasons: Record<string, number> = {}
  Object.entries(blockReasonsRaw).forEach(([key, value]) => {
    block_reasons[key] = toNumber(value)
  })
  return {
    selection_rows: normalizeSignalDayHighSelectionRows(source.selection_rows),
    entry_rows: normalizeSignalDayHighEntryRows(source.entry_rows),
    exit_rows: normalizeSignalDayHighExitRows(source.exit_rows),
    funnel: {
      selected: toNumber(funnelRaw?.selected),
      armed: toNumber(funnelRaw?.armed),
      blocked: toNumber(funnelRaw?.blocked),
      entered: toNumber(funnelRaw?.entered),
      holding: toNumber(funnelRaw?.holding),
      exited: toNumber(funnelRaw?.exited),
      block_reasons,
    },
  }
}

function normalizeSignalDayHighSnapshot(raw: unknown): SignalDayHighMonitorSnapshot {
  const source =
    raw && typeof raw === 'object' && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : null
  const rows = normalizeSignalDayHighRows(source?.rows)
  const preparing = Array.isArray(source?.preparing) ? source.preparing : []
  const entered = Array.isArray(source?.entered) ? source.entered : []
  const exited = Array.isArray(source?.exited) ? source.exited : []
  const counters =
    source?.counters && typeof source.counters === 'object' && !Array.isArray(source.counters)
    ? (source.counters as SignalCounters)
    : EMPTY_SIGNAL_COUNTERS
  const phaseCounts = normalizeSignalDayHighPhaseCounts(
    source?.phase_counts && typeof source.phase_counts === 'object' && !Array.isArray(source.phase_counts)
      ? (source.phase_counts as Record<string, unknown>)
      : null,
  )

  return {
    rows,
    preparing,
    entered,
    exited,
    counters,
    phase_counts: phaseCounts,
    tracking: typeof source?.tracking === 'number' ? source.tracking : 0,
    pullback: typeof source?.pullback === 'number' ? source.pullback : 0,
    triggered: typeof source?.triggered === 'number' ? source.triggered : 0,
    entries: typeof source?.entries === 'number' ? source.entries : 0,
    logic: normalizeSignalDayHighLogic(source?.logic),
  }
}

function normalizeReplaySnapshot(payload: unknown): DashboardSnapshot | null {
  if (!payload || typeof payload !== 'object') return null
  const row = payload as Record<string, unknown>

  const groups = Array.isArray(row.groups)
    ? row.groups
    : Array.isArray(row.dashboard_groups)
      ? row.dashboard_groups
      : []
  const singles = Array.isArray(row.singles)
    ? row.singles
    : Array.isArray(row.dashboard_singles)
      ? row.dashboard_singles
      : []
  const vwapMonitor = Array.isArray(row.vwap_monitor)
    ? row.vwap_monitor
    : Array.isArray(row.dashboard_vwap)
      ? row.dashboard_vwap
      : []
  const signalA: SignalAMonitorSnapshot =
    row.signal_a && typeof row.signal_a === 'object'
      ? (row.signal_a as SignalAMonitorSnapshot)
      : row.dashboard_signal_a && typeof row.dashboard_signal_a === 'object'
        ? (row.dashboard_signal_a as SignalAMonitorSnapshot)
        : {
            preparing: [],
            entered: [],
            exited: [],
            counters: { qualified: 0, not_qualified: 0, holding: 0, take_profit: 0, stop_loss: 0, forbidden: 0 },
          }
  const signalB: SignalBMonitorSnapshot =
    row.signal_b && typeof row.signal_b === 'object'
      ? (row.signal_b as SignalBMonitorSnapshot)
      : row.dashboard_signal_b && typeof row.dashboard_signal_b === 'object'
        ? (row.dashboard_signal_b as SignalBMonitorSnapshot)
        : { rows: [], buffer_zone: 0, trade_zone: 0, triggered: 0, forbidden: 0 }
  const signalDayHigh: SignalDayHighMonitorSnapshot =
    normalizeSignalDayHighSnapshot(
      row.signal_day_high && typeof row.signal_day_high === 'object'
        ? row.signal_day_high
        : row.dashboard_signal_day_high,
    )
  const modules: DashboardModuleStatus[] = Array.isArray(row.modules)
    ? (row.modules as DashboardModuleStatus[])
    : Array.isArray(row.dashboard_modules)
      ? (row.dashboard_modules as DashboardModuleStatus[])
      : DEFAULT_MODULES

  const timestamp = typeof row.market_time === 'string'
    ? row.market_time
    : typeof row.timestamp === 'string'
      ? row.timestamp
      : ''

  return {
    timestamp,
    time_raw: typeof row.time_raw === 'number' ? row.time_raw : 0,
    tick_count: typeof row.tick_count === 'number' ? row.tick_count : 0,
    groups,
    singles,
    vwap_monitor: vwapMonitor,
    signal_a: signalA,
    signal_b: signalB,
    signal_day_high: signalDayHigh,
    modules,
  }
}

export interface ReplayControls {
  currentTime: string
  minTime: string
  maxTime: string
  playing: boolean
  jumpTo: (time: string) => Promise<void>
  step: (deltaMinutes: number) => Promise<void>
  setPlaying: (playing: boolean) => void
}

interface DashboardData {
  snapshot: DashboardSnapshot | null
  mode: 'live' | 'replay'
  connected: boolean
  lastUpdate: string
  stale: boolean
  error: string | null
  refreshNow: () => void
  replay: ReplayControls | null
}

export function useDashboardData(): DashboardData {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null)
  const [mode, setMode] = useState<'live' | 'replay'>('live')
  const [connected, setConnected] = useState(true)
  const [lastUpdate, setLastUpdate] = useState('')
  const [stale, setStale] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [replayInfo, setReplayInfo] = useState<ReplayStatusResponse | null>(null)
  const [currentReplayTime, setCurrentReplayTime] = useState('09:00')
  const [playing, setPlaying] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const playRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const staleRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const lastReceiveAtRef = useRef(0)

  const fetchAll = useCallback(async () => {
    try {
      const [groupsRes, singlesRes, vwapRes, signalARes, signalBRes, signalDayHighRes, modulesRes] = await Promise.all([
        api.groups(),
        api.singles(),
        api.vwap(),
        api.signalA(),
        api.signalB(),
        api.signalDayHigh(),
        api.modules(),
      ])
      const now = new Date().toLocaleTimeString('zh-TW')
      setSnapshot((prev) => ({
        timestamp: now,
        time_raw: prev?.time_raw ?? 0,
        tick_count: prev?.tick_count ?? 0,
        groups: groupsRes.groups,
        singles: singlesRes.singles,
        vwap_monitor: vwapRes.vwap,
        signal_a: signalARes,
        signal_b: signalBRes,
        signal_day_high: normalizeSignalDayHighSnapshot(signalDayHighRes),
        modules: modulesRes.modules,
      }))
      setLastUpdate(now)
      setError(null)
      lastReceiveAtRef.current = Date.now()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch dashboard data')
    }
  }, [])

  const jumpTo = useCallback(async (time: string) => {
    try {
      const result = await api.replayJump(time)
      if (result.error) {
        setError(typeof result.error === 'string' ? result.error : 'Replay jump failed')
        return
      }
      const snapshotData = normalizeReplaySnapshot(result.snapshot ?? result)
      if (snapshotData) {
        setSnapshot(snapshotData)
        setCurrentReplayTime(time)
        setLastUpdate(snapshotData.timestamp || time)
        setError(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Replay jump failed')
    }
  }, [])

  const step = useCallback(async (deltaMinutes: number) => {
    const min = replayInfo?.time_range?.min_time ?? '09:00'
    const max = replayInfo?.time_range?.max_time ?? '13:30'
    const next = Math.max(
      hhmmToMinutes(min),
      Math.min(hhmmToMinutes(max), hhmmToMinutes(currentReplayTime) + deltaMinutes),
    )
    await jumpTo(minutesToHHMM(next))
  }, [currentReplayTime, jumpTo, replayInfo])

  useEffect(() => {
    api.status()
      .then((s) => {
        setMode(s.mode)
        if (s.mode === 'replay') {
          setConnected(true)
        }
      })
      .catch(() => {
        setError('Unable to load server status')
      })
  }, [])

  useEffect(() => {
    if (mode === 'replay') {
      disconnectSocket()
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
      api.replayStatus()
        .then((status) => {
          setReplayInfo(status)
          const start = status.time_range?.min_time ?? '09:00'
          setCurrentReplayTime(start)
          return jumpTo(start)
        })
        .catch(() => {
          setError('Unable to load replay status')
        })
      return
    }

    // Live mode: socket push + polling fallback.
      const socket = getSocket()
    setConnected(socket.connected)
    socket.on('connect', () => setConnected(true))
    socket.on('disconnect', () => setConnected(false))
      socket.on('dashboard:snapshot', (data: DashboardSnapshot) => {
      setSnapshot({
        ...data,
        signal_b: data.signal_b ?? { rows: [], buffer_zone: 0, trade_zone: 0, triggered: 0, forbidden: 0 },
        signal_day_high: normalizeSignalDayHighSnapshot(data.signal_day_high),
        modules: data.modules ?? DEFAULT_MODULES,
      })
      setLastUpdate(data.timestamp)
      setError(null)
      lastReceiveAtRef.current = Date.now()
    })

    fetchAll()
    pollRef.current = setInterval(fetchAll, 2000)

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
      socket.off('connect')
      socket.off('disconnect')
      socket.off('dashboard:snapshot')
    }
  }, [fetchAll, jumpTo, mode])

  useEffect(() => {
    if (mode !== 'replay' || !playing) {
      if (playRef.current) {
        clearInterval(playRef.current)
        playRef.current = null
      }
      return
    }
    playRef.current = setInterval(() => {
      void step(1)
    }, 1000)
    return () => {
      if (playRef.current) {
        clearInterval(playRef.current)
        playRef.current = null
      }
    }
  }, [mode, playing, step])

  useEffect(() => {
    if (mode !== 'live') {
      setStale(false)
      return
    }
    staleRef.current = setInterval(() => {
      const ageMs = Date.now() - lastReceiveAtRef.current
      setStale(lastReceiveAtRef.current > 0 && ageMs > 5000)
    }, 1000)
    return () => {
      if (staleRef.current) {
        clearInterval(staleRef.current)
        staleRef.current = null
      }
    }
  }, [mode])

  const replay = useMemo<ReplayControls | null>(() => {
    if (mode !== 'replay') return null
    return {
      currentTime: currentReplayTime,
      minTime: replayInfo?.time_range?.min_time ?? '09:00',
      maxTime: replayInfo?.time_range?.max_time ?? '13:30',
      playing,
      jumpTo,
      step,
      setPlaying,
    }
  }, [currentReplayTime, jumpTo, mode, playing, replayInfo?.time_range?.max_time, replayInfo?.time_range?.min_time, step])

  return { snapshot, mode, connected, lastUpdate, stale, error, refreshNow: fetchAll, replay }
}
