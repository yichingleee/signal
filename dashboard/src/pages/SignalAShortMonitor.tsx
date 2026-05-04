import { SignalMonitorLayout } from '../components/signal/SignalMonitorLayout'
import type { DashboardSnapshot } from '../types/dashboard'
import { createSideSnapshot } from '../components/signal/signalLifecycleFilters'

interface Props {
  snapshot: DashboardSnapshot | null
  lastUpdate: string
}

export function SignalAShortMonitor({ snapshot, lastUpdate }: Props) {
  if (!snapshot) {
    return (
      <main className="page-content">
        <div className="section-title">SignalAShort 監測</div>
        <div className="empty-state">Waiting for data...</div>
      </main>
    )
  }

  const shortSnapshot = createSideSnapshot(snapshot.signal_a, 'short')

  return (
    <SignalMonitorLayout
      title="SignalAShort 監測"
      lastUpdate={lastUpdate}
      preparing={shortSnapshot.preparing}
      entered={shortSnapshot.entered}
      exited={shortSnapshot.exited}
      counters={shortSnapshot.counters}
      monitorEntries={snapshot.vwap_monitor}
    />
  )
}
