import type { SignalDayHighExitRow } from '../../types/dashboard'

function fmtPct(v: number): string {
  return (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%'
}

export function DayHighExitPolicyCards({ rows }: { rows: SignalDayHighExitRow[] }) {
  if (rows.length === 0) return null

  const openRows = rows.filter((row) => row.status === 'open')
  const closedRows = rows.filter((row) => row.status === 'closed').slice(-12).reverse()

  return (
    <>
      {openRows.length > 0 && (
        <div className="signal-section">
          <div className="signal-section-header text-green">DayHigh Exit Policy (Open)</div>
          <div className="signal-cards">
            {openRows.map((row) => (
              <div key={`${row.symbol}-${row.entry_time}`} className="signal-card entered">
                <div className="signal-card-title">
                  <span className="symbol">{row.symbol}</span>
                  <span className="name">{row.name}</span>
                  <span className="tag">{row.group_name || '-'}</span>
                </div>
                <div className="signal-card-body">
                  <div>
                    <span className="label">entry/current</span>
                    <span className="value">{row.entry_price.toFixed(2)} / {row.current_price.toFixed(2)}</span>
                  </div>
                  <div>
                    <span className="label">pnl</span>
                    <span className={`value ${row.pnl_pct >= 0 ? 'text-green' : 'text-red'}`}>{fmtPct(row.pnl_pct)}</span>
                  </div>
                  <div>
                    <span className="label">stop</span>
                    <span className="value text-red">{row.stop_price.toFixed(2)}</span>
                  </div>
                  <div>
                    <span className="label">stop basis</span>
                    <span className="value">{row.stop_basis} @ {row.stop_anchor.toFixed(2)}</span>
                  </div>
                  <div>
                    <span className="label">time exit</span>
                    <span className="value">{row.time_exit_deadline || '-'}</span>
                  </div>
                  <div>
                    <span className="label">overnight</span>
                    <span className="value">
                      {row.hold_overnight_on_limit_up ? 'enabled' : 'disabled'} / lock {row.currently_limit_up_locked ? 'yes' : 'no'} / eligible {row.overnight_eligible_now ? 'yes' : 'no'}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {closedRows.length > 0 && (
        <div className="signal-section">
          <div className="signal-section-header">DayHigh Exit Outcomes</div>
          <div className="signal-cards">
            {closedRows.map((row) => (
              <div
                key={`${row.symbol}-${row.entry_time}-${row.exit_time}`}
                className={`signal-card ${row.pnl_pct >= 0 ? 'exited-profit' : 'exited-loss'}`}
              >
                <div className="signal-card-title">
                  <span className="symbol">{row.symbol}</span>
                  <span className="name">{row.name}</span>
                  <span className="tag">{row.group_name || '-'}</span>
                </div>
                <div className="signal-card-body">
                  <div>
                    <span className="label">entry/exit</span>
                    <span className="value">{row.entry_price.toFixed(2)} / {row.current_price.toFixed(2)}</span>
                  </div>
                  <div>
                    <span className="label">pnl</span>
                    <span className={`value ${row.pnl_pct >= 0 ? 'text-green' : 'text-red'}`}>{fmtPct(row.pnl_pct)}</span>
                  </div>
                  <div>
                    <span className="label">leave cause</span>
                    <span className="value">{row.final_leave_cause || '-'}</span>
                  </div>
                  <div>
                    <span className="label">entry time</span>
                    <span className="value">{row.entry_time || '-'}</span>
                  </div>
                  <div>
                    <span className="label">exit time</span>
                    <span className="value">{row.exit_time || '-'}</span>
                  </div>
                  <div>
                    <span className="label">time exit rule</span>
                    <span className="value">{row.time_exit_deadline || '-'}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}
