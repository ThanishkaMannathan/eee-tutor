"""
knowledge.py — RAG Knowledge Base Engine
=========================================
This file manages the self-growing knowledge base using ChromaDB.

What it does:
  1. Indexes PDF files and text notes from the /knowledge folder
  2. Automatically detects new files and adds them to the vector database
  3. Fetches fresh EEE articles weekly from RSS feeds and stores summaries
  4. Retrieves relevant context for lessons and doubt-answering (RAG)

RAG = Retrieval-Augmented Generation:
  Instead of relying only on Claude's training data, we first search our
  local knowledge base for relevant content, then pass it to Claude.
  This means your own notes and textbooks directly improve the lessons!

Dependencies: chromadb, sentence-transformers, PyMuPDF, feedparser
"""

import os
import json
import logging
import hashlib
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    import chromadb                         # Vector database for RAG
    from chromadb.config import Settings as ChromaSettings
except ImportError:
    chromadb = None
    ChromaSettings = None

try:
    import fitz                             # PyMuPDF — reads PDF files
except ImportError:
    fitz = None

try:
    import pypdf                            # Pure-Python PDF reader (cloud friendly)
except ImportError:
    pypdf = None

import feedparser                           # Reads RSS news feeds

try:
    from sentence_transformers import SentenceTransformer  # Local embeddings
except ImportError:
    SentenceTransformer = None

from dotenv import load_dotenv
import anthropic                            # Used to summarize RSS articles

load_dotenv()

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  PATHS AND CONSTANTS
# ─────────────────────────────────────────────

BASE_DIR       = os.path.dirname(__file__)
KNOWLEDGE_DIR  = os.path.join(BASE_DIR, "knowledge")   # Drop your PDFs here
CHROMA_DIR     = os.path.join(BASE_DIR, "chroma_db")   # Vector store location
INDEXED_LOG    = os.path.join(BASE_DIR, "data", "indexed_files.json")  # Track what's been indexed

# How many text characters per chunk (smaller = more precise retrieval)
CHUNK_SIZE     = 800
CHUNK_OVERLAP  = 100   # Characters shared between consecutive chunks

# How many relevant chunks to retrieve for context
TOP_K_RESULTS  = 4

# EEE RSS feeds to check weekly for new articles
EEE_RSS_FEEDS = [
    "https://spectrum.ieee.org/rss/fulltext",
    "https://www.electronics-tutorials.ws/feed",
    "https://hackaday.com/category/electronics/feed/",
    "https://www.allaboutcircuits.com/rss.xml",
    "https://circuitdigest.com/rss.xml",
]

# ─────────────────────────────────────────────
#  EMBEDDING MODEL (runs locally — no API cost!)
# ─────────────────────────────────────────────

# This will download the model on first run (~90 MB). Subsequent runs are instant.
_embedding_model = None

def _get_embedding_model():
    """Lazy-load the embedding model (loads only once per session)."""
    global _embedding_model
    if SentenceTransformer is None:
        return None
    if _embedding_model is None:
        try:
            logger.info("Loading sentence-transformer embedding model...")
            _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Embedding model loaded.")
        except Exception as e:
            logger.warning("Could not load embedding model: %s", e)
            return None
    return _embedding_model


def _embed_texts(texts: list) -> list:
    """Convert a list of text strings into embedding vectors."""
    model = _get_embedding_model()
    if model is None:
        return []
    try:
        embeddings = model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()
    except Exception:
        return []


# ─────────────────────────────────────────────
#  CHROMADB SETUP
# ─────────────────────────────────────────────

_chroma_client     = None
_notes_collection  = None   # For student PDFs and notes
_articles_collection = None # For RSS article summaries


def _get_chroma_client():
    """Lazy-load and return the ChromaDB client (singleton)."""
    global _chroma_client
    if chromadb is None:
        return None
    if _chroma_client is None:
        try:
            os.makedirs(CHROMA_DIR, exist_ok=True)
            _chroma_client = chromadb.PersistentClient(
                path     = CHROMA_DIR,
                settings = ChromaSettings(anonymized_telemetry=False)
            )
            logger.info("ChromaDB client initialized at: %s", CHROMA_DIR)
        except Exception as e:
            logger.warning("ChromaDB init error: %s", e)
            return None
    return _chroma_client


def _get_notes_collection():
    """Get (or create) the ChromaDB collection for student notes."""
    global _notes_collection
    if _notes_collection is None:
        client = _get_chroma_client()
        _notes_collection = client.get_or_create_collection(
            name              = "student_notes",
            metadata          = {"description": "Student PDFs, notes, and textbooks"},
            embedding_function = None   # We handle embeddings manually
        )
    return _notes_collection


def _get_articles_collection():
    """Get (or create) the ChromaDB collection for RSS articles."""
    global _articles_collection
    if _articles_collection is None:
        client = _get_chroma_client()
        _articles_collection = client.get_or_create_collection(
            name              = "eee_articles",
            metadata          = {"description": "Weekly EEE news and articles"},
            embedding_function = None
        )
    return _articles_collection


