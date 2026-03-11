import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchPlaybookDetail, updatePlaybookDraft, promotePlaybook, deletePlaybookDraft } from '../../api/client'
import { useToastStore } from '../../stores/toast'
import type { PlaybookStepDetail } from '../../api/types'
import styles from './DraftEditor.module.css'

interface Props {
  draftId: string
  onClose: () => void
}

export function DraftEditor({ draftId, onClose }: Props) {
  const queryClient = useQueryClient()
  const addToast = useToastStore((s) => s.addToast)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editForm, setEditForm] = useState<Partial<PlaybookStepDetail>>({})

  const { data, isLoading } = useQuery({
    queryKey: ['playbook-detail', draftId],
    queryFn: () => fetchPlaybookDetail(draftId),
  })

  const updateMutation = useMutation({
    mutationFn: (steps: PlaybookStepDetail[]) => updatePlaybookDraft(draftId, { steps }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playbook-detail', draftId] })
      queryClient.invalidateQueries({ queryKey: ['playbook-drafts'] })
      addToast('Draft updated', 'success')
    },
  })

  const promoteMutation = useMutation({
    mutationFn: () => promotePlaybook(draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playbook-drafts'] })
      queryClient.invalidateQueries({ queryKey: ['playbooks'] })
      addToast('Playbook promoted', 'success')
      onClose()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deletePlaybookDraft(draftId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playbook-drafts'] })
      addToast('Draft deleted', 'success')
      onClose()
    },
  })

  if (isLoading || !data) return <div className={styles.loading}>Loading draft...</div>

  const steps = data.steps

  const startEdit = (index: number) => {
    setEditingIndex(index)
    setEditForm(steps[index])
  }

  const saveEdit = () => {
    if (editingIndex === null) return
    const updated = [...steps]
    updated[editingIndex] = { ...updated[editingIndex], ...editForm }
    updateMutation.mutate(updated)
    setEditingIndex(null)
  }

  const deleteStep = (index: number) => {
    const updated = steps.filter((_, i) => i !== index).map((s, i) => ({ ...s, number: i + 1 }))
    updateMutation.mutate(updated)
  }

  const moveStep = (index: number, direction: -1 | 1) => {
    const target = index + direction
    if (target < 0 || target >= steps.length) return
    const updated = [...steps]
    ;[updated[index], updated[target]] = [updated[target], updated[index]]
    updateMutation.mutate(updated.map((s, i) => ({ ...s, number: i + 1 })))
  }

  return (
    <div className={styles.editor}>
      <div className={styles.header}>
        <h4 className={styles.title}>{data.name}</h4>
        <div className={styles.actions}>
          <button onClick={() => promoteMutation.mutate()} className={styles.promoteBtn} disabled={promoteMutation.isPending}>
            Promote
          </button>
          <button onClick={() => deleteMutation.mutate()} className={styles.deleteBtn} disabled={deleteMutation.isPending}>
            Delete
          </button>
          <button onClick={onClose} className={styles.closeBtn}>Close</button>
        </div>
      </div>

      {data.description && <p className={styles.description}>{data.description}</p>}

      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.th}>#</th>
            <th className={styles.th}>Description</th>
            <th className={styles.th}>Tool</th>
            <th className={styles.th}>Human?</th>
            <th className={styles.th}></th>
          </tr>
        </thead>
        <tbody>
          {steps.map((step, i) => (
            <tr key={i} className={styles.row}>
              {editingIndex === i ? (
                <>
                  <td className={styles.td}>{step.number}</td>
                  <td className={styles.td}>
                    <input
                      className={styles.input}
                      value={editForm.description ?? ''}
                      onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                    />
                  </td>
                  <td className={styles.td}>
                    <input
                      className={styles.input}
                      value={editForm.tool ?? ''}
                      onChange={(e) => setEditForm({ ...editForm, tool: e.target.value })}
                    />
                  </td>
                  <td className={styles.td}>{step.requires_human ? 'Yes' : 'No'}</td>
                  <td className={styles.td}>
                    <button onClick={saveEdit} className={styles.saveBtn}>Save</button>
                    <button onClick={() => setEditingIndex(null)} className={styles.cancelBtn}>Cancel</button>
                  </td>
                </>
              ) : (
                <>
                  <td className={styles.td}>{step.number}</td>
                  <td className={styles.td}>{step.description}</td>
                  <td className={styles.tdTool}>{step.tool}</td>
                  <td className={styles.td}>{step.requires_human ? 'Yes' : 'No'}</td>
                  <td className={styles.td}>
                    <button onClick={() => startEdit(i)} className={styles.editBtn}>Edit</button>
                    <button onClick={() => moveStep(i, -1)} className={styles.moveBtn} disabled={i === 0}>Up</button>
                    <button onClick={() => moveStep(i, 1)} className={styles.moveBtn} disabled={i === steps.length - 1}>Dn</button>
                    <button onClick={() => deleteStep(i)} className={styles.deleteStepBtn}>X</button>
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
