import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { GroupGrid } from '../components/groups/GroupGrid'
import { SectionToggle } from '../components/overview/SectionToggle'
import { SignalBTable, SignalDayHighTable } from '../components/overview/SignalTables'
import { SignalSummary } from '../components/overview/SignalSummary'
import { ToastStack, type ToastMessage } from '../components/overview/ToastStack'
import { UnavailableCard } from '../components/overview/UnavailableCard'
import { SinglesTable } from '../components/singles/SinglesTable'
import { VWAPTable } from '../components/vwap/VWAPTable'
import type { DashboardSnapshot } from '../types/dashboard'

const SECTION_KEY = 'tw-signal-dashboard-sections'
const DEFAULT_SECTIONS = {
  groups: true,
  burst: true,
  intradayBurst: true,
  singles: true,
  vwap: true,
  signals: true,
  signalB: true,
  dayHigh: true,
  signalC: true,
}

interface Props {
  snapshot: DashboardSnapshot | null
}

export function MarketOverview({ snapshot }: Props) {
  const [sections, setSections] = useState(DEFAULT_SECTIONS)
  const [toasts, setToasts] = useState<ToastMessage[]>([])
  const seenToastIds = useRef<Set<string>>(new Set())

  useEffect(() => {
    const raw = localStorage.getItem(SECTION_KEY)
    if (!raw) return
    try {
      setSections({ ...DEFAULT_SECTIONS, ...JSON.parse(raw) })
    } catch {
      setSections(DEFAULT_SECTIONS)
    }
  }, [])

  const moduleByKey = useMemo(() => new Map(snapshot?.modules.map((m) => [m.key, m]) ?? []), [snapshot?.modules])

  const toggleSection = (id: string) => {
    setSections((prev) => {
      const next = { ...prev, [id]: !prev[id as keyof typeof prev] }
      localStorage.setItem(SECTION_KEY, JSON.stringify(next))
      return next
    })
  }

  useEffect(() => {
    if (!snapshot) return
    const next: ToastMessage[] = []
    for (const row of snapshot.vwap_monitor) {
      if (!row.signal_a_state.includes('near_vwap')) continue
      const id = `vwap-${row.symbol}-${row.signal_a_state}`
      if (seenToastIds.current.has(id)) continue
      seenToastIds.current.add(id)
      next.push({ id, title: 'VWAP watchlist', detail: `${row.symbol} ${row.name} ${row.signal_a_state}` })
    }
    for (const row of snapshot.signal_b.rows) {
      if (row.status !== 'trade_zone' && row.status !== 'triggered') continue
      const id = `signal-b-${row.symbol}-${row.status}`
      if (seenToastIds.current.has(id)) continue
      seenToastIds.current.add(id)
      next.push({ id, title: 'Signal B', detail: `${row.symbol} ${row.name} ${row.status}` })
    }
    for (const row of snapshot.signal_day_high.rows) {
      if (row.status !== 'pullback' && row.status !== 'triggered') continue
      const id = `day-high-${row.symbol}-${row.status}`
      if (seenToastIds.current.has(id)) continue
      seenToastIds.current.add(id)
      next.push({ id, title: 'SignalDayHigh', detail: `${row.symbol} ${row.name} ${row.status}` })
    }
    if (next.length > 0) {
      setToasts((prev) => [...next, ...prev].slice(0, 4))
    }
  }, [snapshot])

  return (
    <main className="page-content">
      <div className="section-title">Market Monitoring Dashboard</div>
      {!snapshot && <div className="empty-state">Waiting for data...</div>}
      {snapshot && (
        <>
          <SectionToggle id="groups" title="Strong Groups" count={snapshot.groups.length} enabled={sections.groups} onToggle={toggleSection}>
            <GroupGrid groups={snapshot.groups} />
          </SectionToggle>
          <SectionToggle id="burst" title="Burst Groups" enabled={sections.burst} onToggle={toggleSection}>
            <UnavailableCard label="Burst Groups" module={moduleByKey.get('burst-groups')} />
          </SectionToggle>
          <SectionToggle id="intradayBurst" title="Intraday Burst Stocks" enabled={sections.intradayBurst} onToggle={toggleSection}>
            <UnavailableCard label="Intraday Burst Stocks" module={moduleByKey.get('intraday-burst')} />
          </SectionToggle>
          <SectionToggle id="singles" title="Strong Stocks" count={snapshot.singles.length} enabled={sections.singles} onToggle={toggleSection}>
            <SinglesTable singles={snapshot.singles} />
          </SectionToggle>
          <SectionToggle id="vwap" title="VWAP Watchlist" count={snapshot.vwap_monitor.length} enabled={sections.vwap} onToggle={toggleSection}>
            <VWAPTable entries={snapshot.vwap_monitor} />
          </SectionToggle>
          <SectionToggle id="signals" title="Signal Summary" enabled={sections.signals} onToggle={toggleSection}>
            <SignalSummary signalA={snapshot.signal_a} signalB={snapshot.signal_b} signalDayHigh={snapshot.signal_day_high} />
          </SectionToggle>
          <SectionToggle id="signalB" title="Signal B Monitor" count={snapshot.signal_b.rows.length} enabled={sections.signalB} onToggle={toggleSection}>
            <SignalBTable rows={snapshot.signal_b.rows} />
          </SectionToggle>
          <SectionToggle id="dayHigh" title="SignalDayHigh Summary" count={snapshot.signal_day_high.rows.length} enabled={sections.dayHigh} onToggle={toggleSection}>
            <div className="signal-section" style={{ marginBottom: 0 }}>
              <div className="text-muted" style={{ fontSize: 12 }}>
                selected {snapshot.signal_day_high.logic?.funnel.selected ?? 0} / armed {snapshot.signal_day_high.logic?.funnel.armed ?? 0} / blocked {snapshot.signal_day_high.logic?.funnel.blocked ?? 0} / holding {snapshot.signal_day_high.logic?.funnel.holding ?? 0}
                {' · '}
                <Link to="/day-high">open full DayHigh monitor</Link>
              </div>
            </div>
            <SignalDayHighTable rows={snapshot.signal_day_high.rows} />
          </SectionToggle>
          <SectionToggle id="signalC" title="Signal C Summary" enabled={sections.signalC} onToggle={toggleSection}>
            <UnavailableCard label="Signal C Summary" module={moduleByKey.get('signal-c-summary')} />
          </SectionToggle>
          <ToastStack messages={toasts} />
        </>
      )}
    </main>
  )
}
