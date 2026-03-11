import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchKnowledgeIndex, fetchKnowledgeDoc } from '../../api/client'
import styles from './KnowledgeView.module.css'

export function KnowledgeView() {
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const { data: indexData, isLoading } = useQuery({
    queryKey: ['knowledge-index'],
    queryFn: fetchKnowledgeIndex,
  })

  const { data: docData } = useQuery({
    queryKey: ['knowledge-doc', selectedPath],
    queryFn: () => fetchKnowledgeDoc(selectedPath!),
    enabled: !!selectedPath,
  })

  const docs = (indexData?.documents ?? []).filter((d) => {
    if (!search) return true
    const term = search.toLowerCase()
    return d.path.toLowerCase().includes(term) || d.name.toLowerCase().includes(term) || d.group.toLowerCase().includes(term)
  })

  if (isLoading) return <div className={styles.loading}>Loading knowledge base...</div>

  return (
    <div className={styles.container}>
      <h2 className={styles.heading}>Knowledge Base</h2>
      <input
        type="text" placeholder="Search docs..."
        value={search} onChange={(e) => setSearch(e.target.value)}
        className={styles.search}
      />
      <div className={styles.layout}>
        <div className={styles.docList}>
          {docs.map((doc) => (
            <button
              key={doc.path}
              className={`${styles.docBtn} ${doc.path === selectedPath ? styles.selected : ''}`}
              onClick={() => setSelectedPath(doc.path)}
            >
              <span className={styles.docGroup}>{doc.group}</span>
              <span className={styles.docName}>{doc.name}</span>
            </button>
          ))}
          {docs.length === 0 && <div className={styles.empty}>No matching docs</div>}
        </div>
        <div className={styles.content}>
          {selectedPath && docData ? (
            <pre className={styles.docContent}>{docData.content}</pre>
          ) : (
            <div className={styles.placeholder}>Select a document to view</div>
          )}
        </div>
      </div>
    </div>
  )
}
