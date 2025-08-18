import React from 'react'
import axios from 'axios'

type Props = {
  onUploaded?: (filenames: string[]) => void
}

export default function UploadPdfButton({ onUploaded }: Props) {
  const inputRef = React.useRef<HTMLInputElement | null>(null)

  const onClick = () => inputRef.current?.click()

  const onChange: React.ChangeEventHandler<HTMLInputElement> = async (e) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    const form = new FormData()
    for (const f of Array.from(files)) form.append('files', f)
    try {
      const api = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')
      const res = await axios.post(`${api}/upload`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const filenames: string[] = res.data?.saved ?? []
      onUploaded?.(filenames)
    } catch (err) {
      console.error('Upload failed', err)
    } finally {
      // reset to allow re-selecting the same file
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <>
      <button
        onClick={onClick}
        style={{
          padding: '8px 14px',
          borderRadius: 8,
          border: '1px solid #d1d5db',
          background: '#111827',
          color: '#fff',
          cursor: 'pointer',
        }}
      >
        Upload PDF
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        multiple
        onChange={onChange}
        style={{ display: 'none' }}
      />
    </>
  )
}
