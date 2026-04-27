import type { SignalDayHighMonitorSnapshot } from '../../types/dashboard'

function getCounts(snapshot: SignalDayHighMonitorSnapshot) {
  const phaseCounts = snapshot.phase_counts
    ? snapshot.phase_counts
    : {
        tracking: snapshot.rows.filter((row) => row.phase === 'tracking').length,
        pullback: snapshot.rows.filter((row) => row.phase === 'pullback').length,
        triggered: snapshot.rows.filter((row) => row.phase === 'triggered').length,
        holding: snapshot.rows.filter((row) => row.phase === 'holding').length,
        exited: snapshot.rows.filter((row) => row.phase === 'exited').length,
      }

  return {
    tracking: phaseCounts.tracking,
    pullback: phaseCounts.pullback,
    triggered: phaseCounts.triggered,
    holding: phaseCounts.holding,
    entries: snapshot.entries,
  }
}

export function DayHighPhaseBar({ snapshot }: { snapshot: SignalDayHighMonitorSnapshot }) {
  const counts = getCounts(snapshot)

  return (
    <div className="counter-bar">
      <div className="counter-item">
        <span className="counter-label">追蹤中</span>
        <span className="counter-value text-blue">{counts.tracking}</span>
      </div>
      <div className="counter-item">
        <span className="counter-label">回落確認</span>
        <span className="counter-value text-orange">{counts.pullback}</span>
      </div>
      <div className="counter-item">
        <span className="counter-label">已突破</span>
        <span className="counter-value text-green">{counts.triggered}</span>
      </div>
      <div className="counter-item">
        <span className="counter-label">持有中</span>
        <span className="counter-value text-green">{counts.holding}</span>
      </div>
      <div className="counter-item">
        <span className="counter-label">今日訊號</span>
        <span className="counter-value">{counts.entries}</span>
      </div>
    </div>
  )
}
