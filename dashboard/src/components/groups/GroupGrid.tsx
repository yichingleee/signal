import type { GroupSnapshot } from '../../types/dashboard'
import { GroupCard } from './GroupCard'

export function GroupGrid({ groups }: { groups: GroupSnapshot[] }) {
  if (groups.length === 0) {
    return <div className="empty-state">No strong groups detected</div>
  }

  return (
    <div className="group-grid">
      {groups.map((g) => (
        <GroupCard key={g.group_name} group={g} />
      ))}
    </div>
  )
}
