import type { SingleSnapshot } from '../../types/dashboard'

function fmtPct(v: number): string {
  return (v * 100).toFixed(2) + '%'
}

function pctColor(v: number): string {
  return v > 0 ? 'text-green' : v < 0 ? 'text-red' : ''
}

export function SinglesTable({ singles }: { singles: SingleSnapshot[] }) {
  if (singles.length === 0) {
    return <div className="empty-state">No strong singles detected</div>
  }

  return (
    <div className="table-wrapper">
      <table className="data-table">
        <thead>
          <tr>
            <th>code</th>
            <th>name</th>
            <th>group</th>
            <th className="text-right">price</th>
            <th className="text-right">chg%</th>
            <th className="text-right">VWAP</th>
            <th className="text-right">VWAP%</th>
            <th className="text-right">vol ratio</th>
          </tr>
        </thead>
        <tbody>
          {singles.map((s) => (
            <tr key={s.symbol}>
              <td className="text-blue">{s.symbol}</td>
              <td>{s.name}</td>
              <td className="text-muted">{s.group_name || '—'}</td>
              <td className="text-right">{s.price.toFixed(1)}</td>
              <td className={`text-right ${pctColor(s.pct_chg)}`}>
                {fmtPct(s.pct_chg)}
              </td>
              <td className="text-right">{s.vwap.toFixed(2)}</td>
              <td className={`text-right ${pctColor(s.vwap_pct_chg)}`}>
                {fmtPct(s.vwap_pct_chg)}
              </td>
              <td className="text-right">{s.cum_vol_ratio.toFixed(2)}x</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
