import type {
  SignalAMonitorSnapshot,
  SignalBMonitorSnapshot,
  SignalDayHighMonitorSnapshot,
} from '../../types/dashboard'

interface Props {
  signalA: SignalAMonitorSnapshot
  signalB: SignalBMonitorSnapshot
  signalDayHigh: SignalDayHighMonitorSnapshot
}

export function SignalSummary({ signalA, signalB, signalDayHigh }: Props) {
  const shortPreparing = signalA.preparing.filter((row) => row.side === 'short').length
  const shortHolding = signalA.entered.filter((row) => row.side === 'short').length
  const dayHighPhase = signalDayHigh.phase_counts
    ? signalDayHigh.phase_counts
    : {
      tracking: signalDayHigh.rows.filter((row) => row.phase === 'tracking').length,
      pullback: signalDayHigh.rows.filter((row) => row.phase === 'pullback').length,
      triggered: signalDayHigh.rows.filter((row) => row.phase === 'triggered').length,
      holding: signalDayHigh.rows.filter((row) => row.phase === 'holding').length,
      exited: signalDayHigh.rows.filter((row) => row.phase === 'exited').length,
    }
  const dayHighTriggered = dayHighPhase.triggered + dayHighPhase.holding

  return (
    <div className="summary-grid">
      <div className="summary-card">
        <div className="summary-title">Signal A Family</div>
        <div className="summary-metrics">
          <Metric label="near/triggered" value={signalA.counters.qualified} tone="green" />
          <Metric label="holding" value={signalA.counters.holding} tone="yellow" />
          <Metric label="short prep/hold" value={`${shortPreparing}/${shortHolding}`} tone="blue" />
          <Metric label="forbidden" value={signalA.counters.forbidden} tone="red" />
        </div>
      </div>
      <div className="summary-card">
        <div className="summary-title">Signal B</div>
        <div className="summary-metrics">
          <Metric label="buffer" value={signalB.buffer_zone} tone="blue" />
          <Metric label="trade zone" value={signalB.trade_zone} tone="yellow" />
          <Metric label="triggered" value={signalB.triggered} tone="green" />
          <Metric label="forbidden" value={signalB.forbidden} tone="red" />
        </div>
      </div>
      <div className="summary-card">
        <div className="summary-title">SignalDayHigh</div>
        <div className="summary-metrics">
          <Metric label="tracking" value={dayHighPhase.tracking} tone="blue" />
          <Metric label="pullback" value={dayHighPhase.pullback} tone="yellow" />
          <Metric label="triggered" value={dayHighTriggered} tone="green" />
          <Metric label="holding" value={dayHighPhase.holding} tone="orange" />
          <Metric label="entries" value={signalDayHigh.entries} tone="green" />
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value, tone }: { label: string; value: number | string; tone: string }) {
  return (
    <div className="summary-metric">
      <span>{label}</span>
      <strong className={`text-${tone}`}>{value}</strong>
    </div>
  )
}
