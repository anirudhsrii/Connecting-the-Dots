from fastapi import FastAPI, UploadFile, File
from typing import List
from pathlib import Path
# Support running as a package (uvicorn backend.main:app) or from within backend/ (uvicorn main:app)
try:  # Prefer absolute imports when launched from repo root
    from backend.processing import process_pdf, _get_embedder  # type: ignore
    from backend.vector_store import VectorStore  # type: ignore
except Exception:  # Fallback to local module imports when cwd is backend/
    from processing import process_pdf, _get_embedder  # type: ignore
    from vector_store import VectorStore  # type: ignore
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Any, Dict, Tuple, Set
import os
import json
import uuid
import fitz  # PyMuPDF
import asyncio
import hashlib
import threading
import time
import struct
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
import re
import numpy as np  # type: ignore
from fastapi import HTTPException
from dotenv import load_dotenv
try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover
    genai = None  # type: ignore
try:
    # New Gemini Speech (google-genai)
    from google import genai as genai_speech  # type: ignore
    from google.genai import types as genai_types  # type: ignore
except Exception:  # pragma: no cover
    genai_speech = None  # type: ignore
    genai_types = None  # type: ignore
try:
    import pyttsx3  # type: ignore
except ImportError:  # pragma: no cover
    pyttsx3 = None  # type: ignore
try:
    import edge_tts  # type: ignore
except ImportError:  # pragma: no cover
    edge_tts = None  # type: ignore
try:
    # Google Cloud Text-to-Speech
    from google.cloud import texttospeech as google_tts  # type: ignore
    import google.oauth2.service_account as gsa  # type: ignore
except Exception:  # pragma: no cover
    google_tts = None  # type: ignore
try:
    import requests  # type: ignore
except ImportError:  # pragma: no cover
    requests = None  # type: ignore
_ENV_PATH = (Path(__file__).resolve().parent / ".env")
if _ENV_PATH.is_file():
    load_dotenv(dotenv_path=str(_ENV_PATH))
else:
    # Fallback to default lookup (cwd)
    load_dotenv()


def _convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    """Generates a WAV file header for the given audio data and parameters.
    Based on reference Gemini TTS implementation.

    Args:
        audio_data: The raw audio data as a bytes object.
        mime_type: Mime type of the audio data.

    Returns:
        A bytes object representing the WAV file with proper header.
    """
    parameters = _parse_audio_mime_type(mime_type)
    bits_per_sample = parameters["bits_per_sample"]
    sample_rate = parameters["rate"]
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size  # 36 bytes for header fields before data chunk size

    # http://soundfile.sapp.org/doc/WaveFormat/
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",          # ChunkID
        chunk_size,       # ChunkSize (total file size - 8 bytes)
        b"WAVE",          # Format
        b"fmt ",          # Subchunk1ID
        16,               # Subchunk1Size (16 for PCM)
        1,                # AudioFormat (1 for PCM)
        num_channels,     # NumChannels
        sample_rate,      # SampleRate
        byte_rate,        # ByteRate
        block_align,      # BlockAlign
        bits_per_sample,  # BitsPerSample
        b"data",          # Subchunk2ID
        data_size         # Subchunk2Size (size of audio data)
    )
    return header + audio_data


def _parse_audio_mime_type(mime_type: str) -> dict:
    """Parses bits per sample and rate from an audio MIME type string.
    Based on reference Gemini TTS implementation.

    Assumes bits per sample is encoded like "L16" and rate as "rate=xxxxx".

    Args:
        mime_type: The audio MIME type string (e.g., "audio/L16;rate=24000").

    Returns:
        A dictionary with "bits_per_sample" and "rate" keys.
    """
    bits_per_sample = 16
    rate = 24000

    # Extract rate from parameters
    parts = mime_type.split(";")
    for param in parts:  # Skip the main type part
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate_str = param.split("=", 1)[1]
                rate = int(rate_str)
            except (ValueError, IndexError):
                # Handle cases like "rate=" with no value or non-integer value
                pass  # Keep rate as default
        elif param.startswith("audio/L"):
            try:
                bits_per_sample = int(param.split("L", 1)[1])
            except (ValueError, IndexError):
                pass  # Keep bits_per_sample as default if conversion fails

    return {"bits_per_sample": bits_per_sample, "rate": rate}

app = FastAPI(title="Adobe Hackathon Finale API")

# Global in-memory vector store for this app instance
store = VectorStore()

# Insights behavior defaults via environment
INSIGHTS_DEFAULT = (os.getenv("INSIGHTS_DEFAULT", "cross") or "cross").lower()
try:
    CROSS_INSIGHTS_MAX_PER_DOC = int(os.getenv("CROSS_INSIGHTS_MAX_PER_DOC", "6"))
except Exception:
    CROSS_INSIGHTS_MAX_PER_DOC = 6
CROSS_INSIGHTS_DEEP = (os.getenv("CROSS_INSIGHTS_DEEP", "true") or "true").strip().lower() == "true"

# ---------------------------------------------------------------------------
# Performance / caching infrastructure
# ---------------------------------------------------------------------------
# Lightweight in-memory caches (non-persistent) to avoid recomputation during a
# single server session. For hackathon/demo scale this is sufficient; for
# production consider an external cache with TTL handling.
_script_cache: Dict[str, str] = {}
_audio_cache: Dict[str, Tuple[str, str]] = {}  # key -> (filename, rel_url)

_pyttsx3_lock = threading.Lock()  # pyttsx3 is not fully thread-safe
_tts_executor = ThreadPoolExecutor(max_workers=int(os.getenv("TTS_WORKERS", "2")))
_bg_executor = ThreadPoolExecutor(max_workers=int(os.getenv("BG_WORKERS", "4")))


def _hash_short(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _synthesize_with_fallback(text: str, base: str, voice: Optional[str], accent: Optional[str], style: Optional[str]) -> Tuple[str, str]:
    """Try TTS providers based on env preference.
    If a specific provider is set via TTS_PROVIDER, use ONLY that provider (no silent fallback).
    If not set, try a sensible fallback order.
    """
    # Choose order based on env preference
    pref = (os.getenv("TTS_PROVIDER") or "").strip().lower()
    recognized = {"edge_tts", "hf_dia", "pyttsx3", "google", "gemini"}
    order: List[str]
    if pref in recognized and pref != "":
        order = [pref]
    else:
        # Auto mode: try in order preferring Gemini first, then Google, then Edge/HF, then offline
        order = ["gemini", "google", "edge_tts", "hf_dia", "pyttsx3"]
    # Try in order
    last_err: Optional[Exception] = None
    for prov in order:
        try:
            return _synthesize_speech(text, voice=voice, accent=accent, style=style, deterministic_basename=base, provider_override=prov)
        except Exception as e:
            last_err = e
            continue
    # If all fail, raise the last error
    if last_err:
        raise last_err
    # Fallback shouldn't reach here; use pyttsx3
    return _synthesize_speech(text, voice=voice, accent=accent, style=style, deterministic_basename=base, provider_override="pyttsx3")

# Cross-document analysis caches
_doc_claims_cache: Dict[str, List[Dict[str, Any]] ] = {}
_cross_insights_cache: Dict[str, Dict[str, Any]] = {}
_web_cache: Dict[str, List[Dict[str, Any]]] = {}

def _file_signature(filename: str) -> str:
    """Return a short signature for a file based on mtime and size for cache invalidation."""
    try:
        p = (_docs_dir / filename)
        st = p.stat()
        return f"{filename}:{int(st.st_mtime)}:{st.st_size}"
    except Exception:
        return f"{filename}:na"

# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded PDFs statically so the frontend can preview them
_docs_dir = (Path(__file__).resolve().parent / "document_library").absolute()
_docs_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/document_library",
    StaticFiles(directory=str(_docs_dir)),
    name="document_library",
)

# Serve generated audio files
_audio_dir = (Path(__file__).resolve().parent / "generated_audio").absolute()
_audio_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/audio",
    StaticFiles(directory=str(_audio_dir)),
    name="audio",
)


# ---------------------------------------------------------------------------
# Startup: index any PDFs already present so recommendations work after restart
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def _startup_index_existing_pdfs():
    try:
        # Collect already-indexed filenames from metadata
        indexed: Set[str] = set()
        for md in store.metadatas:
            fn = md.get("filename")
            if fn:
                indexed.add(fn)
        # Scan disk for PDFs
        to_add: List[Path] = []
        for p in _docs_dir.iterdir():
            if p.is_file() and p.suffix.lower() == ".pdf" and p.name not in indexed:
                to_add.append(p)
        # Process sequentially to avoid embedder concurrency issues
        for pdf_path in sorted(to_add):
            try:
                processed = process_pdf(str(pdf_path))
                if processed:
                    store.add_documents(processed, filename=pdf_path.name)
            except Exception:
                # Skip problematic files to keep startup resilient
                continue
    except Exception:
        # Never block server startup on indexing failures
        pass


