import os
import csv
import io
import json
import time
import sqlite3
import requests
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# ==================================================
# 1. ENVIRONMENT CONFIGURATION
# ==================================================

BASE_DIR = Path(__file__).resolve().parent
DATABASE_FILE = BASE_DIR / "bookverse.db"

load_dotenv(BASE_DIR / ".env")

API_KEY = os.getenv("GEMINI_API_KEY")
SAVEAPI_KEY = os.getenv("SAVEAPI_KEY")
SAVEAPI_URL = "https://api.saveapi.org/v1/download"

client = genai.Client(api_key=API_KEY) if API_KEY else None
GEMINI_MODEL = "gemini-3.8-flash"

MAX_IMAGE_SIZE = 8 * 1024 * 1024
MAX_VIDEO_SIZE = 20 * 1024 * 1024

# Small in-memory cache for URL-only extraction requests.
# This is cleared when the backend restarts; it does not modify SQLite.
EXTRACTION_CACHE = {}
EXTRACTION_CACHE_MAX = 100

# ==================================================
# 2. FASTAPI APPLICATION
# ==================================================

app = FastAPI(
    title="BookVerse API",
    description="AI-powered book recommendations and reading tracker",
    version="2.2.0",
)

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

# ==================================================
# 3. DATABASE CONFIGURATION
# ==================================================

VALID_STATUSES = {"TBR", "Currently Reading", "Finished", "DNF"}


@contextmanager
def get_db():
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    # CREATE TABLE IF NOT EXISTS leaves existing database rows untouched.
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT 'Unknown',
                status TEXT NOT NULL DEFAULT 'TBR',
                rating REAL,
                review TEXT NOT NULL DEFAULT '',
                current_page INTEGER NOT NULL DEFAULT 0,
                total_pages INTEGER,
                date_started TEXT,
                date_finished TEXT,
                source_url TEXT,
                source_platform TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(title, author)
            )
        """)


@app.on_event("startup")
async def startup_event():
    initialize_database()


# ==================================================
# 4. REQUEST MODELS
# ==================================================

class ChatRequest(BaseModel):
    message: str


class BookCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    author: str = Field(default="Unknown", max_length=300)
    status: str = "TBR"
    rating: float | None = Field(default=None, ge=0, le=5)
    review: str = ""
    current_page: int = Field(default=0, ge=0)
    total_pages: int | None = Field(default=None, gt=0)
    date_started: str | None = None
    date_finished: str | None = None
    source_url: str | None = None
    source_platform: str | None = None


class BookUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    author: str | None = Field(default=None, max_length=300)
    status: str | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    review: str | None = None
    current_page: int | None = Field(default=None, ge=0)
    total_pages: int | None = Field(default=None, gt=0)
    date_started: str | None = None
    date_finished: str | None = None
    source_url: str | None = None
    source_platform: str | None = None


# ==================================================
# 5. SHARED ERROR HANDLING
# ==================================================

def gemini_error_status(exc):
    error_text = str(exc).lower()
    if "429" in error_text or "resource_exhausted" in error_text:
        return 429
    if any(term in error_text for term in ("503", "unavailable", "overloaded")):
        return 503
    if "timeout" in error_text or "timed out" in error_text:
        return 504
    return 502


def gemini_error_detail(status_code):
    if status_code == 429:
        return (
            "Gemini's quota is exhausted or rate-limited. "
            "Wait for the reset shown in Google AI Studio before trying again. "
            "BookVerse will not retry a quota error automatically."
        )
    if status_code == 503:
        return "Gemini is temporarily unavailable. Please try again later."
    if status_code == 504:
        return "Gemini took too long to respond. Please try again later."
    return "Gemini could not process this request. Please try again later."


def validate_instagram_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {
        "instagram.com", "www.instagram.com", "m.instagram.com"
    }:
        raise HTTPException(
            status_code=400,
            detail="Please enter a valid Instagram Reel URL.",
        )
    return url


# ==================================================
# 6. HOME AND HEALTH ENDPOINTS
# ==================================================

@app.get("/")
async def home():
    return {
        "message": "BookVerse AI backend is running!",
        "features": [
            "AI book recommendations",
            "Personal reading library",
            "Reading progress",
            "Ratings and reviews",
            "CSV import",
            "Reading statistics",
            "Multiple-book screenshot and Reel extraction",
        ],
    }


@app.get("/health")
async def health_check():
    return {
        "status": "running",
        "api_key_configured": bool(API_KEY),
        "saveapi_key_configured": bool(SAVEAPI_KEY),
        "database": "SQLite",
    }


# ==================================================
# 7. ADD A BOOK
# ==================================================

@app.post("/books")
async def add_book(book: BookCreate):
    title = book.title.strip()
    author = book.author.strip() or "Unknown"

    if not title:
        raise HTTPException(status_code=400, detail="Book title cannot be empty.")
    if book.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Status must be one of {sorted(VALID_STATUSES)}",
        )
    if book.total_pages and book.current_page > book.total_pages:
        raise HTTPException(
            status_code=400,
            detail="Current page cannot exceed total pages.",
        )

    try:
        with get_db() as db:
            cursor = db.execute("""
                INSERT INTO books (
                    title, author, status, rating, review,
                    current_page, total_pages, date_started,
                    date_finished, source_url, source_platform,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                title, author, book.status, book.rating, book.review,
                book.current_page, book.total_pages, book.date_started,
                book.date_finished, book.source_url, book.source_platform,
            ))
            row = db.execute(
                "SELECT * FROM books WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return {"message": "Book added successfully!", "book": dict(row)}
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="This book is already in your library.",
        )


