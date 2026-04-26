import type { PreparingEntry } from '../../types/dashboard'

function fmtPct(v: number): string {
  return (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%'
}

export function PreparingCards({ entries }: { entries: PreparingEntry[] }) {
  if (entries.length === 0) return null

  return (
    <div className="signal-section">
      <div className="signal-section-header text-blue">準備掛單</div>
      <div className="signal-cards">
        {entries.map((e) => (
          <div key={e.symbol} className="signal-card preparing">
            <div className="signal-card-title">
              <span className="symbol">{e.symbol}</span>
              <span className="name">{e.name}</span>
              <span className="tag">{e.group_tag}</span>
              <span className={`tag ${e.side === 'short' ? 'short-side' : 'long-side'}`}>{e.side ?? 'long'}</span>
            </div>
            <div className="signal-card-body">
              <div>
                <span className="label">掛單價</span>
                <span className="value">{e.order_price.toFixed(1)}</span>
              </div>
              <div>
                <span className="label">現價</span>
                <span className="value">{e.current_price.toFixed(1)}</span>
              </div>
              <div>
                <span className="label">距進場</span>
                <span className="value text-orange">{fmtPct(e.distance_pct)}</span>
              </div>
              <div>
                <span className="label">VWAP</span>
                <span className="value">{e.vwap.toFixed(2)}</span>
              </div>
              <div>
                <span className="label">最低</span>
                <span className="value">{e.day_low.toFixed(1)}</span>
              </div>
              <div>
                <span className="label">停損</span>
                <span className="value text-red">{e.stop_loss.toFixed(2)}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