@app.post("/reindex")
async def reindex():
    """Re-scan document_library and (re)index any missing PDFs.
    Returns list of (newly) indexed filenames.
    """
    newly: List[str] = []
    try:
        indexed: Set[str] = set()
        for md in store.metadatas:
            fn = md.get("filename")
            if fn:
                indexed.add(fn)
        for p in _docs_dir.iterdir():
            if p.is_file() and p.suffix.lower() == ".pdf" and p.name not in indexed:
                try:
                    processed = process_pdf(str(p))
                    if processed:
                        store.add_documents(processed, filename=p.name)
                        newly.append(p.name)
                except Exception:
                    continue
    except Exception:
        pass
    return {"indexed": newly}


@app.get("/config/public")
def public_config():
    """Return non-sensitive config usable by the frontend."""
    return {
        "adobeClientId": os.getenv("ADOBE_CLIENT_ID", "")
    }


@app.get("/v1/health")
def health_check():
    return {"status": "ok"}


@app.get("/diagnostics")
def diagnostics():
    """Basic diagnostics for TTS provider configuration and audio tools."""
    provider = (os.getenv("TTS_PROVIDER") or "auto").lower().strip() or "auto"
    info: Dict[str, Any] = {"provider": provider, "ffmpeg": False, "ffprobe": False}
    # Check ffmpeg / ffprobe
    try:
        import subprocess
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        info["ffmpeg"] = (r.returncode == 0)
    except Exception:
        info["ffmpeg"] = False
    try:
        import subprocess
        r = subprocess.run(["ffprobe", "-version"], capture_output=True, text=True, timeout=5)
        info["ffprobe"] = (r.returncode == 0)
    except Exception:
        info["ffprobe"] = False

    # Provider-specific checks
    if provider == "google":
        info["google_tts"] = {"installed": google_tts is not None}
        if google_tts is not None:
            creds_json = os.getenv("GOOGLE_TTS_SERVICE_ACCOUNT_JSON", "").strip()
            try:
                if creds_json:
                    credentials = gsa.Credentials.from_service_account_info(json.loads(creds_json))
                    client = google_tts.TextToSpeechClient(credentials=credentials)
                else:
                    client = google_tts.TextToSpeechClient()
                voices = client.list_voices().voices or []
                info["google_tts"].update({
                    "auth": True,
                    "voices_count": len(voices)
                })
            except Exception as e:
                info["google_tts"].update({
                    "auth": False,
                    "error": str(e)[:300]
                })
    elif provider == "hf_dia":
        info["hf_dia"] = {"token": bool(os.getenv("HUGGINGFACE_API_TOKEN"))}
    elif provider == "gemini":
        ok = False
        err = None
        try:
            if genai_speech is not None:
                _ = genai_speech.Client(api_key=(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""))
                ok = True
        except Exception as e:  # pragma: no cover
            err = str(e)[:300]
        info["gemini_speech"] = {"installed": genai_speech is not None, "client_ok": ok, "error": err}
    else:
        info["pyttsx3"] = {"available": pyttsx3 is not None}

    return info


@app.get("/documents")
def list_documents():
    """List uploaded PDF filenames in the document library."""
    try:
        files = []
        for p in _docs_dir.iterdir():
            if p.is_file() and p.suffix.lower() == ".pdf":
                files.append(p.name)
        files.sort()
        return {"files": files}
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {e}")


class RecommendationRequest(BaseModel):
    text: Optional[str] = None
    filename: Optional[str] = None
    page_number: Optional[int] = None
    k: int = 5
    fetch_k: Optional[int] = None  # retrieve more for better de-dup
    min_score: Optional[float] = None  # filter low-relevance results
    exclude_self: bool = True  # if querying by filename/page, remove same page from results


@app.post("/recommendations")
async def recommendations(req: RecommendationRequest):
    # Determine query text
    query_text: Optional[str] = None
    if req.text and req.text.strip():
        query_text = req.text.strip()
    elif req.filename:
        # Aggregate chunks for the given page or entire file
        joined: List[str] = []
        for text, meta in zip(store.texts, store.metadatas):
            if meta.get("filename") == req.filename and (
                req.page_number is None or meta.get("page_number") == req.page_number
            ):
                joined.append(text)
        if joined:
            # Use a brief summary as query to avoid excessively long input
            query_text = "\n\n".join(joined)[:2000]

    if not query_text:
        return {"results": []}

    # Embed and search
    model = _get_embedder()
    q_emb = model.encode([query_text], convert_to_numpy=True, normalize_embeddings=True)[0]
    # Expand initial pool to ensure we can dedupe and find distinct sections
    fetch_k = req.fetch_k if req.fetch_k is not None else max(req.k * 3, req.k + 10)
    results = store.search(q_emb, k=req.k, fetch_k=fetch_k)

    # Helper: produce a 2–4 sentence extract from the best available source text
    def _snippet_2to4_sentences(source_text: str, meta: Dict[str, Any], query: str) -> str:
        def split_sentences(t: str) -> List[str]:
            t = re.sub(r"\s+", " ", t or "").strip()
            if not t:
                return []
            parts = re.split(r"(?<=[.!?])\s+", t)
            # Trim and drop empties
            return [p.strip() for p in parts if p and len(p.strip()) > 0]

        # Prefer section text if available; otherwise use page text
        text = source_text or ""
        if not text:
            fname = meta.get("filename")
            pnum = meta.get("page_number")
            if fname and pnum:
                try:
                    text = _extract_page_text(str((_docs_dir / fname).absolute()), int(pnum))
                except Exception:
                    text = ""
        sents = split_sentences(text)
        if not sents:
            return ""
        if len(sents) <= 4:
            return " ".join(sents)

        # Score sentences by query term overlap
        tokens = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", query or "") if len(w) >= 3]
        uniq = list(dict.fromkeys(tokens))[:12]
        scores = []
        for i, sent in enumerate(sents):
            l = sent.lower()
            score = sum(1 for w in uniq if w in l)
            scores.append((score, i))
        # Choose best 3-sentence window; allow 2 or 4 if at edges or ties
        best = (-(10**9), 0, 3)  # (score, start, window)
        n = len(sents)
        for win in (3, 4, 2):
            for start in range(0, n - win + 1):
                sc = sum(scores[i][0] for i in range(start, start + win))
                cand = (sc, start, win)
                if cand > best:
                    best = cand
        _, start, win = best
        pick = sents[start:start+win]
        prefix = "… " if start > 0 else ""
        suffix = " …" if start + win < n else ""
        snippet = prefix + " ".join(pick) + suffix
        # Guardrail: keep under ~600 chars
        if len(snippet) > 600:
            snippet = snippet[:600].rsplit(" ", 1)[0] + " …"
        return snippet

    # De-dup and optional filtering
    # De-dup by section when available (filename + section_index), else by page
    seen: Set[Tuple[Optional[str], Optional[int], Optional[int]]] = set()
    shaped = []
    best_self = None  # hold best result from the same page if we end up empty
    for r in results:
        md = r.get("metadata", {})
        fname = md.get("filename")
        pnum = md.get("page_number")
        sec_idx = md.get("section_index")
        key = (fname, sec_idx, pnum)
        if key in seen:
            continue
        if req.exclude_self and req.filename and fname == req.filename and req.page_number and pnum == req.page_number:
            # Record the best self result in case everything else is filtered out
            if best_self is None:
                best_self = r
            continue
        score = r.get("score")
        if req.min_score is not None and score is not None and score < req.min_score:
            continue
        seen.add(key)
        source_text = r.get("text", "")
        cleaned = _snippet_2to4_sentences(source_text, md, query_text or "")
        shaped.append({
            "snippet": cleaned,
            "filename": fname,
            "page_number": pnum,
            "section_title": md.get("section_title"),
            "section_index": md.get("section_index"),
            "distance": r.get("distance"),
            "score": score,
        })
        if len(shaped) >= req.k:
            break
    # If nothing found and we filtered out the self page, return the best self match
    if not shaped and best_self is not None:
        md = best_self.get("metadata", {})
        shaped.append({
            "snippet": best_self.get("text", ""),
            "filename": md.get("filename"),
            "page_number": md.get("page_number"),
            "distance": best_self.get("distance"),
            "score": best_self.get("score"),
        })
    return {"results": shaped}


class InsightsRequest(BaseModel):
    text: Optional[str] = None
    filename: Optional[str] = None
    page_number: Optional[int] = None
    k: int = 5  # retrieval size for context/citations
    web: Optional[bool] = False  # if true, augment with web research
    web_k: int = 3  # number of web sources when web=True


def _extract_entire_pdf_text(file_path: str) -> str:
    """Extract text from entire PDF for podcast generation."""
    if not Path(file_path).is_file():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        doc = fitz.open(file_path)
        try:
            full_text = ""
            for page_num in range(len(doc)):
                page = doc[page_num]
                page_text = page.get_text("text") or ""
                if page_text.strip():
                    full_text += f"\n\nPage {page_num + 1}:\n{page_text}"
            return full_text
        finally:
            doc.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read PDF: {e}")


