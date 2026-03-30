import type { SignalCounters } from '../../types/dashboard'

export function CounterBar({ counters, lastUpdate }: { counters: SignalCounters; lastUpdate: string }) {
  return (
    <div className="counter-bar">
      <div className="counter-item">
        <span className="counter-label">符合條件</span>
        <span className="counter-value green">{counters.qualified}</span>
      </div>
      <div className="counter-item">
        <span className="counter-label">不符條件</span>
        <span className="counter-value">{counters.not_qualified}</span>
      </div>
      <div className="counter-item">
        <span className="counter-label">持倉</span>
        <span className="counter-value yellow">{counters.holding}</span>
      </div>
      <div className="counter-item">
        <span className="counter-label">停利</span>
        <span className="counter-value green">{counters.take_profit}</span>
      </div>
      <div className="counter-item">
        <span className="counter-label">停損</span>
        <span className="counter-value red">{counters.stop_loss}</span>
      </div>
      <div className="counter-item">
        <span className="counter-label">禁止</span>
        <span className="counter-value red">{counters.forbidden}</span>
      </div>
      <div className="counter-item" style={{ marginLeft: 'auto' }}>
        <span className="counter-label">最後更新</span>
        <span className="counter-value" style={{ fontSize: 14 }}>{lastUpdate}</span>
      </div>
    </div>
  )
}