# ─────────────────────────────────────────────
#  PDF INDEXING
# ─────────────────────────────────────────────

def _load_indexed_log() -> dict:
    """Load the record of which files have already been indexed."""
    if os.path.exists(INDEXED_LOG):
        with open(INDEXED_LOG, "r") as f:
            return json.load(f)
    return {}


def _save_indexed_log(log: dict):
    """Save the updated indexed-files record."""
    os.makedirs(os.path.dirname(INDEXED_LOG), exist_ok=True)
    with open(INDEXED_LOG, "w") as f:
        json.dump(log, f, indent=2)


def _file_hash(filepath: str) -> str:
    """Compute MD5 hash of a file so we can detect changes."""
    hasher = hashlib.md5()
    with open(filepath, "rb") as f:
        hasher.update(f.read())
    return hasher.hexdigest()


def _extract_text_from_pdf(filepath: str) -> str:
    """Extract all text from a PDF file using pypdf or PyMuPDF."""
    try:
        if pypdf is not None:
            reader = pypdf.PdfReader(filepath)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            return text.strip()
        elif fitz is not None:
            doc  = fitz.open(filepath)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text.strip()
        return ""
    except Exception as e:
        logger.error("Failed to read PDF '%s': %s", filepath, str(e))
        return ""


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE,
                overlap: int = CHUNK_OVERLAP) -> list:
    """
    Split a long text into smaller overlapping chunks.
    Smaller chunks make retrieval more precise.
    Overlap ensures context isn't cut off at boundaries.
    """
    chunks = []
    start  = 0

    while start < len(text):
        end   = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():   # Only add non-empty chunks
            chunks.append(chunk)
        start = end - overlap   # Move forward with overlap

    return chunks


def index_knowledge_folder():
    """
    Scan the /knowledge folder for new or changed PDFs and text files.
    Index any new content into ChromaDB.
    Call this at startup and whenever files are added.
    """
    if _get_chroma_client() is None or _get_embedding_model() is None:
        logger.info("Knowledge base vector store not active. Skipping indexing.")
        return 0

    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
    indexed_log = _load_indexed_log()
    collection  = _get_notes_collection()

    # Supported file types
    supported = (".pdf", ".txt", ".md")
    new_count  = 0

    for filename in os.listdir(KNOWLEDGE_DIR):
        if not filename.lower().endswith(supported):
            continue

        filepath  = os.path.join(KNOWLEDGE_DIR, filename)
        file_hash = _file_hash(filepath)

        # Skip if we've already indexed this exact version
        if indexed_log.get(filename) == file_hash:
            continue

        logger.info("Indexing new/updated file: %s", filename)

        # Extract text based on file type
        if filename.lower().endswith(".pdf"):
            text = _extract_text_from_pdf(filepath)
        else:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

        if not text:
            logger.warning("No text extracted from '%s', skipping.", filename)
            continue

        # Split into chunks
        chunks = _chunk_text(text)
        if not chunks:
            continue

        # Create embeddings for all chunks
        embeddings = _embed_texts(chunks)

        # Prepare data for ChromaDB
        ids        = [f"{filename}_chunk_{i}" for i in range(len(chunks))]
        metadatas  = [{"source": filename, "chunk": i, "type": "student_note"}
                      for i in range(len(chunks))]

        # Add to collection (overwrite if already exists with same filename)
        # Delete old chunks from this file first
        try:
            collection.delete(where={"source": filename})
        except Exception:
            pass   # Ignore if nothing to delete

        collection.add(
            ids        = ids,
            embeddings = embeddings,
            documents  = chunks,
            metadatas  = metadatas
        )

        indexed_log[filename] = file_hash
        new_count += 1
        logger.info("Indexed '%s' → %d chunks", filename, len(chunks))

    _save_indexed_log(indexed_log)

    if new_count > 0:
        logger.info("Knowledge base updated: %d new/updated files indexed.", new_count)
    else:
        logger.info("Knowledge base up to date (no new files found).")

    return new_count


# ─────────────────────────────────────────────
#  RSS ARTICLE FETCHING
# ─────────────────────────────────────────────

def _summarize_article(title: str, content: str) -> str:
    """Use Claude to summarize a fetched RSS article into 3-4 sentences."""
    try:
        claude_client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        response = claude_client.messages.create(
            model      = "claude-3-5-sonnet-20241022",
            max_tokens = 300,
            system     = "You are a technical summarizer for EEE (Electrical and Electronics Engineering) content.",
            messages   = [{
                "role": "user",
                "content": f"""Summarize this EEE article in 3-4 sentences, 
                keeping the key technical concepts and any important numbers/formulas.
                
                Title: {title}
                Content: {content[:3000]}"""
            }]
        )
        return response.content[0].text
    except Exception as e:
        logger.error("Failed to summarize article '%s': %s", title, str(e))
        # Fall back to first 400 characters of content
        return content[:400] + "..."