# ==================================================
# 8. GET BOOKS
# ==================================================

@app.get("/books")
async def get_books(status: str | None = None):
    with get_db() as db:
        if status:
            if status not in VALID_STATUSES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Status must be one of {sorted(VALID_STATUSES)}",
                )
            rows = db.execute("""
                SELECT * FROM books WHERE status = ? ORDER BY created_at DESC
            """, (status,)).fetchall()
        else:
            rows = db.execute("""
                SELECT * FROM books ORDER BY created_at DESC
            """).fetchall()
    return {"books": [dict(row) for row in rows]}


# ==================================================
# 9. UPDATE A BOOK
# ==================================================

@app.patch("/books/{book_id}")
async def update_book(book_id: int, updates: BookUpdate):
    changes = updates.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No updates were provided.")

    if "status" in changes and changes["status"] not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Status must be one of {sorted(VALID_STATUSES)}",
        )
    if "title" in changes and changes["title"] is not None:
        changes["title"] = changes["title"].strip()
        if not changes["title"]:
            raise HTTPException(status_code=400, detail="Book title cannot be empty.")
    if "author" in changes and changes["author"] is not None:
        changes["author"] = changes["author"].strip() or "Unknown"

    with get_db() as db:
        existing = db.execute(
            "SELECT * FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail="Book not found.")

        updated = dict(existing)
        updated.update(changes)
        if (
            updated["total_pages"] is not None
            and updated["current_page"] > updated["total_pages"]
        ):
            raise HTTPException(
                status_code=400,
                detail="Current page cannot exceed total pages.",
            )

        columns = list(changes.keys())
        assignments = ", ".join(f"{column} = ?" for column in columns)
        values = [changes[column] for column in columns] + [book_id]
        db.execute(
            f"UPDATE books SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        row = db.execute(
            "SELECT * FROM books WHERE id = ?", (book_id,)
        ).fetchone()

    return {"message": "Book updated successfully!", "book": dict(row)}


# ==================================================
# 10. DELETE A BOOK
# ==================================================

@app.delete("/books/{book_id}")
async def delete_book(book_id: int):
    with get_db() as db:
        cursor = db.execute("DELETE FROM books WHERE id = ?", (book_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Book not found.")
    return {"message": "Book removed from your library."}


# ==================================================
# 11. READING STATISTICS
# ==================================================

@app.get("/stats")
async def reading_statistics():
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        status_rows = db.execute("""
            SELECT status, COUNT(*) AS count FROM books GROUP BY status
        """).fetchall()
        average_rating = db.execute("""
            SELECT ROUND(AVG(rating), 2) FROM books WHERE rating IS NOT NULL
        """).fetchone()[0]
        finished_this_year = db.execute("""
            SELECT COUNT(*) FROM books
            WHERE status = 'Finished' AND date_finished LIKE ?
        """, (f"{time.strftime('%Y')}%",)).fetchone()[0]

    counts = {status: 0 for status in VALID_STATUSES}
    for row in status_rows:
        counts[row["status"]] = row["count"]

    return {
        "total_books": total,
        "finished": counts["Finished"],
        "currently_reading": counts["Currently Reading"],
        "tbr": counts["TBR"],
        "dnf": counts["DNF"],
        "finished_this_year": finished_this_year,
        "average_rating": average_rating,
    }


# ==================================================
# 12. IMPORT READING HISTORY FROM CSV
# ==================================================

@app.post("/books/import-csv")
async def import_books_csv(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file.")

    content = await file.read()
    try:
        csv_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="The CSV file must use UTF-8 encoding.",
        )

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise HTTPException(
            status_code=400,
            detail="The CSV file is empty or missing column headers.",
        )

    imported = 0
    skipped = 0
    errors = []

    with get_db() as db:
        for line_number, row in enumerate(reader, start=2):
            normalized = {
                str(key).strip().lower(): (value or "").strip()
                for key, value in row.items() if key is not None
            }
            title = (
                normalized.get("title")
                or normalized.get("book title")
                or normalized.get("name")
            )
            if not title:
                skipped += 1
                errors.append(f"Row {line_number}: missing book title.")
                continue

            author = normalized.get("author") or normalized.get("authors") or "Unknown"
            raw_status = (
                normalized.get("status")
                or normalized.get("reading status")
                or "TBR"
            )
            aliases = {
                "read": "Finished",
                "already read": "Finished",
                "completed": "Finished",
                "reading": "Currently Reading",
                "currently reading": "Currently Reading",
                "to-read": "TBR",
                "to read": "TBR",
                "want to read": "TBR",
                "did not finish": "DNF",
                "dnf": "DNF",
            }
            status = aliases.get(raw_status.lower(), raw_status)
            if status not in VALID_STATUSES:
                skipped += 1
                errors.append(f"Row {line_number}: invalid reading status.")
                continue

            raw_rating = normalized.get("rating") or normalized.get("my rating") or ""
            try:
                rating = float(raw_rating) if raw_rating else None
                if rating is not None and not 0 <= rating <= 5:
                    raise ValueError
            except ValueError:
                skipped += 1
                errors.append(f"Row {line_number}: rating must be between 0 and 5.")
                continue

            try:
                db.execute("""
                    INSERT INTO books (
                        title, author, status, rating, review,
                        date_started, date_finished, source_url,
                        source_platform, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    title, author, status, rating, normalized.get("review", ""),
                    normalized.get("date started") or None,
                    normalized.get("date finished") or None,
                    normalized.get("source url") or None,
                    normalized.get("source platform") or None,
                ))
                imported += 1
            except sqlite3.IntegrityError:
                skipped += 1
                errors.append(f"Row {line_number}: {title} by {author} already exists.")

    return {
        "message": "CSV import completed.",
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:20],
    }


# ==================================================
# 13. AI CHATBOT WITH READING HISTORY CONTEXT + OFFLINE FALLBACK
# ==================================================

def recommend_from_local_library(user_message: str) -> str:
    """Recommend only books already stored in SQLite; never invent titles."""
    with get_db() as db:
        rows = db.execute(
            """
            SELECT title, author, status, rating, review
            FROM books
            ORDER BY COALESCE(rating, 0) DESC, updated_at DESC, title ASC
            """
        ).fetchall()

    if not rows:
        return (
            "Gemini is temporarily out of quota, so BookVerse switched to its "
            "offline recommendation mode. I don't have any books in your local "
            "database to recommend yet. Add books to your library or import your "
            "book CSV, then ask me again. Your existing data has not been changed."
        )

    # Simple keyword scoring: match the user's prompt against the available
    # title, author, review, status, and common genre/mood keywords.
    message_words = {
        word for word in user_message.lower().replace("'", " ").split()
        if len(word) >= 3
    }
    stop_words = {
        "the", "and", "for", "with", "that", "this", "from", "book",
        "books", "recommend", "recommendation", "please", "want", "like",
        "some", "what", "about", "into", "who", "are", "you", "can",
    }
    message_words -= stop_words
    genre_terms = {
        "mystery": {"mystery", "detective", "crime", "thriller", "suspense"},
        "thriller": {"thriller", "suspense", "crime", "mystery", "psychological"},
        "romance": {"romance", "romantic", "love", "relationship"},
        "fantasy": {"fantasy", "magic", "magical", "dragon", "epic"},
        "science fiction": {"science", "fiction", "sci-fi", "space", "dystopian"},
        "horror": {"horror", "scary", "dark", "supernatural"},
        "self-help": {"self-help", "self", "help", "habits", "productivity", "growth"},
        "psychology": {"psychology", "psychological", "mind", "human", "behaviour"},
    }
    expanded_terms = set(message_words)
    for terms in genre_terms.values():
        if message_words & terms:
            expanded_terms.update(terms)

    scored = []
    for row in rows:
        title = row["title"] or ""
        author = row["author"] or "Unknown"
        review = row["review"] or ""
        searchable = f"{title} {author} {review}".lower()
        words = {word for word in searchable.replace("-", " ").split() if len(word) >= 3}
        score = len(expanded_terms & words)
        if row["rating"] is not None:
            score += max(0, float(row["rating"]) - 3) * 0.25
        if row["status"] == "TBR":
            score += 0.5
        scored.append((score, row))

    scored.sort(key=lambda item: (item[0], float(item[1]["rating"] or 0)), reverse=True)
    # Return up to five books, prioritising keyword matches; if none match,
    # use the best-rated / most recently updated books already in the library.
    matching = [item for item in scored if item[0] > 0]
    selected = (matching if matching else scored)[:5]
    lines = []
    for index, (_, row) in enumerate(selected, start=1):
        rating = f" · Your rating: {row['rating']}/5" if row["rating"] is not None else ""
        status = row["status"] or "TBR"
        reason = (
            "matches keywords in your request or book notes"
            if message_words and any(
                term in f"{row['title']} {row['author']} {row['review']}".lower()
                for term in message_words
            ) else "selected from your existing library"
        )
        lines.append(
            f"{index}. **{row['title']}** by {row['author']} "
            f"({status}{rating}) — {reason}."
        )

    return (
        "Gemini's quota is currently exhausted, so I'm using BookVerse's "
        "local fallback. These suggestions come only from books already in "
        "your database; they are not newly generated AI recommendations.\n\n"
        + "\n".join(lines)
        + "\n\nFor recommendations from a larger catalogue, import your book dataset CSV."
    )


@app.post("/chat")
async def chat(request: ChatRequest):
    user_message = request.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="Please enter a message.")

    lowered = user_message.lower()

    # These requests are answered from SQLite and use zero Gemini requests.
    if any(phrase in lowered for phrase in [
        "show my tbr",
        "show my reading list",
        "what is in my tbr",
        "show books i have read",
        "show my reading history",
        "show my currently reading",
    ]):
        if "tbr" in lowered:
            status = "TBR"
        elif "currently reading" in lowered:
            status = "Currently Reading"
        elif "books i have read" in lowered or "reading history" in lowered:
            status = "Finished"
        else:
            status = None

        with get_db() as db:
            if status:
                rows = db.execute("""
                    SELECT title, author, status FROM books
                    WHERE status = ? ORDER BY created_at DESC
                """, (status,)).fetchall()
            else:
                rows = db.execute("""
                    SELECT title, author, status FROM books ORDER BY created_at DESC
                """).fetchall()

        if not rows:
            return {
                "reply": "Your library is empty for that category. "
                         "Add a book through the library feature first."
            }

        lines = [
            f"• {row['title']} — {row['author']} ({row['status']})"
            for row in rows
        ]
        return {"reply": "Here is your reading library:\n\n" + "\n".join(lines)}

    if client is None:
        raise HTTPException(
            status_code=500,
            detail="Gemini API key is missing. Check your backend .env file.",
        )

    with get_db() as db:
        rows = db.execute("""
            SELECT title, author, status, rating, review
            FROM books ORDER BY created_at DESC
        """).fetchall()

    library_context = "\n".join(
        f"- {row['title']} by {row['author']}; status: {row['status']}; "
        f"rating: {row['rating']}; review: {row['review']}"
        for row in rows
    ) or "The user's library is currently empty."

    prompt = f"""
You are BookVerse, a friendly AI book recommendation assistant.

PERSONAL LIBRARY:
{library_context}

Recommend books based on the user's interests, reading history,
favourite genres, mood, favourite authors, and preferred writing style.
Explain why each recommendation suits the user.
Do not invent details about the user's reading history.
Do not claim a book was saved, removed, or updated unless a database
operation actually happened.
If the user asks to save a book, explain that it can currently be saved
using the library feature.

User message:
{user_message}
"""

    # Exactly one Gemini request. Do not retry quota errors.
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        reply = response.text if response else None
        if not reply:
            raise HTTPException(
                status_code=502,
                detail="Gemini returned an empty response.",
            )
        return {"reply": reply}
    except HTTPException:
        raise
    except Exception as exc:
        print(f"GEMINI CHAT ERROR: {type(exc).__name__}: {exc}")
        error_text = str(exc).lower()
        if "429" in error_text or "resource_exhausted" in error_text:
            # No second Gemini request: serve a local-only fallback instead.
            return {
                "reply": recommend_from_local_library(user_message),
                "fallback": True,
                "source": "local_database",
            }
        if any(term in error_text for term in ("503", "unavailable", "overloaded")):
            raise HTTPException(
                status_code=503,
                detail="Gemini is temporarily unavailable. Please try later.",
            )
        if "timeout" in error_text or "timed out" in error_text:
            raise HTTPException(
                status_code=504,
                detail="Gemini took too long to respond. Please try later.",
            )
        raise HTTPException(
            status_code=502,
            detail="BookVerse could not get a response from Gemini.",
        )


# ==================================================
# 14. EXTRACT MULTIPLE BOOKS FROM REELS, CAPTIONS, OR IMAGES
# ==================================================

@app.post("/extract-book")
async def extract_book(
    reel_url: str = Form(default=""),
    caption: str = Form(default=""),
    file: UploadFile | None = File(default=None),
):
    """Identify books from an Instagram Reel, caption, or screenshot."""

    reel_url = reel_url.strip()
    caption = caption.strip()
    image_bytes = None
    mime_type = None
    video_bytes = None
    video_note = ""

    if not reel_url and not caption and file is None:
        raise HTTPException(
            status_code=400,
            detail="Add an Instagram Reel URL, caption, or screenshot.",
        )

    # Validate screenshot if supplied.
    if file is not None and file.filename:
        mime_type = (file.content_type or "").lower()
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise HTTPException(
                status_code=400,
                detail="Upload a JPG, PNG, or WEBP screenshot.",
            )
        image_bytes = await file.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="The uploaded screenshot is empty.")
        if len(image_bytes) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=413, detail="Screenshot must be smaller than 8 MB.")

    normalized_url = validate_instagram_url(reel_url) if reel_url else ""

    # Cache only URL-only requests so changed captions/screenshots are never hidden.
    cache_key = ""
    if normalized_url and not caption and image_bytes is None:
        cache_key = "reel:" + normalized_url.split("?")[0].rstrip("/")
        if cache_key in EXTRACTION_CACHE:
            cached = EXTRACTION_CACHE[cache_key]
            return {
                **cached,
                "note": "Returned cached results; no Gemini request was made.",
            }

    if client is None:
        raise HTTPException(
            status_code=500,
            detail="Gemini API key is missing. Check your backend .env file.",
        )

    # Retrieve video using SaveAPI.
    if normalized_url:
        if not SAVEAPI_KEY:
            if not caption and image_bytes is None:
                raise HTTPException(
                    status_code=500,
                    detail="SaveAPI key is missing. Add SAVEAPI_KEY to backend/.env.",
                )
            video_note = "SaveAPI is not configured; used the supplied caption or screenshot."
        else:
            try:
                api_response = requests.get(
                    SAVEAPI_URL,
                    headers={"Authorization": f"Bearer {SAVEAPI_KEY}"},
                    params={"url": normalized_url},
                    timeout=45,
                )
                api_response.raise_for_status()
                api_data = api_response.json()
                if not api_data.get("success"):
                    raise ValueError("SaveAPI could not retrieve this Reel.")

                media_items = api_data.get("medias", [])
                video_item = next(
                    (
                        item for item in media_items
                        if item.get("type") == "video" and item.get("url")
                    ),
                    None,
                )
                if video_item is None:
                    raise ValueError("SaveAPI did not return a downloadable video.")

                media_url = video_item["url"]
                parsed_media_url = urlparse(media_url)
                if parsed_media_url.scheme != "https" or not parsed_media_url.hostname:
                    raise ValueError("SaveAPI returned an invalid media URL.")

                with requests.get(
                    media_url,
                    stream=True,
                    timeout=(15, 60),
                    allow_redirects=True,
                ) as video_response:
                    video_response.raise_for_status()
                    content_type = (
                        video_response.headers.get("Content-Type", "")
                        .split(";")[0].strip().lower()
                    )
                    if not (
                        content_type.startswith("video/")
                        or content_type == "application/octet-stream"
                    ):
                        raise ValueError("The media URL did not return a video file.")

                    content_length = video_response.headers.get("Content-Length")
                    if content_length and int(content_length) > MAX_VIDEO_SIZE:
                        raise ValueError("The Reel video exceeds the 20 MB download limit.")

                    chunks = []
                    total_size = 0
                    for chunk in video_response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        total_size += len(chunk)
                        if total_size > MAX_VIDEO_SIZE:
                            raise ValueError("The Reel video exceeds the 20 MB download limit.")
                        chunks.append(chunk)
                    video_bytes = b"".join(chunks)
                    if not video_bytes:
                        raise ValueError("The downloaded video is empty.")

            except Exception as exc:
                print(f"SAVEAPI REEL EXTRACTION ERROR: {type(exc).__name__}: {exc}")
                if not caption and image_bytes is None:
                    raise HTTPException(
                        status_code=502,
                        detail=(
                            "BookVerse could not retrieve this Reel. Check that it is "
                            "publicly accessible, or provide its caption or a screenshot."
                        ),
                    )
                video_note = (
                    "The Reel video could not be retrieved; used the supplied caption or screenshot."
                )

    prompt = f"""
You are BookVerse AI, an accurate book identification assistant.

Identify every distinct book that can be reliably identified from the
provided Reel video, screenshot, caption, or combination of these inputs.

Instructions:
1. Examine visible book covers, spines, lists, and readable on-screen text.
2. Identify every distinct book that can be read reliably.
3. Use the caption to identify books mentioned in text.
4. Never invent titles or authors.
5. If the title is readable but the author is unclear, use "Unknown".
6. Include a confidence score between 0 and 1.
7. Briefly explain the evidence for each identification.
8. Preserve the approximate order in which books appear.
9. Do not return duplicate books.
10. Return an empty books array if no books can be identified.

Return ONLY valid JSON in this structure:
{{
  "books": [
    {{
      "title": "Book title",
      "author": "Author name",
      "confidence": 0.95,
      "evidence": "The title is visible on screen."
    }}
  ]
}}

Instagram Reel URL: {normalized_url or "Not provided"}
Caption or transcript: {caption or "Not provided"}
"""

    contents = [prompt]
    if image_bytes:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
    if video_bytes:
        contents.append(types.Part.from_bytes(data=video_bytes, mime_type="video/mp4"))

    # Exactly one Gemini request; a 429 is returned immediately.
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
        )
        raw = response.text.strip() if response and response.text else ""
    except Exception as exc:
        print(f"BOOK EXTRACTION ERROR: {type(exc).__name__}: {exc}")
        error_text = str(exc).lower()
        if "429" in error_text or "resource_exhausted" in error_text:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Gemini's quota is exhausted or rate-limited. "
                    "Wait for the quota reset shown in Google AI Studio. "
                    "BookVerse did not retry the request."
                ),
            )
        if any(term in error_text for term in ("503", "unavailable", "overloaded")):
            raise HTTPException(
                status_code=503,
                detail="Gemini is temporarily unavailable. Please try again later.",
            )
        if "timeout" in error_text or "timed out" in error_text:
            raise HTTPException(
                status_code=504,
                detail="Gemini took too long to respond. Please try again later.",
            )
        raise HTTPException(
            status_code=502,
            detail="Gemini could not process the input. Try a caption or screenshot.",
        )

    if not raw:
        raise HTTPException(status_code=502, detail="Gemini returned an empty response.")

    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502,
            detail="Gemini returned invalid JSON. Please try again.",
        )

    if not isinstance(parsed, dict) or not isinstance(parsed.get("books", []), list):
        raise HTTPException(status_code=502, detail="Gemini returned an invalid book list.")

    books = []
    seen_books = set()
    for item in parsed.get("books", []):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        author = str(item.get("author") or "Unknown").strip() or "Unknown"
        if not title:
            continue

        identity = (title.casefold(), author.casefold())
        if identity in seen_books:
            continue
        seen_books.add(identity)

        try:
            confidence = float(item.get("confidence", 0))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.0

        books.append({
            "title": title,
            "author": author,
            "status": "TBR",
            "confidence": confidence,
            "evidence": str(item.get("evidence") or ""),
        })

    if not books:
        raise HTTPException(
            status_code=422,
            detail=(
                "No book titles could be identified reliably. "
                "Try a clearer screenshot, caption, or another Reel."
            ),
        )

    result = {
        "books": books,
        "count": len(books),
        "note": (
            "Review the identified titles before saving. "
            "Books have not been added to your library automatically. "
            + video_note
        ).strip(),
    }

    if cache_key:
        if len(EXTRACTION_CACHE) >= EXTRACTION_CACHE_MAX:
            EXTRACTION_CACHE.pop(next(iter(EXTRACTION_CACHE)))
        EXTRACTION_CACHE[cache_key] = result

    return result
