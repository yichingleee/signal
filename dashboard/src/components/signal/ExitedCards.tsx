import type { CompletedTrade } from '../../types/dashboard'

function fmtPct(v: number): string {
  return (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%'
}

export function ExitedCards({ trades }: { trades: CompletedTrade[] }) {
  if (trades.length === 0) return null

  const profits = trades.filter((t) => t.exit_cause.includes('take_profit'))
  const losses = trades.filter((t) => t.exit_cause.includes('stop_loss'))

  return (
    <div className="signal-section">
      <div className="signal-section-header">
        已出場
        <span className="text-muted" style={{ fontSize: 13, fontWeight: 400 }}>
          (停利 {profits.length} / 停損 {losses.length})
        </span>
      </div>
      <div className="signal-cards">
        {trades.map((t) => {
          const isProfit = t.pnl_pct >= 0
          return (
            <div
              key={`${t.symbol}-${t.entry_time}`}
              className={`signal-card ${isProfit ? 'exited-profit' : 'exited-loss'}`}
            >
              <div className="signal-card-title">
                <span className="symbol">{t.symbol}</span>
                <span className="name">{t.name}</span>
                <span className="tag">{t.group_tag}</span>
                <span className={`tag ${t.side === 'short' ? 'short-side' : 'long-side'}`}>{t.side ?? 'long'}</span>
              </div>
              <div className="signal-card-body">
                <div>
                  <span className="label">進場</span>
                  <span className="value">{t.entry_price.toFixed(1)}</span>
                </div>
                <div>
                  <span className="label">出場</span>
                  <span className="value">{t.exit_price.toFixed(1)}</span>
                </div>
                <div>
                  <span className="label">損益</span>
                  <span className={`value ${isProfit ? 'text-green' : 'text-red'}`}>
                    {fmtPct(t.pnl_pct)}
                  </span>
                </div>
                <div>
                  <span className="label">進場時間</span>
                  <span className="value">{t.entry_time}</span>
                </div>
                <div>
                  <span className="label">出場時間</span>
                  <span className="value">{t.exit_time}</span>
                </div>
                <div />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
