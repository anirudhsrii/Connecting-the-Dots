import React from 'react'
import axios from 'axios'
import UploadPdfButton from './components/UploadPdfButton'
import GenerateAudioButton from './components/GenerateAudioButton'
import RecommendationsSidebar, { type Recommendation } from './components/RecommendationsSidebar'
import FilePicker from './components/FilePicker'
import PodcastStudio from './components/PodcastStudio'

// Enhanced meta strip for podcast details with modern design
function PodcastMetaStrip({ meta }: { meta: { url: string; parts?: any[]; chapters?: any[] } }) {
  const chapters = Array.isArray(meta.chapters) ? meta.chapters : []
  const speakers = Array.from(new Set(chapters.map((c: any) => (c.speaker || '').toString().trim()).filter(Boolean)))
  const parts = Array.isArray(meta.parts) ? meta.parts : []
  
  // Calculate duration from chapters
  let totalMs: number | null = null
  for (let i = chapters.length - 1; i >= 0; i--) {
    const c = chapters[i]
    if (typeof c.end_ms === 'number') { totalMs = c.end_ms; break }
    if (typeof c.start_ms === 'number') { totalMs = c.start_ms; break }
  }
  
  const fmt = (ms: number | null) => {
    if (!ms || ms <= 0) return '—:—'
    const s = Math.floor(ms / 1000)
    const m = Math.floor(s / 60)
    const r = s % 60
    return `${m}:${String(r).padStart(2, '0')}`
  }

  return (
    <div style={{ 
      display: 'flex', 
      alignItems: 'center', 
      gap: 12, 
      padding: '8px 12px', 
      border: '1px solid #e5e7eb', 
      borderRadius: 10, 
      background: 'linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%)',
      boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{ 
          width: 20, 
          height: 20, 
          borderRadius: 4, 
          display: 'grid', 
          placeItems: 'center', 
          background: '#3b82f6', 
          color: '#fff',
          fontSize: 10,
          fontWeight: 600
        }}>⏱</div>
        <span style={{ fontSize: 13, fontWeight: 500, color: '#374151' }}>{fmt(totalMs)}</span>
      </div>
      
      <div style={{ width: 1, height: 18, background: '#d1d5db' }} />
      
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        {speakers.length > 0 ? speakers.map((s, i) => (
          <div key={`${s}-${i}`} style={{ 
            fontSize: 11, 
            fontWeight: 500,
            padding: '3px 8px', 
            borderRadius: 999, 
            background: i % 2 === 0 ? '#dbeafe' : '#ede9fe', 
            color: '#374151',
            border: '1px solid ' + (i % 2 === 0 ? '#93c5fd' : '#c4b5fd')
          }}>{s}</div>
        )) : (
          <div style={{ 
            fontSize: 11, 
            fontWeight: 500,
            padding: '3px 8px', 
            borderRadius: 999, 
            background: '#f3f4f6', 
            color: '#6b7280',
            border: '1px solid #d1d5db'
          }}>Two Speakers</div>
        )}
      </div>
      
      {parts.length > 0 && (
        <>
          <div style={{ width: 1, height: 18, background: '#d1d5db' }} />
          <div style={{ 
            fontSize: 11, 
            fontWeight: 500,
            color: '#6b7280',
            padding: '3px 8px',
            borderRadius: 999,
            background: '#f9fafb',
            border: '1px solid #e5e7eb'
          }}>
            {parts.length} Part{parts.length > 1 ? 's' : ''}
          </div>
        </>
      )}
    </div>
  )
}

type InsightsData = {
  key_insights: string[]
  did_you_know_facts: string[]
  counterpoints: string[]
  inspirations: string[]
  examples: string[]
  citations?: { filename?: string; page_number?: number; snippet?: string }[]
}

export default function App() {
  const [availableFiles, setAvailableFiles] = React.useState<string[]>([])
  const [currentFile, setCurrentFile] = React.useState<string | null>(null)
  const [filesRefreshTick, setFilesRefreshTick] = React.useState(0)
  const [recs, setRecs] = React.useState<Recommendation[]>([])
  const viewerApiRef = React.useRef<any>(null)
  const pendingPageRef = React.useRef<number | null>(null)
  const [adobeClientId, setAdobeClientId] = React.useState<string>('')
  const [lastSelection, setLastSelection] = React.useState<string>('')
  const [lastPage, setLastPage] = React.useState<number | null>(null)
  const [showInsights, setShowInsights] = React.useState(false)
  const [insightsData, setInsightsData] = React.useState<InsightsData | null>(null)
  const [insightsLoading, setInsightsLoading] = React.useState(false)
  const [insightsError, setInsightsError] = React.useState<string | null>(null)
  const [selectionPanelVisible, setSelectionPanelVisible] = React.useState(false)
  const selectionHideTimer = React.useRef<number | null>(null)
  const viewerContainerRef = React.useRef<HTMLDivElement | null>(null)
  const lastCopyTextRef = React.useRef<string>('')
  const lastCopyAtRef = React.useRef<number>(0)
  const [selectionPanelPos, setSelectionPanelPos] = React.useState<{ top: number; left: number } | null>(null)
  const [podcastReady, setPodcastReady] = React.useState(false)
  const [podcastMeta, setPodcastMeta] = React.useState<{ url: string; parts?: string[]; chapters?: any[] } | null>(null)
  const lastPointerRef = React.useRef<{ x: number; y: number; at: number }>({ x: 0, y: 0, at: 0 })
  const actionBtnRef = React.useRef<HTMLButtonElement | null>(null)

  const onUploaded = (filenames: string[]) => {
    const next = Array.from(new Set([ ...availableFiles, ...filenames ]))
    setAvailableFiles(next)
    if (filenames.length > 0) setCurrentFile(filenames[0])
    // Trigger FilePicker to refresh from backend
    setFilesRefreshTick((v) => v + 1)
  }

  // Load public config (Adobe client ID) from backend once
  React.useEffect(() => {
    const api = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')
    axios.get(`${api}/config/public`).then((res) => {
      const cid = res.data?.adobeClientId?.toString?.() || ''
      if (cid) setAdobeClientId(cid)
    }).catch(() => {
      // ignore, fallback to VITE var
    })
  }, [])

  React.useEffect(() => {
    if (!currentFile) return
    const adobeAny: any = (window as any)
  const render = () => {
  const clientId = adobeClientId || import.meta.env.VITE_ADOBE_CLIENT_ID || 'YOUR_ADOBE_CLIENT_ID'
      const view = new adobeAny.AdobeDC.View({ clientId, divId: 'adobe-dc-view' })
  const api = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')
  const url = `${api}/document_library/${encodeURIComponent(currentFile)}`
      const previewPromise = view.previewFile({
        content: { location: { url } },
        metaData: { fileName: currentFile },
      }, {})

      // Capture viewer APIs when ready (AdobeDC returns a viewer first; then get APIs)
      previewPromise
        .then((viewer: any) => {
          if (viewer && typeof viewer.getAPIs === 'function') {
            return viewer.getAPIs()
          }
          return null
        })
        .then((apis: any) => {
          if (apis) {
            viewerApiRef.current = apis
            if (pendingPageRef.current) {
              apis.gotoLocation({ pageNumber: pendingPageRef.current })
              pendingPageRef.current = null
            }
          } else {
            viewerApiRef.current = null
          }
        })

  // Listen for viewer events
      view.registerCallback(
        adobeAny.AdobeDC.View.Enum.CallbackType.EVENT_LISTENER,
        async (event: any) => {
          if (!currentFile) return
          try { console.debug('[PDF EVENT]', event?.type, event?.data) } catch {}
          const isSelectEvent = typeof event?.type === 'string' && event.type.toUpperCase().includes('SELECT')
          if (event?.type === 'TEXT_COPY' || isSelectEvent) {
            const text = event?.data?.text || event?.data?.copiedText || event?.data?.selectedText || event?.data?.selectionText || event?.data?.textSelection || ''
            if (text && text.trim().length > 0) {
      setLastSelection(text)
              setSelectionPanelVisible(true)
              // Try to anchor by actual selection rect, else fallback to last pointer
              if (!placePanelBySelectionRect()) {
                const { x, y } = lastPointerRef.current
                placePanelByClientXY(x, y)
              }
              // Auto-refresh recommendations for the selection
              try {
                const res = await axios.post(`${(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')}/recommendations`, { text, k: 5 })
                setRecs(res.data?.results ?? [])
              } catch (e) {
                console.error('Recommendations failed', e)
              }
            }
          } else if (event?.type === 'TEXT_DESELECTED' || event?.type === 'SELECTION_DESTROY') {
            setSelectionPanelVisible(false)
            setLastSelection('')
            setSelectionPanelPos(null)
          } else if ((event?.type || '').toString().toUpperCase() === 'PAGE_VIEW') {
            const page = event?.data?.pageNumber || event?.data?.pageNum || event?.pageNumber || event?.pageNum
            if (page) {
      setLastPage(page)
              // Hide panel on navigation
              setSelectionPanelVisible(false)
              setSelectionPanelPos(null)
              try {
                const res = await axios.post(`${(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')}/recommendations`, { filename: currentFile, page_number: page, k: 5 })
                setRecs(res.data?.results ?? [])
              } catch (e) {
                console.error('Recommendations failed', e)
              }
            }
          }
        },
        { enablePDFAnalytics: true }
      )
    }
  if (adobeAny && adobeAny.AdobeDC && adobeAny.AdobeDC.View) render()
  else document.addEventListener('adobe_dc_view_sdk.ready', render, { once: true })
  }, [currentFile, adobeClientId])

  // Helper to navigate to a page, deferring until APIs are ready if needed
  const gotoPage = React.useCallback((page: number) => {
    if (!page) return
    const apis = viewerApiRef.current
    if (apis && typeof apis.gotoLocation === 'function') {
      apis.gotoLocation({ pageNumber: page })
    } else {
      pendingPageRef.current = page
    }
  }, [])

  // Track last pointer position globally (approximate anchor when selection comes from iframe viewer)
  React.useEffect(() => {
    const onPointerUp = (e: any) => {
      const me = e as MouseEvent
      lastPointerRef.current = { x: me.clientX, y: me.clientY, at: Date.now() }
    }
    window.addEventListener('pointerup', onPointerUp, true)
    window.addEventListener('mouseup', onPointerUp, true)
    return () => {
      window.removeEventListener('pointerup', onPointerUp, true)
      window.removeEventListener('mouseup', onPointerUp, true)
    }
  }, [])

  const placePanelByClientXY = React.useCallback((clientX: number, clientY: number) => {
    const container = viewerContainerRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    let left = clientX - rect.left + 8
    let top = clientY - rect.top - 40
    // Clamp within container
    left = Math.max(8, Math.min(left, rect.width - 260))
    top = Math.max(8, Math.min(top, rect.height - 56))
    setSelectionPanelPos({ top, left })
  }, [])

  const placePanelBySelectionRect = React.useCallback(() => {
    const container = viewerContainerRef.current
    if (!container) return false
    try {
      const sel = window.getSelection()
      if (!sel || sel.rangeCount === 0) return false
      const r = sel.getRangeAt(0).getBoundingClientRect()
      if (!r || (r.width === 0 && r.height === 0)) return false
      const crect = container.getBoundingClientRect()
      const left = Math.max(8, Math.min(r.left - crect.left, crect.width - 260))
      const top = Math.max(8, Math.min(r.top - crect.top - 40, crect.height - 56))
      setSelectionPanelPos({ top, left })
      return true
    } catch {
      return false
    }
  }, [])

  // Document-level copy fallback: if user presses Ctrl/Cmd+C outside of the viewer's own events,
  // pick up the current selection text and trigger recommendations + show action panel.
  React.useEffect(() => {
    const onCopy = async () => {
      try {
        const text = (window.getSelection()?.toString() || '').trim()
        if (!text) return
        // De-duplicate rapid repeats (e.g., viewer TEXT_COPY may also fire)
        const now = Date.now()
        if (text === lastCopyTextRef.current && now - lastCopyAtRef.current < 1200) return
        lastCopyTextRef.current = text
        lastCopyAtRef.current = now
        setLastSelection(text)
        setSelectionPanelVisible(true)
        // Try to anchor by selection rect first; fallback to last pointer
        if (!placePanelBySelectionRect()) {
          const { x, y } = lastPointerRef.current
          placePanelByClientXY(x, y)
        }
        // Auto-refresh recommendations
        try {
          const res = await axios.post(`${(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')}/recommendations`, { text, k: 5 })
          setRecs(res.data?.results ?? [])
        } catch (e) {
          // ignore
        }
      } catch {
        // ignore
      }
    }
    document.addEventListener('copy', onCopy)
    return () => document.removeEventListener('copy', onCopy)
  }, [])

  // Auto-hide the selection action panel after a short delay when not used
  const pokeSelectionHideTimer = React.useCallback(() => {
    if (selectionHideTimer.current) {
      window.clearTimeout(selectionHideTimer.current)
      selectionHideTimer.current = null
    }
    selectionHideTimer.current = window.setTimeout(() => {
      setSelectionPanelVisible(false)
    }, 6000) as unknown as number
  }, [])

  React.useEffect(() => {
    if (selectionPanelVisible) pokeSelectionHideTimer()
    return () => {
      if (selectionHideTimer.current) {
        window.clearTimeout(selectionHideTimer.current)
        selectionHideTimer.current = null
      }
    }
  }, [selectionPanelVisible, pokeSelectionHideTimer])

  // (Selection-only handlers removed; we now use auto variants that fall back to current page.)

  // Auto variants: prefer selection, else fall back to current page
  const runInsightsAuto = React.useCallback(async () => {
    setInsightsError(null)
    setInsightsData(null)
    setInsightsLoading(true)
    try {
      const payload: any = {}
      if (lastSelection && lastSelection.trim().length > 0) {
        payload.text = lastSelection
      } else if (currentFile && (lastPage || lastPage === 0)) {
        payload.filename = currentFile
        payload.page_number = lastPage || 1
      } else if (currentFile) {
        payload.filename = currentFile
        payload.page_number = 1
      } else {
        throw new Error('No context available')
      }
      const res = await axios.post(`${(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')}/insights`, { ...payload, k: 5 })
      setInsightsData(res.data as InsightsData)
    } catch (e: any) {
      console.error('Insights failed', e)
      setInsightsError(e?.response?.data?.detail || e?.message || 'Insights failed')
    } finally {
      setInsightsLoading(false)
      setShowInsights(true)
    }
  }, [lastSelection, currentFile, lastPage])

  const runRecommendationsAuto = React.useCallback(async () => {
    try {
      if (lastSelection && lastSelection.trim().length > 0) {
        const res = await axios.post(`${(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')}/recommendations`, { text: lastSelection, k: 5 })
        setRecs(res.data?.results ?? [])
        return
      }
      if (currentFile && (lastPage || lastPage === 0)) {
        const res = await axios.post(`${(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')}/recommendations`, { filename: currentFile, page_number: lastPage || 1, k: 5 })
        setRecs(res.data?.results ?? [])
        return
      }
      if (currentFile) {
        const res = await axios.post(`${(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')}/recommendations`, { filename: currentFile, page_number: 1, k: 5 })
        setRecs(res.data?.results ?? [])
      }
    } catch (e) {
      console.error('Recommendations failed', e)
    }
  }, [lastSelection, currentFile, lastPage])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', fontFamily: 'Inter, system-ui, sans-serif' }}>
      {/* Header */}
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px', borderBottom: '1px solid #e5e7eb', background: '#ffffff' }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>Connecting the Dots</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <FilePicker
            currentFile={currentFile}
            onChange={(f) => setCurrentFile(f)}
            refreshKey={filesRefreshTick}
          />
          <button
            onClick={async () => {
              setInsightsError(null)
              setInsightsData(null)
              setInsightsLoading(true)
              try {
                const payload: any = {}
                if (lastSelection && lastSelection.trim().length > 0) {
                  payload.text = lastSelection
                } else if (currentFile && lastPage) {
                  payload.filename = currentFile
                  payload.page_number = lastPage
                } else if (currentFile) {
                  payload.filename = currentFile
                  payload.page_number = 1
                } else {
                  throw new Error('No context available')
                }
                const res = await axios.post(`${(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')}/insights`, { ...payload, k: 5 })
                setInsightsData(res.data as InsightsData)
              } catch (e: any) {
                console.error('Insights failed', e)
                setInsightsError(e?.response?.data?.detail || e?.message || 'Insights failed')
              } finally {
                setInsightsLoading(false)
                setShowInsights(true)
              }
            }}
            title="Get insights (from selection or current page)"
            style={{ padding: '8px 12px', borderRadius: 6, border: '1px solid #e5e7eb', background: '#fff', cursor: 'pointer' }}
          >
            💡 Insights
          </button>
          <UploadPdfButton onUploaded={onUploaded} />
        </div>
      </header>

      {/* Main content area: left (PDF viewer) + right (recommendations) */}
      <main style={{ display: 'flex', flex: 1, minHeight: 0, background: '#fafafa' }}>
        {/* PDF Viewer Column */}
        <section style={{ flex: 1, padding: 16, minWidth: 0 }}>
          <div ref={viewerContainerRef} style={{ position: 'relative', width: '100%', height: '100%' }}>
            <div
              id="adobe-dc-view"
              style={{ width: '100%', height: '100%', minHeight: 400, background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8 }}
            />

            {/* Always-available Actions button */}
            <button
              ref={actionBtnRef}
              title="Actions"
              onClick={() => {
                // Place panel near the button
                try {
                  const btn = actionBtnRef.current
                  const container = viewerContainerRef.current
                  if (btn && container) {
                    const b = btn.getBoundingClientRect()
                    const c = container.getBoundingClientRect()
                    const left = Math.max(8, Math.min(b.left - c.left - 8, c.width - 260))
                    const top = Math.max(8, Math.min(b.top - c.top - 8, c.height - 56))
                    setSelectionPanelPos({ top, left })
                  }
                } catch {}
                setSelectionPanelVisible(true)
              }}
              style={{
                position: 'absolute',
                right: 12,
                bottom: 12,
                padding: '8px 12px',
                borderRadius: 999,
                border: '1px solid #e5e7eb',
                background: '#ffffff',
                cursor: 'pointer',
                boxShadow: '0 6px 16px rgba(0,0,0,0.08)',
                zIndex: 2147483647,
              }}
            >
              ⚙️ Actions
            </button>

            {/* Floating selection actions */}
            {selectionPanelVisible && (
              <div
                onMouseEnter={pokeSelectionHideTimer}
                onMouseLeave={pokeSelectionHideTimer}
                style={{
                  position: 'absolute',
      left: selectionPanelPos ? selectionPanelPos.left : undefined,
      top: selectionPanelPos ? selectionPanelPos.top : undefined,
      right: selectionPanelPos ? undefined : 12,
      ...(selectionPanelPos ? {} : { top: 12 }),
                  display: 'flex',
                  gap: 8,
                  background: '#ffffff',
                  border: '1px solid #e5e7eb',
                  borderRadius: 999,
                  padding: '6px 8px',
                  boxShadow: '0 6px 16px rgba(0,0,0,0.08)',
                  alignItems: 'center',
                  zIndex: 2147483647,
                }}
              >
                <span style={{ maxWidth: 280, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', color: '#6b7280', fontSize: 12 }} title={lastSelection || (currentFile ? `${currentFile}${lastPage ? ` p.${lastPage}` : ''}` : 'Context')}>
                  {(lastSelection && lastSelection.trim().length > 0)
                    ? `“${lastSelection}”`
                    : (currentFile ? `${currentFile}${lastPage ? ` • p.${lastPage}` : ''}` : 'Context')}
                </span>
                <button
                  onClick={() => { runRecommendationsAuto(); pokeSelectionHideTimer() }}
                  title="Find related snippets (selection or current page)"
                  style={{ padding: '6px 10px', borderRadius: 999, border: '1px solid #e5e7eb', background: '#f9fafb', cursor: 'pointer' }}
                >
                  🔎 Recommend
                </button>
                <button
                  onClick={() => { runInsightsAuto(); pokeSelectionHideTimer() }}
                  title="Analyze (selection or current page)"
                  style={{ padding: '6px 10px', borderRadius: 999, border: '1px solid #e5e7eb', background: '#f9fafb', cursor: 'pointer' }}
                >
                  💡 Insights
                </button>
                <button
                  onClick={() => { setSelectionPanelVisible(false) }}
                  aria-label="Close"
                  title="Close"
                  style={{ background: 'transparent', border: 'none', fontSize: 16, lineHeight: 1, cursor: 'pointer', color: '#6b7280' }}
                >
                  ✖
                </button>
              </div>
            )}
          </div>
        </section>

        {/* Right Column: Recommendations + Podcast */}
        <div style={{ 
          width: 380, 
          display: 'flex', 
          flexDirection: 'column', 
          borderLeft: '1px solid #e5e7eb', 
          background: '#ffffff',
          height: '100%'
        }}>
          {/* Recommendations Section */}
          <div style={{ 
            flex: 1, 
            minHeight: 0,
            border: '2px solid #e2e8f0',
            borderRadius: '12px 12px 0 0',
            margin: '8px 8px 4px 8px',
            background: '#ffffff',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden'
          }}>
            <div style={{
              padding: '12px 16px',
              borderBottom: '1px solid #f1f5f9',
              background: 'linear-gradient(135deg, #fefefe 0%, #f8fafc 100%)',
              borderRadius: '10px 10px 0 0'
            }}>
              <h3 style={{ 
                margin: 0, 
                fontSize: 14, 
                fontWeight: 700, 
                color: '#374151',
                letterSpacing: '-0.025em'
              }}>
                📋 Recommendations
              </h3>
            </div>
            <div style={{ 
              flex: 1, 
              overflow: 'auto',
              padding: '8px'
            }}>
              <RecommendationsSidebar
                items={recs}
                onClickItem={(item) => {
                  if (item.filename && item.filename !== currentFile) {
                    pendingPageRef.current = item.page_number ?? null
                    setCurrentFile(item.filename)
                    return
                  }
                  if (item.page_number) gotoPage(item.page_number)
                }}
              />
            </div>
          </div>

          {/* Podcast Section */}
          <div style={{
            flex: 1,
            minHeight: 0,
            border: '2px solid #e2e8f0',
            borderRadius: '0 0 12px 12px',
            margin: '4px 8px 8px 8px',
            background: '#ffffff',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden'
          }}>
            {/* Modern Header */}
            <div style={{ 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'space-between', 
              padding: '12px 16px', 
              gap: 12,
              borderBottom: '1px solid #f1f5f9',
              background: 'linear-gradient(135deg, #fefefe 0%, #f8fafc 100%)',
              borderRadius: '10px 10px 0 0'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
                <div style={{ 
                  width: 32, 
                  height: 32, 
                  borderRadius: 10, 
                  display: 'grid', 
                  placeItems: 'center', 
                  background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', 
                  color: '#fff',
                  fontSize: 16,
                  boxShadow: '0 2px 8px rgba(102, 126, 234, 0.3)'
                }}>🎙️</div>
                <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                  <div style={{ 
                    fontWeight: 700, 
                    fontSize: 15, 
                    color: '#111827', 
                    lineHeight: 1.2,
                    letterSpacing: '-0.025em'
                  }}>Podcast Studio</div>
                  <div style={{ 
                    fontSize: 12, 
                    color: '#6b7280', 
                    whiteSpace: 'nowrap', 
                    textOverflow: 'ellipsis', 
                    overflow: 'hidden',
                    fontWeight: 400
                  }}>
                    {podcastReady ? 'AI-generated conversation' : 'Transform content into dialogue'}
                  </div>
                </div>
              </div>
              
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {podcastReady && (
                  <div style={{
                    padding: '4px 8px',
                    borderRadius: 999,
                    background: '#dcfce7',
                    border: '1px solid #16a34a',
                    fontSize: 11,
                    fontWeight: 600,
                    color: '#15803d'
                  }}>Ready</div>
                )}
                <GenerateAudioButton
                  getContext={async () => {
                    if (lastSelection && lastSelection.trim().length > 0) {
                      return { text: lastSelection }
                    }
                    if (currentFile && lastPage) {
                      return { filename: currentFile, page_number: lastPage }
                    }
                    if (currentFile) {
                      return { filename: currentFile, page_number: 1 }
                    }
                    throw new Error('No context available')
                  }}
                  onGenerated={(data) => { setPodcastMeta(data); setPodcastReady(true) }}
                />
              </div>
            </div>

            {/* Body with improved layout and scrolling */}
            <div style={{ 
              padding: 16, 
              display: 'flex', 
              flexDirection: 'column', 
              gap: 12, 
              flex: 1, 
              minHeight: 0,
              background: '#fafafa',
              overflow: 'auto'
            }}>
              {!podcastMeta && (
                <div style={{ 
                  flex: 1, 
                  display: 'grid', 
                  placeItems: 'center', 
                  textAlign: 'center',
                  padding: '20px 16px'
                }}>
                  <div style={{
                    background: '#ffffff',
                    border: '1px solid #e5e7eb',
                    borderRadius: 16,
                    padding: '32px 24px',
                    boxShadow: '0 4px 6px rgba(0, 0, 0, 0.05)',
                    maxWidth: 280
                  }}>
                    <div style={{ 
                      fontSize: 48, 
                      marginBottom: 16,
                      filter: 'grayscale(0.2)'
                    }}>🎧</div>
                    <div style={{ 
                      fontSize: 16, 
                      fontWeight: 600,
                      color: '#111827',
                      marginBottom: 8,
                      lineHeight: 1.4
                    }}>Create Your Podcast</div>
                    <div style={{ 
                      fontSize: 13, 
                      color: '#6b7280', 
                      marginBottom: 20,
                      lineHeight: 1.5
                    }}>
                      Generate an AI conversation between two speakers from your selected content or current page.
                    </div>
                    <div style={{
                      fontSize: 12,
                      color: '#9ca3af',
                      fontStyle: 'italic'
                    }}>
                      Use the "🎙️ Narrate" button above to get started
                    </div>
                  </div>
                </div>
              )}

              {podcastMeta && (
                <div style={{
                  background: '#ffffff',
                  border: '1px solid #e5e7eb',
                  borderRadius: 12,
                  overflow: 'hidden',
                  boxShadow: '0 4px 6px rgba(0, 0, 0, 0.05)',
                  flex: 1,
                  display: 'flex',
                  flexDirection: 'column',
                  minHeight: 0
                }}>
                  <div style={{ padding: 12, borderBottom: '1px solid #f1f5f9' }}>
                    <PodcastMetaStrip meta={podcastMeta} />
                  </div>
                  <div style={{ flex: 1, minHeight: 0, padding: 12 }}>
                    <PodcastStudio meta={podcastMeta} />
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>

      {/* Insights Modal */}
      {showInsights && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16
          }}
          onClick={() => setShowInsights(false)}
        >
          <div
            style={{ width: 'min(800px, 95vw)', maxHeight: '85vh', overflow: 'auto', background: '#fff', borderRadius: 10, border: '1px solid #e5e7eb', padding: 16 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <h2 style={{ margin: 0, fontSize: 18 }}>Insights</h2>
              <button onClick={() => setShowInsights(false)} style={{ background: 'transparent', border: 'none', fontSize: 18, cursor: 'pointer' }}>✖</button>
            </div>

            {insightsLoading && <div>Analyzing…</div>}
            {insightsError && <div style={{ color: '#b91c1c' }}>Error: {insightsError}</div>}

            {insightsData && (
              <div style={{ display: 'grid', gap: 12 }}>
                <section>
                  <h3 style={{ margin: '8px 0' }}>Key insights</h3>
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {insightsData.key_insights?.map((s, i) => <li key={`ins-${i}`}>{s}</li>)}
                  </ul>
                </section>
                <section>
                  <h3 style={{ margin: '8px 0' }}>Did you know?</h3>
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {insightsData.did_you_know_facts?.map((s, i) => <li key={`fact-${i}`}>{s}</li>)}
                  </ul>
                </section>
                <section>
                  <h3 style={{ margin: '8px 0' }}>Counterpoints</h3>
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {insightsData.counterpoints?.map((s, i) => <li key={`con-${i}`}>{s}</li>)}
                  </ul>
                </section>
                <section>
                  <h3 style={{ margin: '8px 0' }}>Inspirations</h3>
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {insightsData.inspirations?.map((s, i) => <li key={`insp-${i}`}>{s}</li>)}
                  </ul>
                </section>
                <section>
                  <h3 style={{ margin: '8px 0' }}>Examples</h3>
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {insightsData.examples?.map((s, i) => <li key={`ex-${i}`}>{s}</li>)}
                  </ul>
                </section>
                {insightsData.citations && insightsData.citations.length > 0 && (
                  <section>
                    <h3 style={{ margin: '8px 0' }}>Citations</h3>
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {insightsData.citations.map((c, i) => (
                        <li key={`cit-${i}`}>
                          <button
                            onClick={() => {
                              if (!c) return
                              if (c.filename && c.filename !== currentFile) {
                                pendingPageRef.current = c.page_number ?? null
                                setCurrentFile(c.filename)
                              } else if (c.page_number) {
                                gotoPage(c.page_number)
                              }
                            }}
                            style={{ background: 'transparent', border: 'none', color: '#2563eb', cursor: 'pointer', padding: 0 }}
                            title={`Open ${c.filename || ''} p.${c.page_number || ''}`}
                          >
                            {c.filename || 'document'} p.{c.page_number}
                          </button>
                          {c.snippet && <div style={{ color: '#6b7280', fontSize: 12, marginTop: 2 }}>{c.snippet}</div>}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
