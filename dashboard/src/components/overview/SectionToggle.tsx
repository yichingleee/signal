import type { ReactNode } from 'react'

interface Props {
  id: string
  title: string
  count?: number
  enabled: boolean
  onToggle: (id: string) => void
  children: ReactNode
}

export function SectionToggle({ id, title, count, enabled, onToggle, children }: Props) {
  return (
    <section className={`dashboard-section ${enabled ? '' : 'collapsed'}`}>
      <div className="dashboard-section-header">
        <div>
          <h2>{title}</h2>
          {typeof count === 'number' && <span className="section-count">{count}</span>}
        </div>
        <button type="button" className="section-toggle-btn" onClick={() => onToggle(id)}>
          {enabled ? 'Hide' : 'Show'}
        </button>
      </div>
      {enabled && children}
    </section>
  )
}
