import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import { getSocket, disconnectSocket } from '../api/socket'
import type {
  DashboardSnapshot,
  ReplayStatusResponse,
  SignalAMonitorSnapshot,
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
      const [groupsRes, singlesRes, vwapRes, signalARes] = await Promise.all([
        api.groups(),
        api.singles(),
        api.vwap(),
        api.signalA(),
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
      setSnapshot(data)
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
