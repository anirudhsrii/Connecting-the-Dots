import { useState } from 'react'

export type Recommendation = {
  snippet: string
  filename?: string
  page_number?: number
  section_title?: string
  section_index?: number
  distance?: number
  score?: number
}

type Props = {
  items: Recommendation[]
  onClickItem?: (item: Recommendation) => void
}

export default function RecommendationsSidebar({ items, onClickItem }: Props) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})
  const [pinned, setPinned] = useState<Record<string, boolean>>({})
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null)

  const toggleExpand = (idx: number) => setExpanded((s) => ({ ...s, [idx]: !s[idx] }))
  const keyOf = (rec: Recommendation) => `${rec.filename ?? 'unknown'}:${rec.page_number ?? -1}:${(rec.snippet ?? '').slice(0, 30)}`
  const togglePin = (rec: Recommendation) => {
    const key = keyOf(rec)
    setPinned((s) => ({ ...s, [key]: !s[key] }))
  }
  const copySnippet = async (text: string, idx: number) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedIdx(idx)
      setTimeout(() => setCopiedIdx((c) => (c === idx ? null : c)), 1200)
    } catch (e) {
      // ignore
    }
  }

  return (
    <div style={{ height: '100%', overflow: 'auto' }}>
      {items.length === 0 ? (
        <div style={{ 
          padding: 16,
          textAlign: 'center',
          color: '#6b7280',
          fontSize: 13
        }}>
          <div style={{ fontSize: 24, marginBottom: 8 }}>📄</div>
          <div>Interact with the PDF to see recommendations.</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '8px 0' }}>
          {items.map((rec, idx) => {
            const showAll = !!expanded[idx]
            const text = rec.snippet ?? ''
            const shown = showAll ? text : text.slice(0, 280)
            const hasMore = text.length > 280
            const fileLabel = rec.filename ?? 'Unknown'
            const scorePct = rec.score != null ? Math.round(rec.score * 100) : null
            const isPinned = pinned[keyOf(rec)]
            const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')
            const dlUrl = rec.filename ? `${apiBase}/document_library/${encodeURIComponent(rec.filename)}` : undefined

      return (
              <div key={idx} style={{ background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 8, padding: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <div style={{ fontSize: 12, color: '#6b7280' }}>
        {fileLabel} • Page {rec.page_number ?? '-'}{rec.section_title ? ` • ${rec.section_title}` : ''}
                  </div>
                  {scorePct !== null && (
                    <span style={{ fontSize: 12, color: '#065f46', background: '#d1fae5', border: '1px solid #10b981', borderRadius: 999, padding: '2px 8px' }}>
                      {scorePct}%
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 14, color: '#111827', whiteSpace: 'pre-wrap' }}>{shown}{!showAll && hasMore ? '…' : ''}</div>
                <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
                  <button onClick={() => onClickItem?.(rec)} style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d1d5db', background: '#fff', cursor: 'pointer' }}>Open</button>
                  <button onClick={() => copySnippet(text, idx)} style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d1d5db', background: '#fff', cursor: 'pointer' }}>
                    {copiedIdx === idx ? 'Copied' : 'Copy'}
                  </button>
                  {dlUrl && (
                    <a href={dlUrl} target="_blank" rel="noreferrer" style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d1d5db', background: '#fff', cursor: 'pointer', textDecoration: 'none', color: '#111827' }}>
                      Download
                    </a>
                  )}
                  <button onClick={() => togglePin(rec)} style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d1d5db', background: isPinned ? '#fde68a' : '#fff', cursor: 'pointer' }}>
                    {isPinned ? 'Pinned' : 'Pin'}
                  </button>
                  {hasMore && (
                    <button onClick={() => toggleExpand(idx)} style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #d1d5db', background: '#fff', cursor: 'pointer' }}>
                      {showAll ? 'Show less' : 'Show more'}
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
