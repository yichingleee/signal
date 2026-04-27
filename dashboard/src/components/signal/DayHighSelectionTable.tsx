import type { SignalDayHighSelectionRow } from '../../types/dashboard'

function passLabel(value: boolean): string {
  return value ? '✓' : '✗'
}

export function DayHighSelectionTable({ rows }: { rows: SignalDayHighSelectionRow[] }) {
  if (rows.length === 0) return <div className="empty-state compact">No DayHigh selection rows</div>

  return (
    <div className="table-wrapper compact-table">
      <table className="data-table">
        <thead>
          <tr>
            <th>code</th>
            <th>name</th>
            <th>group</th>
            <th className="text-right">G/M/R</th>
            <th>M1</th>
            <th className="text-right">px</th>
            <th className="text-right">vwap%</th>
            <th className="text-right">vol ratio</th>
            <th className="text-right">month tv</th>
            <th>rules</th>
            <th>selected</th>
            <th>reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.symbol}>
              <td className="text-blue">{row.symbol}</td>
              <td>{row.name}</td>
              <td className="text-muted">{row.group_name || '-'}</td>
              <td className="text-right">
                {row.group_rank || '-'} / {row.member_rank || '-'} / {row.raw_member_rank || '-'}
              </td>
              <td>{row.m1_symbol || '-'}</td>
              <td className="text-right">{row.current_price.toFixed(2)}</td>
              <td className="text-right">{(row.vwap_pct_chg * 100).toFixed(2)}%</td>
              <td className="text-right">{row.vol_ratio.toFixed(2)}</td>
              <td className="text-right">{row.month_trading_val.toLocaleString()}</td>
              <td>
                G {passLabel(row.pass_group_rank)} / M {passLabel(row.pass_member_rank)} / R {passLabel(row.pass_raw_rank)}
                <br />
                VB {passLabel(row.pass_vwap_band)} / Disp {passLabel(row.pass_disposition_block)} / PrevLU {passLabel(row.pass_prev_day_limit_up)}
              </td>
              <td className={row.selected ? 'text-green' : 'text-red'}>{row.selected ? 'yes' : 'no'}</td>
              <td>{row.rejection_reason || '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
