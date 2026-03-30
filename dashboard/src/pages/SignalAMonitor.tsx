import { ActiveCards } from '../components/signal/ActiveCards'
import { CounterBar } from '../components/signal/CounterBar'
import { ExitedCards } from '../components/signal/ExitedCards'
import { MonitorTable } from '../components/signal/MonitorTable'
import { PreparingCards } from '../components/signal/PreparingCards'
import type { DashboardSnapshot } from '../types/dashboard'

interface Props {
  snapshot: DashboardSnapshot | null
  lastUpdate: string
}

export function SignalAMonitor({ snapshot, lastUpdate }: Props) {
  if (!snapshot) {
    return (
      <main className="page-content">
        <div className="section-title">Signal A 監測</div>
        <div className="empty-state">Waiting for data...</div>
      </main>
    )
  }

  return (
    <main className="page-content">
      <div className="section-title">Signal A 監測</div>
      <CounterBar counters={snapshot.signal_a.counters} lastUpdate={lastUpdate} />
      <PreparingCards entries={snapshot.signal_a.preparing} />
      <ActiveCards positions={snapshot.signal_a.entered} />
      <ExitedCards trades={snapshot.signal_a.exited} />
      <MonitorTable entries={snapshot.vwap_monitor} />
    </main>
  )
}
