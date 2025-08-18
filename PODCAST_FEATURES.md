# Enhanced Two-Person Podcast Features

## Overview

Your PDF semantic search app now includes advanced podcast generation capabilities inspired by Google NotebookLM, with natural two-speaker dialogue and high-quality TTS voices.

## Key Features

### 🎧 Natural Two-Speaker Podcasts

- **Alex** (Analytical host): UK English female voice, asks probing questions
- **Jordan** (Enthusiastic host): US English male voice, provides vivid explanations
- **Natural conversation flow**: Interruptions, reactions, building on each other's points
- **Conversational elements**: "Oh, that's fascinating!", "Wait, so you're saying..."

### 📖 Entire PDF Processing

- Generate comprehensive podcasts covering complete documents
- Intelligent content summarization and dialogue structuring
- Perfect for academic papers, reports, and lengthy documents

### 🎙️ Advanced TTS Options

1. **Edge-TTS** (Recommended): Microsoft's neural voices for natural speech
2. **Hugging Face**: AI-powered TTS with customizable voices
3. **pyttsx3**: Offline fallback option

### 🔧 Flexible Audio Modes

- **Single Narrator**: Traditional narration for quick content
- **Two-Speaker Podcast**: Conversational dialogue between Alex & Jordan
- **Full PDF Podcast**: Complete document coverage with engaging dialogue

## API Usage

### Basic Request

```bash
POST /generate-audio
{
  "filename": "document.pdf",
  "page_number": 1,
  "podcast": true,
  "two_speakers": true
}
```

### Full PDF Podcast

```bash
POST /generate-audio
{
  "filename": "document.pdf",
  "entire_pdf": true,
  "podcast": true,
  "two_speakers": true,
  "speakers": {
    "Alex": "en-GB-SoniaNeural",
    "Jordan": "en-US-DavisNeural"
  }
}
```

### Custom Voice Configuration

```bash
POST /generate-audio
{
  "text": "Your content here...",
  "podcast": true,
  "two_speakers": true,
  "accent": "en-US",
  "expressiveness": "high",
  "speakers": {
    "Alex": "en-GB-SoniaNeural",
    "Jordan": "en-US-DavisNeural"
  }
}
```

## Environment Setup

### Required Environment Variables

```bash
# Google API for script generation
GOOGLE_API_KEY=your_gemini_api_key

# Optional: Choose TTS provider
TTS_PROVIDER=edge_tts  # or 'hf_dia' or 'pyttsx3'

# Optional: HuggingFace for alternative TTS
HUGGINGFACE_API_TOKEN=your_hf_token
```

### Installation

```bash
# Install enhanced dependencies
pip install edge-tts pydub

# Ensure ffmpeg is available for audio processing
# Windows: Download from https://ffmpeg.org/
# Ubuntu: sudo apt install ffmpeg
# macOS: brew install ffmpeg
```

## Frontend Integration

The enhanced UI provides three modes:

1. **🎙️ Single Narrator**: Quick narration
2. **🎧 Two-Speaker Podcast**: Alex & Jordan dialogue
3. **📖 Full PDF Podcast**: Complete document coverage

### Usage Tips

- Use **Single Narrator** for quick content review
- Use **Two-Speaker Podcast** for engaging explanations of specific sections
- Use **Full PDF Podcast** for comprehensive document exploration
- Audio controls appear automatically when generation completes

## Technical Architecture

### LLM Script Generation

- **Gemini 1.5 Flash** generates natural dialogue scripts
- **Prompt engineering** creates distinct speaker personalities
- **Content grounding** ensures factual accuracy

### Audio Processing Pipeline

1. **Script Generation**: LLM creates dialogue between Alex & Jordan
2. **Line-by-Line TTS**: Each speaker's lines synthesized with distinct voices
3. **Audio Concatenation**: pydub combines individual clips with natural pauses
4. **Caching**: Intelligent caching for repeated requests

### Performance Optimizations

- **Script caching**: Reuse generated dialogues for identical content
- **Audio caching**: Store synthesized audio for future requests
- **Threaded synthesis**: Non-blocking TTS generation
- **Deterministic naming**: Consistent file naming for cache hits

## Comparison with Other Approaches

### vs. SubhamIO's LangGraph Implementation

**Advantages of your approach:**

- **Integrated**: Built into existing PDF search/insights system
- **Flexible**: Multiple TTS providers and voice options
- **Scalable**: FastAPI backend handles concurrent requests
- **Cached**: Intelligent caching reduces regeneration overhead

**Inspired elements from LangGraph approach:**

- **Structured dialogue generation**: Natural conversation flow
- **Multiple TTS voices**: Distinct speaker personalities
- **Audio concatenation**: Professional podcast-quality output

## Next Steps

### Potential Enhancements

1. **Speaker Emotions**: Add emotional context to dialogue
2. **Background Music**: Subtle audio enhancement
3. **Chapter Markers**: Navigation for long podcasts
4. **Voice Cloning**: Custom speaker voices
5. **Real-time Generation**: Streaming audio synthesis

### Production Considerations

- **Rate Limiting**: Protect TTS APIs from overuse
- **Audio Compression**: Optimize file sizes for streaming
- **CDN Integration**: Fast global audio delivery
- **Analytics**: Track podcast generation and listening metrics
