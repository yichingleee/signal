import { SignalMonitorLayout } from '../components/signal/SignalMonitorLayout'
import type { DashboardSnapshot } from '../types/dashboard'
import { createSideSnapshot } from '../components/signal/signalLifecycleFilters'

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

  const longSnapshot = createSideSnapshot(snapshot.signal_a, 'long')

  return (
    <SignalMonitorLayout
      title="Signal A 監測"
      lastUpdate={lastUpdate}
      preparing={longSnapshot.preparing}
      entered={longSnapshot.entered}
      exited={longSnapshot.exited}
      counters={longSnapshot.counters}
      monitorEntries={snapshot.vwap_monitor}
    />
  )
}
