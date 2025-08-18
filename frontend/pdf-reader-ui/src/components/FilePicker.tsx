import React from 'react'
import axios from 'axios'

type Props = {
  currentFile: string | null
  onChange: (filename: string) => void
  // When this value changes, the component will refetch the file list.
  refreshKey?: number | string
}

export default function FilePicker({ currentFile, onChange, refreshKey }: Props) {
  const [files, setFiles] = React.useState<string[]>([])
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const api = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')
      const res = await axios.get(`${api}/documents`)
      const list: string[] = res.data?.files ?? []
      setFiles(list)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to load documents')
    } finally {
      setLoading(false)
    }
  }

  React.useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])

  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      <label htmlFor="pdf-select" style={{ fontSize: 12, color: '#6b7280' }}>File:</label>
      <select
        id="pdf-select"
        value={currentFile || ''}
        onChange={(e) => onChange(e.target.value)}
        style={{ padding: '6px 8px', borderRadius: 6, border: '1px solid #e5e7eb', background: '#fff' }}
      >
        <option value="" disabled>
          {loading ? 'Loading…' : (files.length ? 'Select a file' : 'No files')}
        </option>
        {files.map((f) => (
          <option key={f} value={f}>{f}</option>
        ))}
      </select>
      <button onClick={load} title="Refresh list" style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid #e5e7eb', background: '#fff' }}>↻</button>
      {error && <span style={{ color: '#b91c1c', fontSize: 12 }}>{error}</span>}
    </div>
  )
}