def _extract_page_text(file_path: str, page_number: int) -> str:
    if not Path(file_path).is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if page_number is None or page_number < 1:
        raise HTTPException(status_code=400, detail="page_number must be >= 1")
    try:
        doc = fitz.open(file_path)
        try:
            idx = page_number - 1
            if idx < 0 or idx >= len(doc):
                raise HTTPException(status_code=400, detail="page_number out of range")
            page = doc[idx]
            return page.get_text("text") or ""
        finally:
            doc.close()
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Failed to read PDF: {e}")


def _gemini_insights(text: str, citations: Optional[List[Dict[str, Any]]] = None, web_results: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    if genai is None:
        raise HTTPException(status_code=500, detail="google-generativeai not installed on server")
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="GOOGLE_API_KEY not configured on server")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        generation_config={
            "response_mime_type": "application/json"
        }
    )
    cites_str = "\n".join([
        f"[CITATION {i+1}] file={c.get('filename')} page={c.get('page_number')}: {c.get('snippet')}"
        for i, c in enumerate(citations or [])
    ])
    web_str = "\n".join([
        f"[WEB {i+1}] title={w.get('title','')} url={w.get('url','')}: {w.get('snippet','')}"
        for i, w in enumerate(web_results or [])
    ])
    prompt = f"""
You are an assistant extracting structured insights from a document passage and optional retrieved references.
Return a single JSON object with EXACTLY these keys (no extra keys):
- "key_insights": array of 3-7 concise takeaways (short, actionable).
- "did_you_know_facts": array of factual nuggets supported by the text.
- "counterpoints": array of potential caveats, risks, or alternative views (empty if none).
- "inspirations": array of ideas, applications, or next steps the reader could try.
- "examples": array of 3-6 illustrative examples that clarify the content; each example should be 1-3 sentences.

Primary Context:
{text}

Retrieved References (optional):
{cites_str or 'None'}

External Web Context (optional):
{web_str or 'None'}
"""
    try:
        resp = model.generate_content(prompt)
        raw = (getattr(resp, "text", None) or "").strip()
        # In JSON mode, raw should be JSON; still guard parsing
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            data = {}
        return {
            "key_insights": data.get("key_insights", []),
            "did_you_know_facts": data.get("did_you_know_facts", []),
            "counterpoints": data.get("counterpoints", []),
            "inspirations": data.get("inspirations", []),
            "examples": data.get("examples", []),
        }
    except Exception:  # pragma: no cover
        return {"key_insights": [], "did_you_know_facts": [], "counterpoints": [], "inspirations": [], "examples": []}


def _web_search(query: str, k: int = 3) -> List[Dict[str, Any]]:
    """Perform a lightweight web search using Tavily or Bing (if API keys provided).
    Returns a list of dicts: { title, url, snippet }
    """
    results: List[Dict[str, Any]] = []
    q = (query or "").strip()
    if not q or requests is None:
        return results
    # Cache by query+k
    key = f"{_hash_short(q)}|{k}"
    cached = _web_cache.get(key)
    if cached is not None:
        return cached

    # Try Tavily first
    tav_key = os.getenv("TAVILY_API_KEY", "").strip()
    if tav_key:
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": tav_key,
                    "query": q,
                    "search_depth": "basic",
                    "include_answer": False,
                    "max_results": max(1, min(10, k)),
                },
                timeout=20,
            )
            if resp.ok:
                data = resp.json()
                for item in data.get("results", [])[:k]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("content", "")[:500],
                    })
        except Exception:
            results = []

    # Fallback to Bing Web Search API
    if not results:
        bing_key = os.getenv("BING_SEARCH_API_KEY", "").strip()
        if bing_key:
            try:
                params = {"q": q, "count": max(1, min(10, k))}
                headers = {"Ocp-Apim-Subscription-Key": bing_key}
                url = f"https://api.bing.microsoft.com/v7.0/search?{urlencode(params)}"
                resp = requests.get(url, headers=headers, timeout=20)
                if resp.ok:
                    data = resp.json()
                    for item in (data.get("webPages", {}).get("value", []) or [])[:k]:
                        results.append({
                            "title": item.get("name", ""),
                            "url": item.get("url", ""),
                            "snippet": item.get("snippet", "")[:500],
                        })
            except Exception:
                results = []

    _web_cache[key] = results
    return results


@app.post("/insights")
async def insights(req: InsightsRequest):
    """Generate insights using Gemini from provided text or a specific page of an uploaded PDF.
    If INSIGHTS_DEFAULT=cross and no explicit text/filename provided, delegate to cross-insights across all PDFs.
    """
    # Default to cross-doc when configured and no specific input
    if INSIGHTS_DEFAULT == "cross" and not (req.text and req.text.strip()) and not req.filename:
        cross_req = CrossInsightsRequest(
            filenames=None,
            max_per_doc=max(2, CROSS_INSIGHTS_MAX_PER_DOC),
            deep=bool(CROSS_INSIGHTS_DEEP),
            force=False,
            include_claims=False,
            focus=None,
        )
        return await cross_insights(cross_req)

    text = (req.text or "").strip()
    if not text:
        if not (req.filename and req.page_number):
            raise HTTPException(status_code=400, detail="Provide text, or filename + page_number")
        file_path = str((_docs_dir / req.filename).absolute())
        text = _extract_page_text(file_path, req.page_number).strip()
        if not text:
            raise HTTPException(status_code=400, detail="No extractable text for the given page")
    # Retrieve top-k related chunks for better grounded insights and citations
    citations: List[Dict[str, Any]] = []
    try:
        model = _get_embedder()
        q_emb = model.encode([text], convert_to_numpy=True, normalize_embeddings=True)[0]
        raw = store.search(q_emb, k=max(1, req.k or 5), fetch_k=max(10, (req.k or 5) * 2))
        seen: Set[Tuple[Optional[str], Optional[int]]] = set()
        for r in raw:
            md = r.get("metadata", {})
            fname = md.get("filename")
            pnum = md.get("page_number")
            key = (fname, pnum)
            if key in seen:
                continue
            seen.add(key)
            citations.append({
                "filename": fname,
                "page_number": pnum,
                "snippet": r.get("text", "")[:500]
            })
            if len(citations) >= (req.k or 5):
                break
    except Exception:
        citations = []

    # Optional: web augmentation
    web_results: List[Dict[str, Any]] = []
    if req.web:
        # Keep query compact to reduce search noise
        q = (text[:300] + ("…" if len(text) > 300 else "")).strip()
        try:
            web_results = _web_search(q, k=max(1, min(5, req.web_k)))
        except Exception:
            web_results = []

    result = _gemini_insights(text, citations, web_results)
    return {
        "key_insights": result.get("key_insights", []),
        "did_you_know_facts": result.get("did_you_know_facts", []),
        "counterpoints": result.get("counterpoints", []),
        "inspirations": result.get("inspirations", []),
        "examples": result.get("examples", []),
        "citations": citations,
        "web": web_results,
    }


class CrossInsightsRequest(BaseModel):
    filenames: Optional[List[str]] = None  # if None, use all uploaded PDFs
    max_per_doc: int = 6  # max claims/snippets per document
    deep: Optional[bool] = False  # if true, use LLM to extract claims; else use fast snippet fallback
    force: Optional[bool] = False  # bypass caches when true
    focus: Optional[str] = None  # optional topic/focus to steer comparison
    include_claims: Optional[bool] = False  # include per-doc extracted claims in response (debugging)


def _select_diverse_pages(page_texts: Dict[int, str], k: int) -> List[int]:
    """Select up to k pages maximizing diversity using cosine distances on embeddings.
    Start with longest page then greedy max-min. Falls back to length ranking if embedder unavailable.
    """
    items = [(p, t, len(t)) for p, t in page_texts.items() if (t or "").strip()]
    if not items:
        return []
    # If k >= pages, return all pages sorted by page number
    if k >= len(items):
        return [p for p, _, _ in sorted(items, key=lambda x: x[0])]
    # Candidate pool: top k*3 by length to cap compute
    cand = sorted(items, key=lambda x: x[2], reverse=True)[: max(1, min(len(items), k * 3))]
    pages = [p for p, _, _ in cand]
    texts = [t for _, t, _ in cand]
    try:
        model = _get_embedder()
        embs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    except Exception:
        return [p for p, _, _ in cand[:k]]
    # Greedy max-min selection
    selected: List[int] = []
    selected_idx: List[int] = []
    # seed with the longest page (index 0 in cand)
    selected.append(pages[0])
    selected_idx.append(0)
    while len(selected) < k and len(selected) < len(pages):
        best_i = None
        best_score = -1.0
        for i in range(len(pages)):
            if i in selected_idx:
                continue
            # max-min distance (1 - cosine since embs normalized and search uses inner product)
            dmin = 1.0
            for si in selected_idx:
                sim = float(np.dot(embs[i], embs[si]))
                dist = 1.0 - sim
                if dist < dmin:
                    dmin = dist
            if dmin > best_score:
                best_score = dmin
                best_i = i
        if best_i is None:
            break
        selected_idx.append(best_i)
        selected.append(pages[best_i])
    return selected


