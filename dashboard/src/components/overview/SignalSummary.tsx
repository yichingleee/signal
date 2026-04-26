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
          <Metric label="tracking" value={signalDayHigh.tracking} tone="blue" />
          <Metric label="pullback" value={signalDayHigh.pullback} tone="yellow" />
          <Metric label="triggered" value={signalDayHigh.triggered} tone="green" />
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
