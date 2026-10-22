BOOKVERSE UPDATE
================

Included files:
- App.jsx: existing BookVerse UI updated with a saved Light/Dark theme toggle and an Instagram Reel/screenshot book-identification panel.
- App.css: styles for the theme and source panel.
- backend_additions.py: backend endpoint code for identifying books from pasted captions/transcripts and uploaded screenshots.

FRONTEND INSTALL
1. Stop the Vite server with Ctrl+C.
2. Back up src/App.jsx and src/App.css.
3. Copy App.jsx into your project's src folder and rename it App.jsx.
4. Copy App.css into your project's src folder and rename it App.css.
5. Restart with npm run dev.
The theme button saves the preference in localStorage, so it stays selected after refresh.

BACKEND INSTALL
1. Back up backend/app.py first. Do not delete bookverse.db or your .env file.
2. Open backend/app.py.
3. Add these imports near the top:
   from google.genai import types
   Also add Form to the existing FastAPI imports (the screenshot endpoint receives multipart form fields).
   (re is only needed for the optional chat-command addition below; types is required for screenshot analysis.)
4. Copy the contents of backend_additions.py starting at @app.post("/extract-book") to the END of backend/app.py. The top comments in that file list the required imports.
5. Ensure python-multipart and google-genai are installed in the backend environment:
   pip install python-multipart google-genai
6. Restart FastAPI. Test at http://127.0.0.1:8000/docs and look for POST /extract-book.

INSTAGRAM LIMITATION
A Reel URL is saved as source metadata; Instagram may block direct automated retrieval of video/audio/captions. The reliable fallback is to paste the caption/transcript or upload a screenshot. The app asks you to verify the detected title/author before saving.

ADDING BOOKS THROUGH AI CHAT
The current /chat endpoint in your supplied app.py does not write to the database. To add a book directly from chat, insert this block inside chat(), immediately after `lowered = user_message.lower()` and before the `if client is None:` check:

    import re
    add_match = re.search(r"\b(?:add|save|put)\s+(.+?)\s+by\s+(.+?)\s+(?:to|in)\s+(?:my\s+)?(?:tbr|to[- ]read|reading list|library)\b", user_message, re.I)
    if add_match:
        title = add_match.group(1).strip().strip('“”\"\'')
        author = add_match.group(2).strip().strip('“”\"\'')
        with get_db() as db:
            try:
                cursor = db.execute("INSERT INTO books (title, author, status, updated_at) VALUES (?, ?, 'TBR', CURRENT_TIMESTAMP)", (title, author))
                row = db.execute("SELECT * FROM books WHERE id = ?", (cursor.lastrowid,)).fetchone()
            except sqlite3.IntegrityError:
                raise HTTPException(status_code=409, detail="This book is already in your library.")
        return {"reply": f'Added “{row["title"]}” by {row["author"]} to your TBR.'}

Example prompt: Add The Brothers Karamazov by Fyodor Dostoevsky to my TBR.
This command expects the title and author to be explicitly included; it does not guess missing author details.
