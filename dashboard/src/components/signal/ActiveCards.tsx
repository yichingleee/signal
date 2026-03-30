import type { ActivePosition } from '../../types/dashboard'

function fmtPct(v: number): string {
  return (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%'
}

export function ActiveCards({ positions }: { positions: ActivePosition[] }) {
  if (positions.length === 0) return null

  return (
    <div className="signal-section">
      <div className="signal-section-header text-green">已進場</div>
      <div className="signal-cards">
        {positions.map((p) => (
          <div key={p.symbol} className="signal-card entered">
            <div className="signal-card-title">
              <span className="symbol">{p.symbol}</span>
              <span className="name">{p.name}</span>
              <span className="tag">{p.group_tag}</span>
            </div>
            <div className="signal-card-body">
              <div>
                <span className="label">進場</span>
                <span className="value">{p.entry_price.toFixed(1)}</span>
              </div>
              <div>
                <span className="label">現價</span>
                <span className="value">{p.current_price.toFixed(1)}</span>
              </div>
              <div>
                <span className="label">損益</span>
                <span className={`value ${p.pnl_pct >= 0 ? 'text-green' : 'text-red'}`}>
                  {fmtPct(p.pnl_pct)}
                </span>
              </div>
              <div>
                <span className="label">停損</span>
                <span className="value text-red">{p.stop_loss.toFixed(1)}</span>
              </div>
              <div>
                <span className="label">停利</span>
                <span className="value text-green">{p.take_profit.toFixed(1)}</span>
              </div>
              <div>
                <span className="label">DH</span>
                <span className="value">{p.day_high.toFixed(1)}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
