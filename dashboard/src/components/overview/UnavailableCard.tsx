import type { DashboardModuleStatus } from '../../types/dashboard'

interface Props {
  module?: DashboardModuleStatus
  label: string
}

export function UnavailableCard({ module, label }: Props) {
  return (
    <div className="unavailable-card">
      <div className="unavailable-title">{module?.label ?? label}</div>
      <div className="unavailable-reason">
        {module?.reason || 'This module is present in the source dashboard but has no data contract in this engine.'}
      </div>
      {module?.source_equivalent && (
        <div className="unavailable-source">Source equivalent: {module.source_equivalent}</div>
      )}
    </div>
  )
}
