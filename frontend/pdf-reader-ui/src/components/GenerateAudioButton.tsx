import React from 'react'
import axios from 'axios'

type Props = {
  getContext: () => Promise<{ text?: string; filename?: string; page_number?: number }>
  onGenerated?: (data: { url: string; parts?: string[]; chapters?: any[] }) => void
}

export default function GenerateAudioButton({ getContext, onGenerated }: Props) {
  const [loading, setLoading] = React.useState(false)
  const [mode, setMode] = React.useState<'single' | 'two'>('two')

  const onClick = async () => {
    setLoading(true)
    try {
      const payload = await getContext()
      
      // Configure based on selected mode
      const requestPayload = {
        ...payload,
        podcast: mode === 'two',
        two_speakers: mode === 'two',
        expressiveness: mode === 'two' ? 'high' : 'medium',
        // Hint Gemini TTS to use these prebuilt voices; backend reads comma-separated style for multi-speaker
        style: mode === 'two' ? 'Charon,Puck' : 'Charon'
      }
      
      const api = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')
      const res = await axios.post(`${api}/generate-audio`, requestPayload)
      const relUrl: string = res.data?.url
      const parts: string[] | undefined = res.data?.parts
      const ch: any[] | undefined = res.data?.chapters
      
      if (!relUrl) throw new Error('No audio URL returned')
      
      const full = relUrl.startsWith('http') ? relUrl : `${api}${relUrl}`
      
      // Build absolute URLs for parts if provided
      const absoluteParts = Array.isArray(parts) && parts.length > 0 
        ? parts.map(p => (p.startsWith('http') ? p : `${api}${p}`))
        : undefined

      // Notify parent component with generated data
      onGenerated?.({ 
        url: full, 
        parts: absoluteParts, 
        chapters: Array.isArray(ch) ? ch : undefined 
      })
      
    } catch (e: any) {
      console.error('Audio generation failed:', e)
      // Could show a toast notification here instead
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <select
        value={mode}
        onChange={(e) => setMode(e.target.value as 'single' | 'two')}
        style={{
          padding: '6px 8px',
          borderRadius: 6,
          border: '1px solid #d1d5db',
          background: '#fff',
          fontSize: 11,
          fontWeight: 500,
          color: '#374151'
        }}
      >
        <option value="single">👤 Single</option>
        <option value="two">👥 Two Speakers</option>
      </select>
      
      <button
        onClick={onClick}
    disabled={loading}
  title={mode === 'single' ? 'Generate single narrator' : 'Generate podcast with Charon & Puck'}
        style={{ 
          padding: '8px 12px', 
          borderRadius: 8, 
          border: '1px solid #3b82f6', 
          background: loading ? '#f3f4f6' : '#3b82f6', 
          color: loading ? '#6b7280' : '#fff',
          cursor: loading ? 'not-allowed' : 'pointer',
          fontWeight: 600,
          fontSize: 12,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          boxShadow: '0 2px 4px rgba(59, 130, 246, 0.2)'
        }}
      >
        {loading ? '⏳ Generating...' : '🎙️ Narrate'}
      </button>
    </div>
  )
}