def _extract_doc_claims(filename: str, max_per_doc: int = 6, deep: bool = False) -> List[Dict[str, Any]]:
    """Return a list of concise claims for a document with page refs.
    Strategy:
      1) Select up to max_per_doc pages with the most content.
      2) Ask Gemini to extract 3-8 factual claims with page refs and short quotes.
      3) Fallback to raw snippets if LLM isn't available.
    """
    # Gather chunks for this file
    chunks: List[Tuple[str, Dict[str, Any]]] = [
        (t, m) for t, m in zip(store.texts, store.metadatas) if m.get("filename") == filename
    ]
    if not chunks:
        return []
    # Group by page
    pages: Dict[int, List[str]] = {}
    for t, m in chunks:
        p = int(m.get("page_number") or 0)
        pages.setdefault(p, []).append(t)
    # Build per-page text and select a diverse subset of pages
    page_full: Dict[int, str] = {}
    for p, segs in pages.items():
        page_full[p] = "\n".join(segs)
    chosen_pages = _select_diverse_pages(page_full, max_per_doc) or [p for p in sorted(pages.keys())[:max_per_doc]]

    # Prepare sections for LLM with page markers
    sections = []
    for p in chosen_pages:
        joined = page_full.get(p, "")
        sections.append({"page_number": p, "text": joined[:900]})

    # If Gemini not available, fallback to snippets
    if (not deep) or genai is None or not os.getenv("GOOGLE_API_KEY"):
        fallback: List[Dict[str, Any]] = []
        for s in sections:
            fallback.append({
                "filename": filename,
                "page_number": s["page_number"],
                "snippet": s["text"],
            })
        return fallback

    # Call Gemini once per document to extract claims
    try:
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )
        sec_text = []
        for s in sections:
            sec_text.append(f"PAGE {s['page_number']}\n{s['text']}")
        sections_block = "\n\n".join(sec_text)
        prompt = f"""
You are extracting factual claims from a PDF. Read the page sections and return JSON with an array 'claims'.
Each claim item must include:
    statement: concise factual sentence.
    page_number: integer page number where it's supported.
    quotes: array of 1-2 short quotes (<=120 chars) from that page.
Limit to 3-8 high-value claims total. Do not invent facts.

Sections:

{sections_block}
"""
        resp = model.generate_content(prompt)
        raw = (getattr(resp, "text", None) or "").strip()
        data = json.loads(raw) if raw else {}
        items = data.get("claims", []) if isinstance(data, dict) else []
        claims: List[Dict[str, Any]] = []
        for it in items:
            try:
                claims.append({
                    "filename": filename,
                    "page_number": int(it.get("page_number") or (chosen_pages[0] if chosen_pages else 1)),
                    "statement": (it.get("statement") or "").strip(),
                    "quotes": it.get("quotes", []) or [],
                })
            except Exception:
                continue
        if claims:
            return claims[: max_per_doc]
    except Exception:
        pass

    # Fallback to snippets if JSON parsing or LLM fails
    claims: List[Dict[str, Any]] = []
    for p in chosen_pages:
        joined = page_full.get(p, "")
        claims.append({
            "filename": filename,
            "page_number": p,
            "snippet": joined[:800],
        })
    return claims


def _gemini_cross_compare(doc_claims: List[Dict[str, Any]], focus: Optional[str] = None) -> Dict[str, Any]:
    """Use Gemini to compare claims across documents, returning agreements and contradictions with references."""
    if genai is None:
        return {"agreements": [], "contradictions": [], "notes": []}
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return {"agreements": [], "contradictions": [], "notes": []}
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        generation_config={"response_mime_type": "application/json"}
    )

    refs: List[str] = []
    for i, c in enumerate(doc_claims):
        line = f"[{i+1}] file={c.get('filename')} page={c.get('page_number')}\n"
        if c.get("statement"):
            line += f"CLAIM: {c.get('statement')}\n"
        if c.get("quotes"):
            try:
                qs = c.get("quotes") or []
                for q in qs[:2]:
                    if isinstance(q, str) and q.strip():
                        line += f"QUOTE: {q.strip()}\n"
            except Exception:
                pass
        if c.get("snippet") and not c.get("statement"):
            line += c.get("snippet")
        refs.append(line.strip())
    refs_block = "\n\n".join(refs)

    prompt = f"""
You are comparing evidence across multiple PDFs. Read the references and identify (for the topic below if provided).
- Agreements: statements that are supported by two or more sources (list each statement once).
- Contradictions: statements that are in tension or conflict between sources.

Return a single JSON object with these top-level keys ONLY:
- "agreements": array of items
- "contradictions": array of items
- "notes": optional array (can be empty)

Each item in agreements/contradictions MUST have:
- "statement": concise sentence.
- "support": array of objects like {"file": string, "page_number": number}
- "quotes": array of 1-3 short quotes (<=120 chars) drawn from the supporting refs.

If no clear items exist, return empty arrays for "agreements" and "contradictions".

Topic (optional): {focus or 'None'}

References:

{refs_block}
"""

    try:
        resp = model.generate_content(prompt)
        raw = (getattr(resp, "text", None) or "").strip()
        data = json.loads(raw) if raw else {}
        return {
            "agreements": data.get("agreements", []) if isinstance(data, dict) else [],
            "contradictions": data.get("contradictions", []) if isinstance(data, dict) else [],
            "notes": data.get("notes", []) if isinstance(data, dict) else [],
        }
    except Exception:
        return {"agreements": [], "contradictions": [], "notes": []}


@app.post("/cross-insights")
async def cross_insights(req: CrossInsightsRequest):
    """Compare uploaded PDFs to find supporting and contradicting points.
    If req.filenames is not provided, all PDFs in document_library are used.
    Returns agreements and contradictions with references back to files/pages.
    """
    # Determine files to analyze
    if req.filenames:
        files = [f for f in req.filenames if (_docs_dir / f).is_file() and f.lower().endswith(".pdf")]
    else:
        try:
            files = [p.name for p in _docs_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
        except Exception:
            files = []
    files.sort()
    if len(files) < 2:
        raise HTTPException(status_code=400, detail="At least two PDFs are required for cross-insights")

    # Collect claims with simple per-file caching based on (mtime,size)
    all_claims: List[Dict[str, Any]] = []
    cache_key_parts = []
    loop = asyncio.get_running_loop()
    tasks = []
    for f in files:
        sig = _file_signature(f) + ("|deep" if req.deep else "|fast")
        cache_key_parts.append(sig)
        if (not req.force) and (sig in _doc_claims_cache):
            # Use cached directly
            all_claims.extend(_doc_claims_cache[sig])
            continue
        # Offload extraction to background thread
        def _job(file=f, signature=sig):
            c = _extract_doc_claims(file, max_per_doc=max(2, req.max_per_doc), deep=bool(req.deep))
            _doc_claims_cache[signature] = c
            return c
        tasks.append(loop.run_in_executor(_bg_executor, _job))

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            all_claims.extend(r or [])

    if not all_claims:
        return {"agreements": [], "contradictions": [], "notes": []}

    cross_key = _hash_short("|".join(cache_key_parts) + f"|m{req.max_per_doc}|deep{1 if req.deep else 0}|focus{(req.focus or '').strip().lower()}")
    cached = _cross_insights_cache.get(cross_key)
    if (not req.force) and (cached is not None):
        return cached

    result = _gemini_cross_compare(all_claims, focus=req.focus)
    # Heuristic retry: if both arrays empty but we have many claims, try once more with a narrowed focus built from frequent terms
    if not result.get("agreements") and not result.get("contradictions") and len(all_claims) >= 4:
        try:
            # Build a crude focus from top words across claims/snippets
            text_blobs = []
            for c in all_claims[:10]:
                if c.get("statement"):
                    text_blobs.append(str(c.get("statement")))
                elif c.get("snippet"):
                    text_blobs.append(str(c.get("snippet"))[:200])
            blob = " ".join(text_blobs)
            # pick a few frequent keywords (letters only)
            words = re.findall(r"[A-Za-z]{5,}", blob.lower())
            from collections import Counter
            top = [w for w, _ in Counter(words).most_common(5)]
            alt_focus = " ".join(top[:3]) if top else None
            if alt_focus:
                result = _gemini_cross_compare(all_claims, focus=alt_focus)
        except Exception:
            pass
    # Cache and respond (optionally include claims for debugging)
    _cross_insights_cache[cross_key] = result
    if req.include_claims:
        return {**result, "claims": all_claims}
    return result


class GenerateAudioRequest(BaseModel):
    text: Optional[str] = None
    filename: Optional[str] = None
    page_number: Optional[int] = None
    voice: Optional[str] = None  # optional, used best-effort for local pyttsx3
    format: Optional[str] = None  # mp3 or wav (hf_dia returns mp3; pyttsx3 outputs wav)
    podcast: Optional[bool] = False  # if true, use more human/podcast-like narration
    accent: Optional[str] = None  # e.g. en-US, en-GB, en-IN, es-ES
    style: Optional[str] = None   # e.g. "female", "male", or custom speaker id
    expressiveness: Optional[str] = None  # e.g. "high", "medium", "low"
    speakers: Optional[Dict[str, str]] = None  # optional mapping: {"A": "voiceA", "B": "voiceB"}
    entire_pdf: Optional[bool] = False  # if true, generate podcast for entire PDF
    two_speakers: Optional[bool] = None  # explicit control for two-speaker mode


def _gemini_script(text: str, podcast: bool = False, accent: Optional[str] = None, style: Optional[str] = None, expressiveness: Optional[str] = None, two_speakers: bool = False) -> str:
    """Use Gemini to convert raw context into a narration or dialogue script.
    When podcast=True or expressiveness is specified, produce a warmer, more natural script.
    Accent/style hints are woven subtly (no phonetic spellings) to encourage region-appropriate phrasing.
    If two_speakers=True, produce alternating lines for "Speaker A" and "Speaker B".
    """
    if genai is None:
        return text[:1500]
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return text[:1500]
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        generation_config={
            "response_mime_type": "text/plain"
        }
    )
    # Build dynamic guidance
    accent_hint = f"Accent preference: {accent}." if accent else ""
    style_hint = f" Voice/style hint: {style}." if style else ""
    expr_level = (expressiveness or ("high" if podcast else "medium"))
    expr_hint = f" Target expressiveness: {expr_level}." if expr_level else ""

    if two_speakers:
        prompt = f"""
You are an expert podcast writer creating engaging conversational content. Convert the following into a natural, lively dialogue between two knowledgeable hosts labeled "Speaker 1" and "Speaker 2".

Guidelines for natural podcast dialogue:
- Speaker 1 tends to be more analytical and asks probing questions
- Speaker 2 is more enthusiastic and provides vivid explanations and examples
- Create natural back-and-forth with occasional reactions and building on each other's points
- Include conversational elements like "Oh, that's fascinating!", "Wait, so you're saying...", "Exactly! And here's another thing..."
- Vary sentence lengths naturally - some short reactions, some longer explanations
- Target 3-5 minutes of engaging conversation
- Stay grounded in the provided content - don't invent facts
- Format EXACTLY as:
Speaker 1: [their dialogue]
Speaker 2: [their response]
Speaker 1: [continuation]
(etc.)

{accent_hint}{style_hint}{expr_hint}

Content to discuss:
{text}
"""
    elif podcast or expressiveness:
        prompt = f"""
You are a professional podcast narrator. Rewrite the following content as a warm, highly natural spoken narration.
Guidelines:
- Conversational, human, fluid phrasing; no bullet lists.
- Vary rhythm & sentence length; insert implicit short pauses with commas (do NOT write stage directions).
- Avoid robotic repetition; add light connective tissue for flow if needed (do not invent facts).
- No URLs, no markdown, no list formatting.
- Keep within ~220 words.
{accent_hint}{style_hint}{expr_hint}

Content:
{text}
"""
    else:
        prompt = f"""
Rewrite the content into a concise, natural narration (15-60 seconds). Conversational tone, no lists, no URLs.
{accent_hint}{style_hint}{expr_hint}

Content:
{text}
"""
    try:
        resp = model.generate_content(prompt)
        raw = (getattr(resp, "text", None) or "").strip()
        return raw or text[:1500]
    except Exception:
        return text[:1500]


