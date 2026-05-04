import type { SignalDayHighEntryRow } from '../../types/dashboard'

function passLabel(value: boolean): string {
  return value ? '✓' : '✗'
}

function decisionText(row: SignalDayHighEntryRow): string {
  if (row.entered) return 'entered'
  if (row.allowed) return 'allowed'
  return 'blocked'
}

export function DayHighEntryDecisionTable({ rows }: { rows: SignalDayHighEntryRow[] }) {
  if (rows.length === 0) return <div className="empty-state compact">No DayHigh entry decisions</div>

  return (
    <div className="table-wrapper compact-table">
      <table className="data-table">
        <thead>
          <tr>
            <th>code</th>
            <th>phase</th>
            <th>trigger</th>
            <th className="text-right">px</th>
            <th className="text-right">anchor</th>
            <th className="text-right">pullback</th>
            <th>group LU gate</th>
            <th>entry filters</th>
            <th>decision</th>
            <th>block reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.symbol}-${row.trigger_time}-${row.block_reason}`}>
              <td className="text-blue">{row.symbol}</td>
              <td>{row.phase}</td>
              <td>{row.trigger_time || '-'}</td>
              <td className="text-right">{row.current_price.toFixed(2)}</td>
              <td className="text-right">{row.established_high > 0 ? row.established_high.toFixed(2) : '-'}</td>
              <td className="text-right">{row.pullback_low > 0 ? row.pullback_low.toFixed(2) : '-'}</td>
              <td>
                {row.day_high_group_limit_up_count}/{row.day_high_group_limit_up_limit} ({passLabel(row.day_high_group_limit_up_passed)})
              </td>
              <td>
                T {passLabel(row.filter_entry_time_limit)} / PrevLU {passLabel(row.filter_prev_day_limit_up)} / Fri {passLabel(row.filter_no_entry_friday)}
                <br />
                0050E {passLabel(row.filter_max_0050_entry_chg)} / 0050I {passLabel(row.filter_max_0050_intra_chg)} / VolPause {passLabel(row.filter_volatility_pause)}
                <br />
                Hold {passLabel(row.filter_already_holding)} / Single {passLabel(row.filter_single_forbidden)} / Price {passLabel(row.filter_max_entry_price)}
              </td>
              <td className={row.entered ? 'text-green' : row.allowed ? 'text-blue' : 'text-red'}>{decisionText(row)}</td>
              <td>{row.block_reason || '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
