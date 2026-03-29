import type { VWAPMonitorEntry } from '../../types/dashboard'

function fmtPct(v: number): string {
  return (v * 100).toFixed(2) + '%'
}

function pctColor(v: number): string {
  return v > 0 ? 'text-green' : v < 0 ? 'text-red' : ''
}

function statusClass(status: string): string {
  if (status === '持倉中') return 'status-badge holding'
  if (status === '接近VWAP') return 'status-badge near-vwap'
  if (status.includes('停利')) return 'status-badge exited-profit'
  if (status.includes('停損')) return 'status-badge exited-loss'
  if (status === '禁止') return 'status-badge forbidden'
  return 'status-badge'
}

export function VWAPTable({ entries }: { entries: VWAPMonitorEntry[] }) {
  if (entries.length === 0) {
    return <div className="empty-state">No symbols in monitoring universe</div>
  }

  return (
    <div className="table-wrapper">
      <table className="data-table">
        <thead>
          <tr>
            <th>group</th>
            <th>code</th>
            <th>name</th>
            <th className="text-right">price</th>
            <th className="text-right">VWAP</th>
            <th className="text-right">VWAP%</th>
            <th className="text-right">P/VWAP</th>
            <th>status</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.symbol} className={e.status === '持倉中' ? 'bg-green' : ''}>
              <td className="text-muted">{e.group_name || '—'}</td>
              <td className="text-blue">{e.symbol}</td>
              <td>{e.name}</td>
              <td className="text-right">{e.price.toFixed(1)}</td>
              <td className="text-right">{e.vwap.toFixed(2)}</td>
              <td className={`text-right ${pctColor(e.vwap_pct)}`}>
                {fmtPct(e.vwap_pct)}
              </td>
              <td className="text-right">{e.pv_ratio.toFixed(4)}</td>
              <td>
                <span className={statusClass(e.status)}>
                  {e.status || '—'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