def fetch_rss_articles():
    """
    Fetch new EEE articles from RSS feeds, summarize them with Claude,
    and store them in the ChromaDB articles collection.
    This is called weekly by the scheduler.
    """
    logger.info("Starting weekly RSS article fetch...")
    collection  = _get_articles_collection()
    total_added = 0

    for feed_url in EEE_RSS_FEEDS:
        try:
            logger.info("Fetching RSS feed: %s", feed_url)
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:5]:  # Take up to 5 articles per feed
                # Create a unique ID based on the article URL
                article_id = hashlib.md5(entry.get("link", entry.get("title", "")).encode()).hexdigest()

                # Check if we already have this article
                try:
                    existing = collection.get(ids=[article_id])
                    if existing["ids"]:
                        continue   # Already indexed, skip
                except Exception:
                    pass

                title   = entry.get("title", "Untitled")
                link    = entry.get("link", "")
                content = entry.get("summary", entry.get("content", [{}])[0].get("value", ""))

                if not content or len(content) < 100:
                    continue   # Skip articles with no useful content

                # Summarize with Claude
                logger.info("Summarizing article: '%s'", title[:60])
                summary = _summarize_article(title, content)

                full_text = f"Article: {title}\nSource: {link}\n\nSummary: {summary}"

                # Embed and store
                embedding = _embed_texts([full_text])[0]
                collection.add(
                    ids        = [article_id],
                    embeddings = [embedding],
                    documents  = [full_text],
                    metadatas  = [{
                        "title"   : title,
                        "source"  : link,
                        "feed"    : feed_url,
                        "type"    : "rss_article",
                        "fetched" : datetime.now().isoformat()
                    }]
                )
                total_added += 1
                time.sleep(1)   # Be polite to the servers

        except Exception as e:
            logger.error("Error fetching RSS feed '%s': %s", feed_url, str(e))
            continue

    logger.info("RSS fetch complete. Added %d new articles to knowledge base.", total_added)
    return total_added


# ─────────────────────────────────────────────
#  CONTEXT RETRIEVAL (for RAG)
# ─────────────────────────────────────────────

def retrieve_context(query: str, top_k: int = TOP_K_RESULTS) -> str:
    """
    Search the knowledge base for content relevant to the query.
    Searches BOTH student notes and RSS articles.

    Parameters:
      query : The topic or question to search for
      top_k : How many chunks to retrieve

    Returns: A formatted string with relevant content and sources,
             or an empty string if nothing relevant is found.
    """
    try:
        query_embedding = _embed_texts([query])[0]
        results_text    = []

        # --- Search student notes ---
        notes_collection = _get_notes_collection()
        try:
            notes_count = notes_collection.count()
            if notes_count > 0:
                notes_results = notes_collection.query(
                    query_embeddings = [query_embedding],
                    n_results        = min(top_k, notes_count),
                    include          = ["documents", "metadatas", "distances"]
                )

                for doc, meta, dist in zip(
                    notes_results["documents"][0],
                    notes_results["metadatas"][0],
                    notes_results["distances"][0]
                ):
                    # Only include results that are reasonably relevant
                    # (lower distance = more similar in ChromaDB)
                    if dist < 1.5:
                        source = meta.get("source", "your notes")
                        results_text.append(f"[From your notes: {source}]\n{doc}")
        except Exception as e:
            logger.warning("Notes search error: %s", str(e))

        # --- Search RSS articles ---
        articles_collection = _get_articles_collection()
        try:
            articles_count = articles_collection.count()
            if articles_count > 0:
                art_results = articles_collection.query(
                    query_embeddings = [query_embedding],
                    n_results        = min(2, articles_count),
                    include          = ["documents", "metadatas", "distances"]
                )

                for doc, meta, dist in zip(
                    art_results["documents"][0],
                    art_results["metadatas"][0],
                    art_results["distances"][0]
                ):
                    if dist < 1.5:
                        source = meta.get("source", "web")
                        results_text.append(f"[From web: {source}]\n{doc}")
        except Exception as e:
            logger.warning("Articles search error: %s", str(e))

        if not results_text:
            return ""

        combined = "\n\n---\n\n".join(results_text[:top_k])
        logger.info("Retrieved %d context chunks for query: '%s'", len(results_text), query[:50])
        return combined

    except Exception as e:
        logger.error("Context retrieval failed: %s", str(e))
        return ""


def get_knowledge_stats() -> dict:
    """Return statistics about the knowledge base (for /progress command)."""
    try:
        notes_count    = _get_notes_collection().count()
        articles_count = _get_articles_collection().count()

        # Count indexed files
        indexed_log  = _load_indexed_log()
        files_indexed = len(indexed_log)

        return {
            "files_indexed"   : files_indexed,
            "note_chunks"     : notes_count,
            "article_summaries": articles_count,
        }
    except Exception as e:
        logger.error("Failed to get knowledge stats: %s", str(e))
        return {"files_indexed": 0, "note_chunks": 0, "article_summaries": 0}
