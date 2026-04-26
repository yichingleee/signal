import type { SignalBMonitorEntry, SignalDayHighMonitorEntry } from '../../types/dashboard'

function badgeClass(status: string): string {
  if (status === 'triggered' || status === 'holding') return 'status-badge holding'
  if (status === 'trade_zone' || status === 'pullback') return 'status-badge near-vwap'
  if (status === 'forbidden') return 'status-badge forbidden'
  return 'status-badge'
}

export function SignalBTable({ rows }: { rows: SignalBMonitorEntry[] }) {
  if (rows.length === 0) return <div className="empty-state compact">No active Signal B states</div>

  return (
    <div className="table-wrapper compact-table">
      <table className="data-table">
        <thead>
          <tr>
            <th>code</th>
            <th>name</th>
            <th>group</th>
            <th className="text-right">rolling low</th>
            <th className="text-right">volume ratio</th>
            <th>status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.symbol}>
              <td className="text-blue">{row.symbol}</td>
              <td>{row.name}</td>
              <td className="text-muted">{row.group_name || '-'}</td>
              <td className="text-right">{row.rolling_low.toFixed(2)}</td>
              <td className="text-right">{row.rolling_sum_ratio.toFixed(2)}x</td>
              <td><span className={badgeClass(row.status)}>{row.status || '-'}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function SignalDayHighTable({ rows }: { rows: SignalDayHighMonitorEntry[] }) {
  if (rows.length === 0) return <div className="empty-state compact">No active SignalDayHigh states</div>

  return (
    <div className="table-wrapper compact-table">
      <table className="data-table">
        <thead>
          <tr>
            <th>code</th>
            <th>name</th>
            <th>group</th>
            <th className="text-right">est. high</th>
            <th className="text-right">pullback low</th>
            <th className="text-right">entries</th>
            <th>status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.symbol}>
              <td className="text-blue">{row.symbol}</td>
              <td>{row.name}</td>
              <td className="text-muted">{row.group_name || '-'}</td>
              <td className="text-right">{row.established_high.toFixed(2)}</td>
              <td className="text-right">{row.pullback_low.toFixed(2)}</td>
              <td className="text-right">{row.entries}</td>
              <td><span className={badgeClass(row.status)}>{row.status || '-'}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
