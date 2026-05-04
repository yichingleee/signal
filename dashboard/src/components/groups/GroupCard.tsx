import type { GroupSnapshot } from '../../types/dashboard'

function fmtPct(v: number): string {
  return (v * 100).toFixed(2) + '%'
}

function fmtRatio(v: number): string {
  return v.toFixed(2) + 'x'
}

function pctColor(v: number): string {
  return v > 0 ? 'text-green' : v < 0 ? 'text-red' : ''
}

function ratioColor(v: number): string {
  return v > 1.0 ? 'text-red' : 'text-green'
}

export function GroupCard({ group, onOpen }: { group: GroupSnapshot; onOpen?: (group: GroupSnapshot) => void }) {
  return (
    <div
      className="group-card"
      role={onOpen ? 'button' : undefined}
      tabIndex={onOpen ? 0 : undefined}
      onClick={() => onOpen?.(group)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onOpen?.(group)
      }}
    >
      <div className="group-card-header">
        <h3>{group.group_name}</h3>
        <div className="group-stats">
          <div className="group-stat">
            <span className="group-stat-label">avg chg</span>
            <span className={`group-stat-value ${pctColor(group.avg_pct_chg)}`}>
              {fmtPct(group.avg_pct_chg)}
            </span>
          </div>
          <div className="group-stat">
            <span className="group-stat-label">vol ratio</span>
            <span className={`group-stat-value ${ratioColor(group.vol_ratio)}`}>
              {fmtRatio(group.vol_ratio)}
            </span>
          </div>
          <div className="group-stat">
            <span className="group-stat-label">avg surge</span>
            <span className={`group-stat-value ${ratioColor(group.avg_vol_surge)}`}>
              {fmtRatio(group.avg_vol_surge)}
            </span>
          </div>
        </div>
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>code</th>
            <th>name</th>
            <th className="text-right">price</th>
            <th className="text-right">chg%</th>
            <th className="text-right">VWAP</th>
            <th className="text-right">vol ratio</th>
            <th className="text-right">shrink</th>
          </tr>
        </thead>
        <tbody>
          {group.members.map((m) => (
            <tr key={m.symbol}>
              <td className="text-blue">{m.symbol}</td>
              <td>{m.name}</td>
              <td className="text-right">{m.price.toFixed(1)}</td>
              <td className={`text-right ${pctColor(m.pct_chg)}`}>
                {fmtPct(m.pct_chg)}
              </td>
              <td className="text-right">{m.vwap.toFixed(2)}</td>
              <td className={`text-right ${ratioColor(m.cum_vol_ratio)}`}>
                {fmtRatio(m.cum_vol_ratio)}
              </td>
              <td className="text-right">{m.vol_shrink_ratio.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
