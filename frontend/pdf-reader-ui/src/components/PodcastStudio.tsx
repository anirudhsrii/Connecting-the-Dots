import React from 'react'

// Add keyframe animations
const pulseKeyframes = `
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
`

type Props = {
	meta: { url: string; parts?: string[]; chapters?: Array<{ index: number; speaker: string; text: string; start_ms?: number; end_ms?: number; part_url?: string }> }
}

export default function PodcastStudio({ meta }: Props) {
	// Add CSS animations to document head
	React.useEffect(() => {
		const style = document.createElement('style')
		style.textContent = pulseKeyframes
		document.head.appendChild(style)
		return () => {
			document.head.removeChild(style)
		}
	}, [])

	const audioRef = React.useRef<HTMLAudioElement | null>(null)
	const api = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')
	const mergedSrc = meta.url.startsWith('http') ? meta.url : `${api}${meta.url}`

	const [currentSrc, setCurrentSrc] = React.useState<string>(mergedSrc)
	const [duration, setDuration] = React.useState<number>(0)
	const [currentTime, setCurrentTime] = React.useState<number>(0)
	const [playing, setPlaying] = React.useState<boolean>(false)
	const [activeChapter, setActiveChapter] = React.useState<number | null>(null)
	const [playbackRate, setPlaybackRate] = React.useState<number>(1)
	const [isPartMode, setIsPartMode] = React.useState<boolean>(false)
	const [errorMsg, setErrorMsg] = React.useState<string | null>(null)
	const [showTranscript, setShowTranscript] = React.useState<boolean>(true)
	const [transcriptMode, setTranscriptMode] = React.useState<'chapters' | 'fullText'>('chapters')
	const [volume, setVolume] = React.useState<number>(1)
	const [isMinimized, setIsMinimized] = React.useState<boolean>(false)
	const [showSubtitles, setShowSubtitles] = React.useState<boolean>(true)
	const [subtitleSize, setSubtitleSize] = React.useState<'small' | 'medium' | 'large'>('medium')
	const activeChapterRef = React.useRef<HTMLDivElement | null>(null)

	const chapters = Array.isArray(meta.chapters) ? meta.chapters : []

	// Get current subtitle text based on playback time
	const getCurrentSubtitle = () => {
		if (!chapters.length || isPartMode) return null
		const tms = currentTime * 1000
		for (let i = 0; i < chapters.length; i++) {
			const c = chapters[i]
			const start = typeof c.start_ms === 'number' ? c.start_ms : null
			const end = typeof c.end_ms === 'number' ? c.end_ms : null
			if (start !== null && end !== null && tms >= start && tms < end) {
				return { text: c.text, speaker: c.speaker || 'Unknown Speaker' }
			}
		}
		return null
	}

	const currentSubtitle = getCurrentSubtitle()

	// Generate full transcript text from chapters
	const generateFullTranscript = () => {
		if (!chapters.length) return 'No transcript available.'
		
		return chapters.map((c) => {
			const timestamp = typeof c.start_ms === 'number' ? 
				`${Math.floor(c.start_ms/1000/60)}:${String(Math.floor(c.start_ms/1000)%60).padStart(2,'0')}` : 
				'--:--'
			const speaker = (c.speaker || 'Unknown Speaker').toString().trim()
			return `[${timestamp}] ${speaker}: ${c.text}`
		}).join('\n\n')
	}

	const fmt = (sec: number) => {
		const s = Math.max(0, Math.floor(sec || 0))
		const m = Math.floor(s / 60)
		const r = s % 60
		return `${m}:${String(r).padStart(2, '0')}`
	}

	React.useEffect(() => {
		const el = audioRef.current
		if (!el) return
		const onLoaded = () => setDuration(el.duration || 0)
		const onTime = () => setCurrentTime(el.currentTime || 0)
		const onPlay = () => setPlaying(true)
		const onPause = () => setPlaying(false)
		const onError = () => {
			try {
				// Provide a helpful error and link to open directly
				const mediaErr = (el as any)?.error
				setErrorMsg(mediaErr ? `Audio error ${mediaErr.code || ''}` : 'Audio failed to load')
			} catch { setErrorMsg('Audio failed to load') }
		}
			const onEnded = () => {
				// If playing a part file, auto-advance to next chapter
				if (!chapters.length) return
				if (isPartMode && activeChapter != null) {
					const nextIdx = Math.min(chapters.length - 1, activeChapter + 1)
					if (nextIdx !== activeChapter) playChapter(chapters[nextIdx], nextIdx)
				}
			}
		el.addEventListener('loadedmetadata', onLoaded)
		el.addEventListener('timeupdate', onTime)
		el.addEventListener('play', onPlay)
		el.addEventListener('pause', onPause)
		el.addEventListener('error', onError)
			el.addEventListener('ended', onEnded)
		return () => {
			el.removeEventListener('loadedmetadata', onLoaded)
			el.removeEventListener('timeupdate', onTime)
			el.removeEventListener('play', onPlay)
			el.removeEventListener('pause', onPause)
			el.removeEventListener('error', onError)
				el.removeEventListener('ended', onEnded)
		}
	}, [])

		// Highlight active chapter based on current time (only when playing merged audio)
	React.useEffect(() => {
			if (!chapters.length || isPartMode) return
		const tms = currentTime * 1000
		let idx: number | null = null
		for (let i = 0; i < chapters.length; i++) {
			const c = chapters[i]
			const start = typeof c.start_ms === 'number' ? c.start_ms : null
			const end = typeof c.end_ms === 'number' ? c.end_ms : null
			if (start !== null && end !== null && tms >= start && tms < end) {
				idx = i
				break
			}
		}
		setActiveChapter(idx)
		}, [currentTime, chapters, isPartMode])

	// Auto-scroll to active chapter when in transcript mode
	React.useEffect(() => {
		if (showTranscript && transcriptMode === 'chapters' && activeChapter !== null && activeChapterRef.current) {
			activeChapterRef.current.scrollIntoView({
				behavior: 'smooth',
				block: 'center'
			})
		}
	}, [activeChapter, showTranscript, transcriptMode])

	const ensurePlay = () => {
		const el = audioRef.current
		if (!el) {
			console.error('Audio element not found')
			return
		}
		console.log('Attempting to play audio:', el.src)
		setTimeout(() => { 
			el.play().catch((error) => {
				console.error('Play failed:', error)
				setErrorMsg(`Playback failed: ${error.message}`)
			}) 
		}, 0)
	}

		const playPause = () => {
		const el = audioRef.current
		if (!el) {
			console.error('Audio element not found for playPause')
			return
		}
		console.log('Play/Pause clicked, current state:', el.paused ? 'paused' : 'playing')
		if (el.paused) {
			el.play().catch((error) => {
				console.error('Play failed in playPause:', error)
				setErrorMsg(`Playback failed: ${error.message}`)
			})
		} else {
			el.pause()
		}
	}

	const seek = (s: number) => {
		const el = audioRef.current
		if (!el) return
		el.currentTime = Math.max(0, Math.min(s, duration || s))
	}

	// When the mergedSrc changes (new generation), reset the player source cleanly
	React.useEffect(() => {
		setErrorMsg(null)
		setPlaying(false)
		setCurrentSrc(mergedSrc)
		const el = audioRef.current
		if (el) {
			try {
				el.pause()
				el.src = mergedSrc
				el.load()
			} catch {}
		}
	}, [mergedSrc])

		const playChapter = (c: any, idx?: number) => {
		const el = audioRef.current
		if (!el) {
			console.error('Audio element not found for playChapter')
			return
		}
		console.log('Playing chapter:', c, 'index:', idx)
		const p = c?.part_url
		if (p) {
			const abs = p.startsWith('http') ? p : `${api}${p}`
			console.log('Playing chapter part:', abs)
			setCurrentSrc(abs)
			el.src = abs
				setIsPartMode(true)
				if (typeof idx === 'number') setActiveChapter(idx)
			ensurePlay()
			return
		}
		if (typeof c?.start_ms === 'number') {
			console.log('Seeking to timestamp:', c.start_ms)
				setIsPartMode(false)
			if (currentSrc !== mergedSrc) {
				console.log('Loading merged audio and seeking')
				setCurrentSrc(mergedSrc)
				el.src = mergedSrc
				el.onloadeddata = () => {
					el.currentTime = (c.start_ms || 0) / 1000
					ensurePlay()
				}
				el.load()
			} else {
				console.log('Seeking in current audio')
				el.currentTime = (c.start_ms || 0) / 1000
				ensurePlay()
			}
				if (typeof idx === 'number') setActiveChapter(idx)
		} else {
			console.warn('Chapter has no start_ms or part_url:', c)
		}
	}

	const gotoPrev = () => {
		if (!chapters.length) return
			const idx = activeChapter == null ? 0 : Math.max(0, activeChapter - 1)
			playChapter(chapters[idx], idx)
	}
	const gotoNext = () => {
		if (!chapters.length) return
			const idx = activeChapter == null ? 0 : Math.min(chapters.length - 1, activeChapter + 1)
			playChapter(chapters[idx], idx)
	}

		const skip = (deltaSec: number) => {
			const el = audioRef.current
			if (!el) return
			el.currentTime = Math.max(0, Math.min((el.currentTime || 0) + deltaSec, duration || (el.currentTime || 0) + deltaSec))
		}

		// Apply playback rate
		React.useEffect(() => {
			const el = audioRef.current
			if (!el) return
			try { el.playbackRate = playbackRate } catch {}
		}, [playbackRate])

		// Keyboard shortcuts: Space (play/pause), [ / ] skip, , / . prev/next chapter
		React.useEffect(() => {
			const onKey = (e: KeyboardEvent) => {
				const tag = (e.target as HTMLElement)?.tagName?.toLowerCase()
				if (tag === 'input' || tag === 'textarea' || (e as any).isComposing) return
				if (e.code === 'Space') { e.preventDefault(); playPause(); }
				else if (e.key === '[') { e.preventDefault(); skip(-15); }
				else if (e.key === ']') { e.preventDefault(); skip(15); }
				else if (e.key === ',') { e.preventDefault(); gotoPrev(); }
				else if (e.key === '.') { e.preventDefault(); gotoNext(); }
			}
			window.addEventListener('keydown', onKey)
			return () => window.removeEventListener('keydown', onKey)
		}, [playPause, gotoPrev, gotoNext])

	return (
		<div style={{ 
			display: 'flex', 
			flexDirection: 'column', 
			gap: 0, 
			minHeight: 0, 
			height: '100%',
			background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
			borderRadius: 16,
			overflow: 'hidden',
			boxShadow: '0 20px 40px rgba(0,0,0,0.1)'
		}}>
			{/* Modern Header */}
			<div style={{
				background: 'rgba(255,255,255,0.1)',
				backdropFilter: 'blur(10px)',
				padding: '16px 24px',
				borderBottom: '1px solid rgba(255,255,255,0.2)',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'space-between'
			}}>
				<div style={{
					display: 'flex',
					alignItems: 'center',
					gap: 12
				}}>
					<div style={{
						width: 40,
						height: 40,
						borderRadius: '50%',
						background: 'linear-gradient(45deg, #ff6b6b, #feca57)',
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						fontSize: 18
					}}>🎧</div>
					<div>
						<h2 style={{
							margin: 0,
							fontSize: 18,
							fontWeight: 700,
							color: '#fff',
							letterSpacing: '-0.025em'
						}}>Podcast Studio</h2>
						<p style={{
							margin: 0,
							fontSize: 12,
							color: 'rgba(255,255,255,0.8)',
							fontWeight: 500
						}}>AI-Generated Content Player</p>
					</div>
				</div>
				
				<div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
					<button
						onClick={() => setIsMinimized(!isMinimized)}
						title={isMinimized ? 'Expand' : 'Minimize'}
						style={{
							background: 'rgba(255,255,255,0.2)',
							border: 'none',
							borderRadius: 8,
							padding: '8px 12px',
							color: '#fff',
							cursor: 'pointer',
							fontSize: 12,
							fontWeight: 600,
							backdropFilter: 'blur(10px)',
							transition: 'all 0.2s ease'
						}}
					>
						{isMinimized ? '↗️' : '↙️'}
					</button>
				</div>
			</div>

			{!isMinimized && (
				<>
					{/* Live Subtitle Display */}
					{showSubtitles && currentSubtitle && (
						<div style={{
							background: 'rgba(0,0,0,0.8)',
							backdropFilter: 'blur(10px)',
							margin: '16px 24px',
							padding: '16px 20px',
							borderRadius: 12,
							border: '1px solid rgba(255,255,255,0.1)',
							position: 'relative',
							overflow: 'hidden'
						}}>
							<div style={{
								position: 'absolute',
								top: 0,
								left: 0,
								right: 0,
								height: 2,
								background: 'linear-gradient(90deg, #ff6b6b, #4ecdc4)',
								borderRadius: '2px 2px 0 0'
							}} />
							<div style={{
								display: 'flex',
								alignItems: 'center',
								gap: 12,
								marginBottom: 8
							}}>
								<div style={{
									fontSize: 10,
									fontWeight: 700,
									color: '#4ecdc4',
									textTransform: 'uppercase',
									letterSpacing: '0.1em'
								}}>LIVE SUBTITLE</div>
								<div style={{
									padding: '2px 8px',
									background: 'rgba(78, 205, 196, 0.2)',
									borderRadius: 12,
									fontSize: 10,
									fontWeight: 600,
									color: '#4ecdc4',
									textTransform: 'capitalize'
								}}>
									{currentSubtitle.speaker}
								</div>
							</div>
							<div style={{
								fontSize: subtitleSize === 'small' ? 14 : subtitleSize === 'large' ? 18 : 16,
								lineHeight: 1.6,
								color: '#fff',
								fontWeight: 500,
								fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto',
								textShadow: '0 1px 2px rgba(0,0,0,0.5)'
							}}>
								{currentSubtitle.text}
							</div>
						</div>
					)}

					{/* Main Player Controls */}
					<div style={{
						background: 'rgba(255,255,255,0.95)',
						backdropFilter: 'blur(10px)',
						margin: '0 24px 16px',
						padding: '20px 24px',
						borderRadius: 16,
						boxShadow: '0 8px 32px rgba(0,0,0,0.1)',
						border: '1px solid rgba(255,255,255,0.2)'
					}}>
						{/* Progress Bar */}
						<div style={{ marginBottom: 20 }}>
							<div style={{
								display: 'flex',
								justifyContent: 'space-between',
								alignItems: 'center',
								marginBottom: 8
							}}>
								<span style={{
									fontSize: 12,
									fontWeight: 600,
									color: '#6b7280',
									fontVariantNumeric: 'tabular-nums'
								}}>{fmt(currentTime)}</span>
								<span style={{
									fontSize: 12,
									fontWeight: 600,
									color: '#6b7280',
									fontVariantNumeric: 'tabular-nums'
								}}>{fmt(duration)}</span>
							</div>
							<div style={{
								position: 'relative',
								height: 8,
								background: '#e5e7eb',
								borderRadius: 4,
								overflow: 'hidden',
								cursor: 'pointer'
							}} onClick={(e) => {
								const rect = e.currentTarget.getBoundingClientRect()
								const pos = (e.clientX - rect.left) / rect.width
								seek(pos * duration)
							}}>
								<div style={{
									position: 'absolute',
									top: 0,
									left: 0,
									height: '100%',
									width: `${duration > 0 ? (currentTime / duration) * 100 : 0}%`,
									background: 'linear-gradient(90deg, #667eea, #764ba2)',
									borderRadius: 4,
									transition: 'width 0.1s ease'
								}} />
								{/* Chapter markers */}
								{chapters.map((c, i) => {
									if (typeof c.start_ms !== 'number' || !duration) return null
									const pos = (c.start_ms / 1000) / duration * 100
									return (
										<div
											key={i}
											style={{
												position: 'absolute',
												top: -2,
												left: `${pos}%`,
												width: 2,
												height: 12,
												background: '#ff6b6b',
												borderRadius: 1,
												transform: 'translateX(-50%)'
											}}
										/>
									)
								})}
							</div>
						</div>

						{/* Transport Controls */}
						<div style={{
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							gap: 16,
							marginBottom: 16
						}}>
							<button 
								onClick={gotoPrev} 
								title="Previous chapter"
								style={{
									width: 44,
									height: 44,
									borderRadius: '50%',
									border: 'none',
									background: 'linear-gradient(135deg, #f3f4f6, #e5e7eb)',
									cursor: 'pointer',
									fontSize: 16,
									color: '#374151',
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'center',
									boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
									transition: 'all 0.2s ease'
								}}
								onMouseEnter={(e) => {
									e.currentTarget.style.transform = 'scale(1.1)'
									e.currentTarget.style.boxShadow = '0 6px 20px rgba(0,0,0,0.2)'
								}}
								onMouseLeave={(e) => {
									e.currentTarget.style.transform = 'scale(1)'
									e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)'
								}}
							>⏮</button>
							
							<button 
								onClick={() => skip(-15)} 
								title="Back 15s"
								style={{
									width: 40,
									height: 40,
									borderRadius: '50%',
									border: 'none',
									background: 'rgba(107, 114, 128, 0.1)',
									cursor: 'pointer',
									fontSize: 12,
									fontWeight: 600,
									color: '#6b7280',
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'center',
									transition: 'all 0.2s ease'
								}}
							>-15</button>
							
							<button 
								onClick={playPause} 
								title={playing ? 'Pause' : 'Play'}
								style={{
									width: 64,
									height: 64,
									borderRadius: '50%',
									border: 'none',
									background: playing ? 
										'linear-gradient(135deg, #ef4444, #dc2626)' : 
										'linear-gradient(135deg, #10b981, #059669)',
									cursor: 'pointer',
									fontSize: 24,
									color: '#fff',
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'center',
									boxShadow: '0 8px 25px rgba(59, 130, 246, 0.4)',
									transition: 'all 0.3s ease',
									transform: playing ? 'scale(1.05)' : 'scale(1)'
								}}
								onMouseEnter={(e) => {
									e.currentTarget.style.transform = playing ? 'scale(1.1)' : 'scale(1.05)'
									e.currentTarget.style.boxShadow = '0 10px 30px rgba(59, 130, 246, 0.5)'
								}}
								onMouseLeave={(e) => {
									e.currentTarget.style.transform = playing ? 'scale(1.05)' : 'scale(1)'
									e.currentTarget.style.boxShadow = '0 8px 25px rgba(59, 130, 246, 0.4)'
								}}
							>
								{playing ? '⏸️' : '▶️'}
							</button>
							
							<button 
								onClick={() => skip(15)} 
								title="Forward 15s"
								style={{
									width: 40,
									height: 40,
									borderRadius: '50%',
									border: 'none',
									background: 'rgba(107, 114, 128, 0.1)',
									cursor: 'pointer',
									fontSize: 12,
									fontWeight: 600,
									color: '#6b7280',
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'center',
									transition: 'all 0.2s ease'
								}}
							>+15</button>
							
							<button 
								onClick={gotoNext} 
								title="Next chapter"
								style={{
									width: 44,
									height: 44,
									borderRadius: '50%',
									border: 'none',
									background: 'linear-gradient(135deg, #f3f4f6, #e5e7eb)',
									cursor: 'pointer',
									fontSize: 16,
									color: '#374151',
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'center',
									boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
									transition: 'all 0.2s ease'
								}}
								onMouseEnter={(e) => {
									e.currentTarget.style.transform = 'scale(1.1)'
									e.currentTarget.style.boxShadow = '0 6px 20px rgba(0,0,0,0.2)'
								}}
								onMouseLeave={(e) => {
									e.currentTarget.style.transform = 'scale(1)'
									e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)'
								}}
							>⏭</button>
						</div>

						{/* Secondary Controls */}
						<div style={{
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'space-between',
							gap: 16
						}}>
							<div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
								<span style={{ fontSize: 12, fontWeight: 600, color: '#6b7280' }}>Speed:</span>
								<select
									value={String(playbackRate)}
									onChange={(e) => setPlaybackRate(parseFloat(e.target.value))}
									style={{
										fontSize: 12,
										fontWeight: 600,
										border: '1px solid #d1d5db',
										borderRadius: 8,
										padding: '6px 8px',
										background: '#fff',
										cursor: 'pointer'
									}}
								>
									<option value="0.75">0.75×</option>
									<option value="1">1×</option>
									<option value="1.25">1.25×</option>
									<option value="1.5">1.5×</option>
									<option value="2">2×</option>
								</select>
							</div>
							
							<div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
								<span style={{ fontSize: 12, fontWeight: 600, color: '#6b7280' }}>Volume:</span>
								<input
									type="range"
									min={0}
									max={1}
									step={0.1}
									value={volume}
									onChange={(e) => {
										const vol = parseFloat(e.target.value)
										setVolume(vol)
										if (audioRef.current) audioRef.current.volume = vol
									}}
									style={{
										width: 80,
										height: 4,
										borderRadius: 2,
										background: '#e5e7eb',
										outline: 'none',
										cursor: 'pointer'
									}}
								/>
							</div>
							
							<div style={{ display: 'flex', gap: 8 }}>
								<button
									onClick={() => setShowSubtitles(!showSubtitles)}
									title="Toggle subtitles"
									style={{
										padding: '6px 12px',
										borderRadius: 8,
										border: '1px solid #d1d5db',
										background: showSubtitles ? '#3b82f6' : '#fff',
										color: showSubtitles ? '#fff' : '#374151',
										cursor: 'pointer',
										fontSize: 12,
										fontWeight: 600,
										transition: 'all 0.2s ease'
									}}
								>📝</button>
								
								<a 
									href={currentSrc} 
									target="_blank" 
									rel="noreferrer" 
									title="Download audio"
									style={{
										padding: '6px 12px',
										borderRadius: 8,
										border: '1px solid #d1d5db',
										background: '#f9fafb',
										color: '#374151',
										textDecoration: 'none',
										fontSize: 12,
										fontWeight: 600,
										transition: 'all 0.2s ease'
									}}
								>⬇️</a>
							</div>
						</div>
					</div>

					{/* Subtitle Settings */}
					{showSubtitles && (
						<div style={{
							background: 'rgba(255,255,255,0.9)',
							backdropFilter: 'blur(10px)',
							margin: '0 24px 16px',
							padding: '16px 20px',
							borderRadius: 12,
							border: '1px solid rgba(255,255,255,0.2)'
						}}>
							<div style={{
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'space-between'
							}}>
								<span style={{
									fontSize: 13,
									fontWeight: 700,
									color: '#374151'
								}}>Subtitle Settings</span>
								
								<div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
									<span style={{ fontSize: 12, color: '#6b7280' }}>Size:</span>
									<select
										value={subtitleSize}
										onChange={(e) => setSubtitleSize(e.target.value as 'small' | 'medium' | 'large')}
										style={{
											fontSize: 12,
											padding: '4px 8px',
											border: '1px solid #d1d5db',
											borderRadius: 6,
											background: '#fff'
										}}
									>
										<option value="small">Small</option>
										<option value="medium">Medium</option>
										<option value="large">Large</option>
									</select>
								</div>
							</div>
						</div>
					)}

					{/* Audio Element */}
					<audio ref={audioRef} src={currentSrc} crossOrigin="anonymous" preload="metadata" style={{ display: 'none' }} />

					{/* Error Display */}
					{errorMsg && (
						<div style={{
							margin: '0 24px 16px',
							padding: '16px 20px',
							borderRadius: 12,
							border: '1px solid #fecaca',
							background: 'rgba(254, 242, 242, 0.95)',
							backdropFilter: 'blur(10px)',
							color: '#991b1b',
							fontSize: 13,
							display: 'flex',
							alignItems: 'center',
							gap: 12,
							flexWrap: 'wrap'
						}}>
							<span style={{ fontWeight: 600 }}>⚠️ {errorMsg}</span>
							<a href={currentSrc} target="_blank" rel="noreferrer" style={{ 
								fontWeight: 700, 
								color: '#b91c1c',
								textDecoration: 'underline'
							}}>Open Audio Directly</a>
						</div>
					)}

					{/* Enhanced Transcript & Chapters */}
					{chapters.length > 0 && (
						<div style={{
							background: 'rgba(255,255,255,0.95)',
							backdropFilter: 'blur(10px)',
							margin: '0 24px 24px',
							borderRadius: 16,
							overflow: 'hidden',
							boxShadow: '0 8px 32px rgba(0,0,0,0.1)',
							border: '1px solid rgba(255,255,255,0.2)',
							flex: 1,
							display: 'flex',
							flexDirection: 'column'
						}}>
							{/* Transcript Header */}
							<div style={{
								padding: '20px 24px',
								borderBottom: '1px solid #e5e7eb',
								background: 'linear-gradient(135deg, #f8fafc, #f1f5f9)'
							}}>
								<div style={{
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'space-between',
									marginBottom: 12
								}}>
									<div style={{
										display: 'flex',
										alignItems: 'center',
										gap: 12
									}}>
										<div style={{
											width: 32,
											height: 32,
											borderRadius: '50%',
											background: 'linear-gradient(45deg, #4ecdc4, #44a08d)',
											display: 'flex',
											alignItems: 'center',
											justifyContent: 'center',
											fontSize: 14
										}}>📄</div>
										<div>
											<h3 style={{
												margin: 0,
												fontSize: 16,
												fontWeight: 700,
												color: '#374151',
												letterSpacing: '-0.025em'
											}}>Interactive Transcript</h3>
											<p style={{
												margin: 0,
												fontSize: 12,
												color: '#6b7280',
												fontWeight: 500
											}}>{chapters.length} chapters • Click to jump to section</p>
										</div>
									</div>
									
									<div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
										<button
											onClick={() => setShowTranscript(!showTranscript)}
											style={{
												padding: '6px 12px',
												borderRadius: 8,
												border: '1px solid #d1d5db',
												background: showTranscript ? '#3b82f6' : '#fff',
												color: showTranscript ? '#fff' : '#374151',
												cursor: 'pointer',
												fontSize: 12,
												fontWeight: 600,
												transition: 'all 0.2s ease'
											}}
										>
											{showTranscript ? 'Hide' : 'Show'}
										</button>
										
										{showTranscript && (
											<>
												<select
													value={transcriptMode}
													onChange={(e) => setTranscriptMode(e.target.value as 'chapters' | 'fullText')}
													style={{
														fontSize: 12,
														fontWeight: 600,
														padding: '6px 8px',
														border: '1px solid #d1d5db',
														borderRadius: 8,
														background: '#fff',
														cursor: 'pointer'
													}}
												>
													<option value="chapters">Chapters</option>
													<option value="fullText">Full Text</option>
												</select>
												
												<button
													onClick={() => {
														const transcript = generateFullTranscript()
														navigator.clipboard.writeText(transcript).catch(() => {
															const textArea = document.createElement('textarea')
															textArea.value = transcript
															document.body.appendChild(textArea)
															textArea.select()
															document.execCommand('copy')
															document.body.removeChild(textArea)
														})
													}}
													title="Copy transcript"
													style={{
														padding: '6px 12px',
														borderRadius: 8,
														border: '1px solid #d1d5db',
														background: '#fff',
														color: '#374151',
														cursor: 'pointer',
														fontSize: 12,
														fontWeight: 600,
														transition: 'all 0.2s ease'
													}}
												>
													📋
												</button>
											</>
										)}
									</div>
								</div>
								
								{activeChapter !== null && (
									<div style={{
										display: 'flex',
										alignItems: 'center',
										gap: 8,
										padding: '8px 12px',
										background: 'rgba(16, 185, 129, 0.1)',
										borderRadius: 8,
										border: '1px solid rgba(16, 185, 129, 0.2)'
									}}>
										<div style={{
											width: 8,
											height: 8,
											borderRadius: '50%',
											background: '#10b981',
											animation: 'pulse 2s infinite'
										}} />
										<span style={{
											fontSize: 12,
											fontWeight: 600,
											color: '#059669'
										}}>
											Now playing: Chapter {activeChapter + 1}
										</span>
									</div>
								)}
							</div>

							{/* Transcript Content */}
							{showTranscript && (
								<div style={{ flex: 1, overflow: 'auto' }}>
									{transcriptMode === 'fullText' ? (
										<div style={{
											padding: '24px',
											fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Consolas, monospace',
											fontSize: 13,
											lineHeight: 1.8,
											color: '#374151',
											whiteSpace: 'pre-wrap',
											wordBreak: 'break-word'
										}}>
											{generateFullTranscript()}
										</div>
									) : (
										<div style={{ padding: '12px 0' }}>
											{chapters.map((c, i) => {
												const active = i === activeChapter
												const badge = (c.speaker || 'Unknown Speaker').toString().trim()
												const speakerColors = {
													alex: { bg: '#dbeafe', border: '#3b82f6', text: '#1e40af' },
													jordan: { bg: '#ede9fe', border: '#8b5cf6', text: '#6d28d9' },
													charon: { bg: '#dbeafe', border: '#3b82f6', text: '#1e40af' },
													puck: { bg: '#ede9fe', border: '#8b5cf6', text: '#6d28d9' },
													a: { bg: '#dbeafe', border: '#3b82f6', text: '#1e40af' },
													b: { bg: '#ede9fe', border: '#8b5cf6', text: '#6d28d9' },
													'speaker 1': { bg: '#dbeafe', border: '#3b82f6', text: '#1e40af' },
													'speaker 2': { bg: '#ede9fe', border: '#8b5cf6', text: '#6d28d9' },
													'speaker a': { bg: '#dbeafe', border: '#3b82f6', text: '#1e40af' },
													'speaker b': { bg: '#ede9fe', border: '#8b5cf6', text: '#6d28d9' }
												}
												const defaultColors = { bg: '#fef3c7', border: '#f59e0b', text: '#92400e' }
												const colors = speakerColors[badge.toLowerCase() as keyof typeof speakerColors] || defaultColors
												
												return (
													<div 
														key={c.index}
														ref={active ? activeChapterRef : null}
														style={{ 
															margin: '8px 24px',
															padding: '20px',
															background: active ? 
																'linear-gradient(135deg, rgba(59, 130, 246, 0.05), rgba(16, 185, 129, 0.05))' : 
																'#fff',
															border: active ? 
																'2px solid #3b82f6' : 
																'1px solid #e5e7eb',
															borderRadius: 16,
															cursor: 'pointer',
															transition: 'all 0.3s ease',
															position: 'relative',
															overflow: 'hidden'
														}}
														onClick={() => playChapter(c, i)}
														onMouseEnter={(e) => {
															if (!active) {
																e.currentTarget.style.transform = 'translateY(-2px)'
																e.currentTarget.style.boxShadow = '0 8px 25px rgba(0,0,0,0.1)'
															}
														}}
														onMouseLeave={(e) => {
															if (!active) {
																e.currentTarget.style.transform = 'translateY(0)'
																e.currentTarget.style.boxShadow = 'none'
															}
														}}
													>
														{active && (
															<div style={{
																position: 'absolute',
																top: 0,
																left: 0,
																right: 0,
																height: 3,
																background: 'linear-gradient(90deg, #3b82f6, #10b981)',
																borderRadius: '16px 16px 0 0'
															}} />
														)}
														
														<div style={{
															display: 'flex',
															alignItems: 'flex-start',
															gap: 16
														}}>
															<div style={{
																display: 'flex',
																flexDirection: 'column',
																alignItems: 'center',
																gap: 8,
																minWidth: 80
															}}>
																<div style={{
																	fontSize: 11,
																	fontWeight: 700,
																	fontVariantNumeric: 'tabular-nums',
																	color: active ? '#3b82f6' : '#6b7280',
																	padding: '4px 8px',
																	background: active ? 'rgba(59, 130, 246, 0.1)' : 'rgba(107, 114, 128, 0.1)',
																	borderRadius: 6
																}}>
																	{typeof c.start_ms === 'number' ? 
																		`${Math.floor(c.start_ms/1000/60)}:${String(Math.floor(c.start_ms/1000)%60).padStart(2,'0')}` : 
																		'--:--'
																	}
																</div>
																
																<div style={{
																	padding: '6px 12px',
																	borderRadius: 20,
																	background: colors.bg,
																	border: `2px solid ${colors.border}`,
																	fontSize: 11,
																	fontWeight: 700,
																	color: colors.text,
																	textAlign: 'center',
																	textTransform: 'capitalize',
																	letterSpacing: '0.025em',
																	minWidth: 70
																}}>
																	{badge}
																</div>
															</div>
															
															<div style={{
																flex: 1,
																fontSize: 14,
																lineHeight: 1.7,
																color: active ? '#1f2937' : '#374151',
																fontWeight: active ? 500 : 400
															}}>
																{c.text}
															</div>
															
															<div style={{
																display: 'flex',
																alignItems: 'center',
																gap: 8,
																opacity: active ? 1 : 0.6
															}}>
																<button
																	onClick={(e) => {
																		e.stopPropagation()
																		const chapterText = `[${typeof c.start_ms === 'number' ? 
																			`${Math.floor(c.start_ms/1000/60)}:${String(Math.floor(c.start_ms/1000)%60).padStart(2,'0')}` : 
																			'--:--'
																		}] ${badge}: ${c.text}`
																		navigator.clipboard.writeText(chapterText).catch(() => {
																			const textArea = document.createElement('textarea')
																			textArea.value = chapterText
																			document.body.appendChild(textArea)
																			textArea.select()
																			document.execCommand('copy')
																			document.body.removeChild(textArea)
																		})
																	}}
																	title="Copy chapter"
																	style={{
																		width: 32,
																		height: 32,
																		borderRadius: '50%',
																		border: '1px solid #d1d5db',
																		background: '#fff',
																		cursor: 'pointer',
																		fontSize: 12,
																		color: '#6b7280',
																		display: 'flex',
																		alignItems: 'center',
																		justifyContent: 'center',
																		transition: 'all 0.2s ease'
																	}}
																>📋</button>
																
																<div style={{
																	width: 32,
																	height: 32,
																	borderRadius: '50%',
																	background: active && playing ? 
																		'linear-gradient(135deg, #ef4444, #dc2626)' : 
																		'linear-gradient(135deg, #10b981, #059669)',
																	display: 'flex',
																	alignItems: 'center',
																	justifyContent: 'center',
																	fontSize: 12,
																	color: '#fff',
																	fontWeight: 600
																}}>
																	{active && playing ? '⏸️' : '▶️'}
																</div>
															</div>
														</div>
													</div>
												)
											})}
										</div>
									)}
								</div>
							)}
						</div>
					)}

					{/* No Chapters Message */}
					{chapters.length === 0 && (
						<div style={{
							background: 'rgba(255,255,255,0.9)',
							backdropFilter: 'blur(10px)',
							margin: '0 24px 24px',
							padding: '40px 24px',
							borderRadius: 16,
							border: '1px solid rgba(255,255,255,0.2)',
							textAlign: 'center'
						}}>
							<div style={{
								fontSize: 48,
								marginBottom: 16
							}}>🎙️</div>
							<h3 style={{
								margin: 0,
								fontSize: 16,
								fontWeight: 600,
								color: '#6b7280',
								marginBottom: 8
							}}>No Chapters Available</h3>
							<p style={{
								margin: 0,
								fontSize: 14,
								color: '#9ca3af'
							}}>Generate a podcast to see interactive chapters and subtitles</p>
						</div>
					)}
				</>
			)}
		</div>
	)
}