def _synthesize_speech(text: str, voice: Optional[str] = None, fmt: Optional[str] = None, accent: Optional[str] = None, style: Optional[str] = None, deterministic_basename: Optional[str] = None, provider_override: Optional[str] = None) -> Tuple[str, str]:
    """Synthesize speech from text into a file using the selected provider.
    Preference: Edge-TTS for natural voices, then Hugging Face (Dia-1.6B), then offline pyttsx3.
    You can force provider via env TTS_PROVIDER: 'edge_tts', 'hf_dia' or 'pyttsx3'.
    Returns (filename, public_relative_url).
    """
    provider = (provider_override or os.getenv("TTS_PROVIDER") or "").lower().strip()
    hf_token = os.getenv("HUGGINGFACE_API_TOKEN")
    hf_model = os.getenv("HF_DIA_MODEL", "nari-labs/Dia-1.6B")

    # Always use Gemini TTS implementation
    if genai_speech is None or genai_types is None:
        raise HTTPException(status_code=500, detail="google-genai not installed on server")
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not configured on server")
    try:
        client = genai_speech.Client(api_key=api_key)
        model_name = (os.getenv("GEMINI_TTS_MODEL") or "gemini-2.5-flash-preview-tts").strip()
        candidate_models = [m for m in [model_name, "gemini-2.5-flash-preview-tts"] if m]

        contents = [genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=text)])]

        single_voice_name = (voice or style or os.getenv("GEMINI_VOICE_A") or "Charon").strip()
        single_voice_cfg = genai_types.SpeechConfig(
            voice_config=genai_types.VoiceConfig(
                prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=single_voice_name)
            )
        )

        multi_cfg = None
        if style and "," in (style or ""):
            a, b = [s.strip() for s in style.split(",", 1)]
            if re.search(r"^\s*Alex:\s*", text, flags=re.IGNORECASE | re.MULTILINE):
                spk1, spk2 = "Alex", "Jordan"
            elif re.search(r"^\s*Speaker\s*1:\s*", text, flags=re.IGNORECASE | re.MULTILINE):
                spk1, spk2 = "Speaker 1", "Speaker 2"
            else:
                spk1, spk2 = "Speaker 1", "Speaker 2"
            multi_cfg = genai_types.MultiSpeakerVoiceConfig(
                speaker_voice_configs=[
                    genai_types.SpeakerVoiceConfig(
                        speaker=spk1,
                        voice_config=genai_types.VoiceConfig(prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=a or os.getenv("GEMINI_VOICE_A", "Charon")))
                    ),
                    genai_types.SpeakerVoiceConfig(
                        speaker=spk2,
                        voice_config=genai_types.VoiceConfig(prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=b or os.getenv("GEMINI_VOICE_B", "Puck")))
                    ),
                ]
            )
        use_multi = bool(multi_cfg) or bool(re.search(r"^\s*(Speaker\s*\d+|Alex|Jordan)\s*:\s*", text, flags=re.IGNORECASE | re.MULTILINE))

        gen_cfg = genai_types.GenerateContentConfig(
            temperature=1,
            response_modalities=["audio"],
            speech_config=(genai_types.SpeechConfig(multi_speaker_voice_config=multi_cfg) if use_multi else single_voice_cfg),
        )

        data_buf = bytearray()
        mime_type: Optional[str] = None
        last_err: Optional[Exception] = None
        
        for m in candidate_models:
            try:
                data_buf.clear()
                mime_type = None
                for chunk in client.models.generate_content_stream(model=m, contents=contents, config=gen_cfg):
                    if (chunk.candidates is None or 
                        chunk.candidates[0].content is None or 
                        chunk.candidates[0].content.parts is None):
                        continue
                    for part in chunk.candidates[0].content.parts:
                        if (getattr(part, "inline_data", None) and 
                            getattr(part.inline_data, "data", None)):
                            if mime_type is None:
                                mime_type = getattr(part.inline_data, "mime_type", None)
                                print(f"[DEBUG] Gemini mime_type: {mime_type}")
                            data_buf.extend(part.inline_data.data)
                
                if data_buf:
                    last_err = None
                    print(f"[DEBUG] Got {len(data_buf)} bytes of audio data")
                    break
            except Exception as e:
                last_err = e
                continue
        
        if not data_buf and last_err is not None:
            raise last_err
        if not data_buf:
            raise HTTPException(status_code=502, detail="Gemini returned no audio; ensure model supports audio and API key has access")

        ext = "wav"
        audio_data = bytes(data_buf)
        if mime_type and "/" in mime_type:
            mt = mime_type.split("/")[-1].lower()
            print(f"[DEBUG] Detected format: {mt} from mime: {mime_type}")
            if "wav" in mt:
                ext = "wav"
            elif "mpeg" in mt or "mp3" in mt:
                ext = "mp3"
            elif "ogg" in mt:
                ext = "ogg"
            else:
                print(f"[DEBUG] Converting {mime_type} to WAV")
                audio_data = _convert_to_wav(audio_data, mime_type)
                ext = "wav"

        base = f"{deterministic_basename}.{ext}" if deterministic_basename else f"tts_{uuid.uuid4().hex[:8]}_gem.{ext}"
        out_path = _audio_dir / base
        out_path.write_bytes(audio_data)
        return base, f"/audio/{base}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini speech failed: {e}")

    # If Google TTS selected, use that
    if False:  # Disabled - using Gemini TTS for all providers
        if google_tts is None:
            raise HTTPException(status_code=500, detail="google-cloud-texttospeech not installed on server")
        # Auth: prefer explicit JSON in env, else default credentials (file path handled by library via GOOGLE_APPLICATION_CREDENTIALS)
        creds_json = os.getenv("GOOGLE_TTS_SERVICE_ACCOUNT_JSON", "").strip()
        try:
            if creds_json:
                credentials = gsa.Credentials.from_service_account_info(json.loads(creds_json))
                client = google_tts.TextToSpeechClient(credentials=credentials)
            else:
                client = google_tts.TextToSpeechClient()
        except Exception as e:  # pragma: no cover
            raise HTTPException(status_code=500, detail=f"Google TTS auth failed: {e}")

        # Voice: accept explicit voice name from 'voice' or 'style'; else default by accent/locale
        voice_name = (voice or style or os.getenv("GOOGLE_TTS_VOICE_A") or "en-US-Neural2-C").strip()
        language_code = (accent or "en-US")
        if voice_name and "-" in voice_name:
            # derive language from voice eg en-US-Neural2-C -> en-US
            try:
                parts = voice_name.split("-")[:2]
                language_code = f"{parts[0]}-{parts[1]}"
            except Exception:
                pass

        synthesis_input = google_tts.SynthesisInput(text=text)
        voice_params = google_tts.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name
        )
        audio_encoding = (os.getenv("GOOGLE_TTS_AUDIO_ENCODING") or "MP3").upper()
        if audio_encoding not in ("MP3", "LINEAR16", "OGG_OPUS"):
            audio_encoding = "MP3"
        audio_config = google_tts.AudioConfig(audio_encoding=getattr(google_tts.AudioEncoding, audio_encoding))

        try:
            response = client.synthesize_speech(input=synthesis_input, voice=voice_params, audio_config=audio_config)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Google TTS synth failed: {e}")

        ext = "mp3" if audio_encoding == "MP3" else ("wav" if audio_encoding == "LINEAR16" else "ogg")
        base = f"{deterministic_basename}.{ext}" if deterministic_basename else f"tts_{uuid.uuid4().hex[:8]}.{ext}"
        out_path = _audio_dir / base
        try:
            out_path.write_bytes(response.audio_content)
        except Exception as e:  # pragma: no cover
            raise HTTPException(status_code=500, detail=f"Failed to write audio: {e}")
        return base, f"/audio/{base}"

    # Gemini Speech (google-genai) - updated to match reference implementation
    if False:  # Disabled - using Gemini TTS for all providers
        if genai_speech is None or genai_types is None:
            raise HTTPException(status_code=500, detail="google-genai not installed on server")
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise HTTPException(status_code=503, detail="GEMINI_API_KEY not configured on server")
        try:
            client = genai_speech.Client(api_key=api_key)
            # Use the correct TTS model as per reference (flash, not pro)
            model_name = (os.getenv("GEMINI_TTS_MODEL") or "gemini-2.5-flash-preview-tts").strip()
            candidate_models = [m for m in [model_name, "gemini-2.5-flash-preview-tts"] if m]

            # Build contents
            contents = [genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=text)])]

            # Voice selection - match reference code patterns
            single_voice_name = (voice or style or os.getenv("GEMINI_VOICE_A") or "Charon").strip()
            single_voice_cfg = genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=single_voice_name)
                )
            )

            # Multi-speaker when the script contains labeled lines or style specifies two voices
            multi_cfg = None
            if style and "," in (style or ""):
                a, b = [s.strip() for s in style.split(",", 1)]
                if re.search(r"^\s*Alex:\s*", text, flags=re.IGNORECASE | re.MULTILINE):
                    spk1, spk2 = "Alex", "Jordan"
                elif re.search(r"^\s*Speaker\s*1:\s*", text, flags=re.IGNORECASE | re.MULTILINE):
                    spk1, spk2 = "Speaker 1", "Speaker 2"
                else:
                    spk1, spk2 = "Speaker 1", "Speaker 2"
                multi_cfg = genai_types.MultiSpeakerVoiceConfig(
                    speaker_voice_configs=[
                        genai_types.SpeakerVoiceConfig(
                            speaker=spk1,
                            voice_config=genai_types.VoiceConfig(prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=a or os.getenv("GEMINI_VOICE_A", "Charon")))
                        ),
                        genai_types.SpeakerVoiceConfig(
                            speaker=spk2,
                            voice_config=genai_types.VoiceConfig(prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=b or os.getenv("GEMINI_VOICE_B", "Puck")))
                        ),
                    ]
                )
            use_multi = bool(multi_cfg) or bool(re.search(r"^\s*(Speaker\s*\d+|Alex|Jordan)\s*:\s*", text, flags=re.IGNORECASE | re.MULTILINE))

            # Generation config - corrected response_modalities to match reference
            gen_cfg = genai_types.GenerateContentConfig(
                temperature=1,
                response_modalities=["audio"],  # Fixed: lowercase "audio" as per reference
                speech_config=(genai_types.SpeechConfig(multi_speaker_voice_config=multi_cfg) if use_multi else single_voice_cfg),
            )

            # Use streaming approach like reference for better reliability
            data_buf = bytearray()
            mime_type: Optional[str] = None
            last_err: Optional[Exception] = None
            
            for m in candidate_models:
                try:
                    data_buf.clear()
                    mime_type = None
                    for chunk in client.models.generate_content_stream(model=m, contents=contents, config=gen_cfg):
                        if (chunk.candidates is None or 
                            chunk.candidates[0].content is None or 
                            chunk.candidates[0].content.parts is None):
                            continue
                        for part in chunk.candidates[0].content.parts:
                            if (getattr(part, "inline_data", None) and 
                                getattr(part.inline_data, "data", None)):
                                if mime_type is None:
                                    mime_type = getattr(part.inline_data, "mime_type", None)
                                    print(f"[DEBUG] Gemini mime_type: {mime_type}")
                                data_buf.extend(part.inline_data.data)
                    
                    if data_buf:  # Successfully got audio data
                        last_err = None
                        print(f"[DEBUG] Got {len(data_buf)} bytes of audio data")
                        break
                except Exception as e:
                    last_err = e
                    continue
            
            if not data_buf and last_err is not None:
                raise last_err
            if not data_buf:
                raise HTTPException(status_code=502, detail="Gemini returned no audio; ensure model supports audio and API key has access")

            # Convert to WAV if needed (following reference implementation)
            ext = "wav"
            audio_data = bytes(data_buf)
            if mime_type and "/" in mime_type:
                mt = mime_type.split("/")[-1].lower()
                print(f"[DEBUG] Detected format: {mt} from mime: {mime_type}")
                if "wav" in mt:
                    ext = "wav"
                elif "mpeg" in mt or "mp3" in mt:
                    ext = "mp3"
                elif "ogg" in mt:
                    ext = "ogg"
                else:
                    # Convert non-standard format to WAV like reference code
                    print(f"[DEBUG] Converting {mime_type} to WAV")
                    audio_data = _convert_to_wav(audio_data, mime_type)
                    ext = "wav"

            base = f"{deterministic_basename}.{ext}" if deterministic_basename else f"tts_{uuid.uuid4().hex[:8]}_gem.{ext}"
            out_path = _audio_dir / base
            out_path.write_bytes(audio_data)
            return base, f"/audio/{base}"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Gemini speech failed: {e}")

    # Edge TTS (free, natural voices)
    if False:  # Disabled - using Gemini TTS for all providers
        if edge_tts is None:
            raise HTTPException(status_code=500, detail="edge-tts not installed on server")
        voice_name = (voice or style or os.getenv("EDGE_TTS_VOICE_DEFAULT") or "en-US-AriaNeural")
        base = f"{deterministic_basename}.mp3" if deterministic_basename else f"tts_{uuid.uuid4().hex[:8]}.mp3"
        out_path = _audio_dir / base

        async def _edge_synth():
            communicate = edge_tts.Communicate(text=text, voice=voice_name)
            with open(out_path, "wb") as f:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])

        try:
            # Run a fresh event loop in this worker thread
            asyncio.run(_edge_synth())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Edge TTS synth failed: {e}")
        return base, f"/audio/{base}"

    # Decide provider: HF > pyttsx3 (skip Edge-TTS for now to avoid asyncio conflicts)
    use_hf = False  # Disabled - using Gemini TTS for all providers

    # Hugging Face Dia-1.6B via Inference API (mp3)
    if False:  # Disabled - using Gemini TTS for all providers
        if requests is None:
            raise HTTPException(status_code=500, detail="requests library not installed on server")
        url = f"https://api-inference.huggingface.co/models/{hf_model}"
        headers = {
            "Authorization": f"Bearer {hf_token}",
            "Accept": "audio/mpeg",
        }
        parameters: Dict[str, Any] = {}
        # Provide multiple possible keys to maximize compatibility across models
        if accent:
            # Normalize accent to language base for lang field (e.g. en-US -> en)
            base_lang = accent.split('-')[0]
            parameters["language"] = accent
            parameters["lang"] = base_lang
        if style:
            # Some models expect speaker or speaker_id
            parameters["speaker_id"] = style
            parameters["speaker"] = style
        payload: Dict[str, Any] = {"inputs": text}
        if parameters:
            payload["parameters"] = parameters
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=180)
        except Exception as e:  # pragma: no cover
            # Fall back to offline if network/model errors
            resp = None
        if resp is not None and resp.status_code == 503:
            # Model loading; surface a retryable error
            raise HTTPException(status_code=503, detail="TTS model loading, retry shortly")
        if resp is not None and resp.ok and resp.content:
            # Include short label for accent/style in filename for caching clarity
            tag_parts = []
            if accent:
                tag_parts.append(accent.replace('-', '').lower())
            if style:
                tag_parts.append(style.lower())
            tag = ("_" + "_".join(tag_parts)) if tag_parts else ""
            if deterministic_basename:
                base = f"{deterministic_basename}.mp3"
            else:
                base = f"tts_{uuid.uuid4().hex[:8]}_hf{tag}.mp3"
            out_path = _audio_dir / base
            try:
                out_path.write_bytes(resp.content)
            except Exception as e:  # pragma: no cover
                raise HTTPException(status_code=500, detail=f"Failed to write audio: {e}")
            rel_url = f"/audio/{base}"
            return base, rel_url
        # Otherwise: fall through to offline pyttsx3

    # Offline provider: pyttsx3 (WAV)
    if False:  # Disabled - using Gemini TTS for all providers
        raise HTTPException(status_code=500, detail="No TTS providers available. Install edge-tts, configure HUGGINGFACE_API_TOKEN, or install pyttsx3")
    ext = "wav"
    voice_name = voice or os.getenv("PYTTSX3_VOICE") or ""
    if deterministic_basename:
        base = f"{deterministic_basename}.{ext}"
    else:
        base = f"tts_{abs(hash(text))}_{(voice_name or 'default').replace(' ','_')}.{ext}"
    out_path = _audio_dir / base
    try:
        # Guard engine usage with a lock for thread safety
        with _pyttsx3_lock:
            engine = pyttsx3.init()
            if voice_name:
                # Try to select a matching voice id by name substring
                for v in engine.getProperty('voices'):
                    if voice_name.lower() in (v.name or '').lower():
                        engine.setProperty('voice', v.id)
                        break
            engine.save_to_file(text, str(out_path))
            engine.runAndWait()
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Local TTS failed: {e}")
    rel_url = f"/audio/{base}"
    return base, rel_url


