import { useState } from 'react'
import type { GroupSnapshot } from '../../types/dashboard'
import { GroupCard } from './GroupCard'

export function GroupGrid({ groups }: { groups: GroupSnapshot[] }) {
  const [selected, setSelected] = useState<GroupSnapshot | null>(null)

  if (groups.length === 0) {
    return <div className="empty-state">No strong groups detected</div>
  }

  return (
    <>
      <div className="group-grid">
        {groups.map((g) => (
          <GroupCard key={g.group_name} group={g} onOpen={setSelected} />
        ))}
      </div>
      {selected && (
        <div className="modal-backdrop" onClick={() => setSelected(null)}>
          <div className="detail-modal" onClick={(e) => e.stopPropagation()}>
            <div className="detail-modal-header">
              <h3>{selected.group_name}</h3>
              <button type="button" onClick={() => setSelected(null)}>Close</button>
            </div>
            <GroupCard group={selected} />
          </div>
        </div>
      )}
    </>
  )
}
