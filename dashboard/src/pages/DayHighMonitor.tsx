import { SignalMonitorLayout } from '../components/signal/SignalMonitorLayout'
import { DayHighPhaseBar } from '../components/signal/DayHighPhaseBar'
import { SignalDayHighTable } from '../components/overview/SignalTables'
import type { DashboardSnapshot } from '../types/dashboard'

interface Props {
  snapshot: DashboardSnapshot | null
  lastUpdate: string
}

export function DayHighMonitor({ snapshot, lastUpdate }: Props) {
  if (!snapshot) {
    return (
      <main className="page-content">
        <div className="section-title">DayHigh 監測</div>
        <div className="empty-state">Waiting for data...</div>
      </main>
    )
  }

  return (
    <SignalMonitorLayout
      title="DayHigh 監測"
      lastUpdate={lastUpdate}
      preparing={snapshot.signal_day_high.preparing}
      entered={snapshot.signal_day_high.entered}
      exited={snapshot.signal_day_high.exited}
      counters={snapshot.signal_day_high.counters}
      beforeLifecycle={(
        <>
          <DayHighPhaseBar snapshot={snapshot.signal_day_high} />
          <SignalDayHighTable rows={snapshot.signal_day_high.rows} />
        </>
      )}
    />
  )
}