@app.post("/generate-audio")
async def generate_audio(req: GenerateAudioRequest):
    """Generate (and cache) TTS audio from provided text or a specific page.
    Supports entire PDF podcast generation with natural two-speaker dialogue.
    Optimizations:
    - Script caching: repeated requests for same content + parameters reuse Gemini output.
    - Audio caching: identical script + voice/style/accent/provider returns existing file.
    - Offloaded synthesis to thread pool to avoid blocking event loop.
    """
    text = (req.text or "").strip()
    start_ts = time.time()
    try:
        print(f"[generate-audio] start podcast={bool(req.podcast)} two_speakers={bool(req.two_speakers)} entire_pdf={bool(req.entire_pdf)}")
    except Exception:
        pass
    
    # Handle entire PDF processing
    if req.entire_pdf and req.filename:
        file_path = str((_docs_dir / req.filename).absolute())
        text = _extract_entire_pdf_text(file_path).strip()
        if not text:
            raise HTTPException(status_code=400, detail="No extractable text from PDF")
    elif not text:
        if not (req.filename and req.page_number):
            raise HTTPException(status_code=400, detail="Provide text, filename + page_number, or filename + entire_pdf=true")
        file_path = str((_docs_dir / req.filename).absolute())
        text = _extract_page_text(file_path, req.page_number).strip()
        if not text:
            raise HTTPException(status_code=400, detail="No extractable text for the given page")

    # Determine if two-speaker mode should be used
    two_speakers = req.two_speakers if req.two_speakers is not None else bool(req.podcast)
    
    # --- Script caching ---
    script_key = "|".join([
        _hash_short(text[:1000]),  # Use first 1000 chars for key to handle long texts
        f"p{1 if req.podcast else 0}",
        f"ts{1 if two_speakers else 0}",
        f"ep{1 if req.entire_pdf else 0}",
        req.accent or "-",
        req.style or "-",
        req.expressiveness or "-",
    ])
    
    script = _script_cache.get(script_key)
    if script is None:
        script = _gemini_script(
            text,
            podcast=bool(req.podcast),
            accent=req.accent,
            style=req.style,
            expressiveness=req.expressiveness,
            two_speakers=two_speakers,
        )
        _script_cache[script_key] = script
    try:
        print(f"[generate-audio] script ready len={len(script or '')} two_speakers={two_speakers}")
    except Exception:
        pass

    provider = (os.getenv("TTS_PROVIDER") or "").lower().strip() or "auto"

    # Deterministic base name for caching (does not include random UUID)
    deterministic_base = "_".join([
        "tts",
        _hash_short(script),
        provider,
        (req.accent or "na").replace('-', ''),
        (req.style or "na"),
        f"ts{1 if two_speakers else 0}",
    ])

    audio_key = "|".join([
        deterministic_base,
        req.voice or "-",
    ])
    cached_audio = _audio_cache.get(audio_key)
    if cached_audio:
        return {"url": cached_audio[1], "cached": True}
    # Disk-backed cache: if file exists from a previous run, reuse it
    for ext in ("mp3", "wav"):
        candidate = _audio_dir / f"{deterministic_base}.{ext}"
        if candidate.is_file():
            rel_url = f"/audio/{candidate.name}"
            _audio_cache[audio_key] = (candidate.name, rel_url)
            return {"url": rel_url, "cached": True}

    loop = asyncio.get_running_loop()
    # If not podcast/two-speaker, synthesize as single take
    if not two_speakers:
        try:
            filename, rel_url = await loop.run_in_executor(
                _tts_executor,
                lambda: _synthesize_with_fallback(
                    script,
                    deterministic_base,
                    req.voice,
                    req.accent,
                    req.style,
                ),
            )
        except HTTPException:
            raise
        except Exception as e:  # pragma: no cover
            raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {e}")

        _audio_cache[audio_key] = (filename, rel_url)
        try:
            print(f"[generate-audio] single-speaker done provider={provider} url={rel_url} elapsed={time.time()-start_ts:.1f}s")
        except Exception:
            pass
        return {"url": rel_url, "cached": False}

    # --- Two-speaker podcast flow ---
    # Parse the dialogue into (speaker, line) pairs - support multiple formats robustly
    lines: List[Tuple[str, str]] = []
    pat = re.compile(r"^(?P<label>(?:Speaker\s*[12]|Alex|Jordan|Speaker\s*[AB]|[AB])):\s*(?P<text>.+)$", re.IGNORECASE)
    for raw_line in (script or "").splitlines():
        line = (raw_line or "").strip()
        if not line:
            continue
        m = pat.match(line)
        if not m:
            continue
        label = (m.group("label") or "").strip()
        content = (m.group("text") or "").strip()
        # Normalize labels
        if re.fullmatch(r"Speaker\s*1", label, flags=re.IGNORECASE):
            spk = "Speaker 1"
        elif re.fullmatch(r"Speaker\s*2", label, flags=re.IGNORECASE):
            spk = "Speaker 2"
        elif re.fullmatch(r"[Aa]", label):
            spk = "Speaker A"
        elif re.fullmatch(r"[Bb]", label):
            spk = "Speaker B"
        elif re.fullmatch(r"Alex", label, flags=re.IGNORECASE):
            spk = "Speaker 1"
        elif re.fullmatch(r"Jordan", label, flags=re.IGNORECASE):
            spk = "Speaker 2"
        else:
            spk = label.title()
        if content:
            lines.append((spk, content))
        
    if not lines:
        # Fallback to single speaker if parsing failed
        try:
            filename, rel_url = await loop.run_in_executor(
                _tts_executor,
                lambda: _synthesize_speech(
                    script,
                    voice=req.voice,
                    fmt=req.format,
                    accent=req.accent,
                    style=req.style,
                    deterministic_basename=deterministic_base,
                ),
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {e}")
        _audio_cache[audio_key] = (filename, rel_url)
        return {"url": rel_url, "cached": False}

    # If Gemini is the provider, prefer single-call multi-speaker synthesis for the whole script
    provider_eff = (os.getenv("TTS_PROVIDER") or "").lower().strip()
    if provider_eff == "gemini":
        try:
            filename, rel_url = await loop.run_in_executor(
                _tts_executor,
                lambda: _synthesize_speech(
                    script,
                    voice=req.voice,
                    fmt=req.format,
                    accent=req.accent,
                    style=req.style,
                    deterministic_basename=deterministic_base,
                    provider_override="gemini",
                ),
            )
            _audio_cache[audio_key] = (filename, rel_url)
            # No per-line parts/chapters available from single-pass synthesis
            try:
                print(f"[generate-audio] gemini multi-speaker done url={rel_url} elapsed={time.time()-start_ts:.1f}s")
            except Exception:
                pass
            return {"url": rel_url, "cached": False}
        except Exception as e:
            try:
                print(f"[generate-audio] gemini multi-speaker error: {e}")
            except Exception:
                pass
            # Fall back to per-line synthesis below
            pass

    # Enhanced voice mapping with natural-sounding defaults
    spk_voice: Dict[str, Optional[str]] = {}
    
    # Set default voices for natural podcast experience
    provider_eff = (os.getenv("TTS_PROVIDER") or "").lower().strip()
    if provider_eff == "google":
        # Use Google voices from env
        vA = os.getenv("GOOGLE_TTS_VOICE_A", "en-US-Neural2-C")
        vB = os.getenv("GOOGLE_TTS_VOICE_B", "en-GB-Neural2-B")
        if "Alex" in [spk for spk, _ in lines]:
            spk_voice["Alex"] = vA
            spk_voice["Jordan"] = vB
        else:
            spk_voice["Speaker A"] = vA
            spk_voice["Speaker B"] = vB
    elif provider_eff == "edge_tts":
        # Good free Edge voices
        vA = os.getenv("EDGE_TTS_VOICE_A", "en-US-GuyNeural")
        vB = os.getenv("EDGE_TTS_VOICE_B", "en-GB-SoniaNeural")
        if "Alex" in [spk for spk, _ in lines]:
            spk_voice["Alex"] = vA
            spk_voice["Jordan"] = vB
        else:
            spk_voice["Speaker A"] = vA
            spk_voice["Speaker B"] = vB
    elif provider_eff == "gemini":
        # Gemini prebuilt voices
        vA = os.getenv("GEMINI_VOICE_A", "Charon")
        vB = os.getenv("GEMINI_VOICE_B", "Aoede")
        if "Alex" in [spk for spk, _ in lines]:
            spk_voice["Alex"] = vA
            spk_voice["Jordan"] = vB
        elif "Speaker 1" in [spk for spk, _ in lines] or "Speaker 2" in [spk for spk, _ in lines]:
            spk_voice["Speaker 1"] = vA
            spk_voice["Speaker 2"] = vB
        else:
            spk_voice["Speaker A"] = vA
            spk_voice["Speaker B"] = vB
    else:
        # Local defaults (pyttsx3 / hf)
        if "Alex" in [spk for spk, _ in lines]:
            spk_voice["Alex"] = "en_UK-jenny-medium"  # Analytical voice
            spk_voice["Jordan"] = "en_US-danny-low"   # Enthusiastic voice
        else:
            spk_voice["Speaker A"] = "en_UK-jenny-medium"
            spk_voice["Speaker B"] = "en_US-danny-low"
    
    # Override with user-provided speakers if available
    if req.speakers:
        for speaker_key, voice_val in req.speakers.items():
            if speaker_key in ["A", "Alex"]:
                spk_voice["Alex"] = voice_val
                spk_voice["Speaker A"] = voice_val
            elif speaker_key in ["B", "Jordan"]:
                spk_voice["Jordan"] = voice_val
                spk_voice["Speaker B"] = voice_val
            else:
                spk_voice[speaker_key] = voice_val

    # Generate individual clips with pauses
    clip_files: List[Path] = []
    clip_urls: List[str] = []
    for idx, (spk, content) in enumerate(lines):
        basename = f"{deterministic_base}_part{idx:03d}"
        voice_choice = spk_voice.get(spk) or req.voice
        # Derive accent from Google voice name if provider=google and accent not explicitly set
        eff_accent = req.accent
        provider_eff = (os.getenv("TTS_PROVIDER") or "").lower().strip()
        if provider_eff == "google" and not eff_accent and isinstance(voice_choice, str) and "-" in voice_choice:
            try:
                parts = voice_choice.split("-")[:2]
                eff_accent = f"{parts[0]}-{parts[1]}"
            except Exception:
                pass
        # Provider plan: if a provider is explicitly set via TTS_PROVIDER, use ONLY that provider
        # to avoid mixing voices. Otherwise, try a sensible fallback order.
        tried: List[str] = []
        fn = None
        url_rel = None
        pref = (os.getenv("TTS_PROVIDER") or "").lower().strip()
        all_providers = ["gemini", "google", "edge_tts", "hf_dia", "pyttsx3"]
        if pref in all_providers:
            providers_plan = [pref]
        else:
            providers_plan = all_providers
        for prov in providers_plan:
            tried.append(prov)
            try:
                candidate = await loop.run_in_executor(
                    _tts_executor,
                    lambda p=prov: _synthesize_speech(
                        content,
                        voice=voice_choice,
                        fmt=req.format,
                        accent=eff_accent or req.accent,
                        style=None,
                        # Tag per-line filename with provider to reflect actual synthesis source
                        deterministic_basename=f"{basename}_{p}",
                        provider_override=p,
                    ),
                )
                if candidate and isinstance(candidate, tuple):
                    fn, url_rel = candidate
                    break
            except Exception as e:
                try:
                    print(f"[generate-audio] per-line provider={prov} error: {e}")
                except Exception:
                    pass
                continue
        if not fn or not url_rel:
            # Skip failed lines, continue others
            try:
                print(f"[generate-audio] line {idx} failed tried={tried}")
            except Exception:
                pass
            continue
        clip_files.append((_audio_dir / fn))
        clip_urls.append(url_rel)

    if not clip_files:
        raise HTTPException(status_code=500, detail="No audio clips generated for podcast")

    # Build chapter list with durations using ffprobe (best-effort)
    chapters: List[Dict[str, Any]] = []
    durations_sec: List[float] = []
    try:
        import subprocess
        for i, path in enumerate(clip_files):
            try:
                cmd = [
                    'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1', path.name
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_audio_dir), timeout=10)
                dur = float(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip() else 0.0
            except Exception:
                dur = 0.0
            durations_sec.append(max(0.0, dur))
    except Exception:
        durations_sec = [0.0 for _ in clip_files]
    # Accumulate timestamps
    t = 0.0
    for i, (spk, (url_rel)) in enumerate(zip([s for s, _ in lines], clip_urls)):
        dur = durations_sec[i] if i < len(durations_sec) else 0.0
        start_ms = int(round(t * 1000))
        end_ms = int(round((t + dur) * 1000))
        chapters.append({
            "index": i,
            "speaker": [s for s, _ in lines][i],
            "text": [t for _, t in lines][i],
            "start_ms": start_ms,
            "end_ms": end_ms,
            "part_url": url_rel,
        })
        t += dur

    # Concatenation using ffmpeg (re-encode to MP3 for robustness)
    try:
        import subprocess
        import sys
        
        final_name = f"{deterministic_base}_podcast.mp3"
        final_path = _audio_dir / final_name
        
        # Create a file list for ffmpeg concat
        filelist_path = _audio_dir / f"{deterministic_base}_files.txt"
        with open(filelist_path, 'w', encoding='utf-8') as f:
            for clip_file in clip_files:
                # Use relative paths to avoid issues with special characters
                f.write(f"file '{clip_file.name}'\n")
        
        # Use ffmpeg to concatenate and re-encode to MP3 (handles mixed inputs)
        ffmpeg_cmd = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', str(filelist_path), '-c:a', 'libmp3lame', '-b:a', '160k', '-ar', '44100', str(final_path)
        ]
        
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, cwd=str(_audio_dir))
        
        # Clean up temp file list only (keep parts for chapter playback / fallback)
        filelist_path.unlink(missing_ok=True)
        
        if result.returncode == 0 and final_path.exists():
            final_url = f"/audio/{final_name}"
            _audio_cache[audio_key] = (final_name, final_url)
            try:
                print(f"[generate-audio] concat success url={final_url} elapsed={time.time()-start_ts:.1f}s")
            except Exception:
                pass
            return {"url": final_url, "parts": clip_urls, "chapters": chapters, "cached": False}
        else:
            # Fallback: return the first clip if concatenation fails
            if clip_urls:
                first_clip = clip_urls[0]
                _audio_cache[audio_key] = (clip_files[0].name, first_clip)
                try:
                    print(f"[generate-audio] concat failed, returning first clip elapsed={time.time()-start_ts:.1f}s")
                except Exception:
                    pass
                return {"url": first_clip, "parts": clip_urls, "chapters": chapters, "cached": False}
            raise HTTPException(status_code=500, detail="Audio concatenation failed")
            
    except FileNotFoundError:
        # ffmpeg not available, fallback to first clip
        if clip_urls:
            first_clip = clip_urls[0]
            _audio_cache[audio_key] = (clip_files[0].name, first_clip)
            return {"url": first_clip, "parts": clip_urls, "chapters": chapters, "cached": False, "note": "ffmpeg not available, returning first clip only"}
        raise HTTPException(status_code=500, detail="No audio processing tools available")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process audio: {e}")

@app.get("/")
def read_root():
    return {"message": "Hello World"}


@app.post("/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """Accept multiple file uploads and save them to backend/document_library.
    Returns the list of saved filenames.
    """
    base_dir = Path(__file__).resolve().parent
    save_dir = base_dir / "document_library"
    save_dir.mkdir(parents=True, exist_ok=True)

    saved: List[str] = []
    for f in files:
        # Prevent path traversal by using only the name component
        safe_name = Path(f.filename).name if f.filename else "upload.bin"
        target = save_dir / safe_name
        content = await f.read()
        with open(target, "wb") as out:
            out.write(content)
        saved.append(safe_name)

        # Process the saved PDF into chunks + embeddings and add to the vector store
        try:
            processed = process_pdf(str(target))
            if processed:
                store.add_documents(processed, filename=safe_name)
        except Exception as e:
            # Skip processing errors per-file but continue others
            # Optionally, log e
            pass

    return {"saved": saved}

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("UVICORN_HOST", "127.0.0.1")
    port = int(os.getenv("UVICORN_PORT", "8001"))
    uvicorn.run("main:app", host=host, port=port, reload=True)
