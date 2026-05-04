import { SignalDayHighTable } from '../components/overview/SignalTables'
import { DayHighEntryDecisionTable } from '../components/signal/DayHighEntryDecisionTable'
import { DayHighExitPolicyCards } from '../components/signal/DayHighExitPolicyCards'
import { DayHighPhaseBar } from '../components/signal/DayHighPhaseBar'
import { DayHighSelectionTable } from '../components/signal/DayHighSelectionTable'
import { SignalMonitorLayout } from '../components/signal/SignalMonitorLayout'
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

  const logic = snapshot.signal_day_high.logic

  return (
    <SignalMonitorLayout
      title="DayHigh 監測"
      lastUpdate={lastUpdate}
      preparing={snapshot.signal_day_high.preparing}
      entered={snapshot.signal_day_high.entered}
      exited={snapshot.signal_day_high.exited}
      counters={snapshot.signal_day_high.counters}
    >
      <DayHighPhaseBar snapshot={snapshot.signal_day_high} />
      <div className="signal-section">
        <div className="signal-section-header">Stock Selection</div>
      </div>
      <DayHighSelectionTable rows={logic.selection_rows} />
      <div className="signal-section">
        <div className="signal-section-header">Pattern Monitor</div>
      </div>
      <SignalDayHighTable rows={snapshot.signal_day_high.rows} />
      <div className="signal-section">
        <div className="signal-section-header">Entry Decisions</div>
      </div>
      <DayHighEntryDecisionTable rows={logic.entry_rows} />
      <DayHighExitPolicyCards rows={logic.exit_rows} />
    </SignalMonitorLayout>
  )
}
