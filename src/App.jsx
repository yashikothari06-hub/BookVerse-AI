import { useCallback, useEffect, useState } from "react";
import "./App.css";

const API_BASE = "http://127.0.0.1:8000";
const STATUSES = ["TBR", "Currently Reading", "Finished", "DNF"];

const suggestions = [
  { icon: "☾", title: "Something for the soul", description: "Books about life, meaning and self-discovery", prompt: "Recommend philosophical books about finding meaning in life." },
  { icon: "⌕", title: "Keep me guessing", description: "Twisty mysteries and psychological thrillers", prompt: "Recommend psychological thrillers with unpredictable twists." },
  { icon: "♡", title: "Make me feel something", description: "Emotional stories that stay with you", prompt: "Recommend emotionally powerful books that stay with you." },
  { icon: "✳", title: "Help me grow", description: "Books that change how you see the world", prompt: "Recommend books about personal growth and self-discovery." },
];

const emptyBookForm = { title: "", author: "", status: "TBR", rating: "", review: "", total_pages: "", current_page: "0" };

function App() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [activePage, setActivePage] = useState("Discover");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [books, setBooks] = useState([]);
  const [stats, setStats] = useState(null);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [libraryError, setLibraryError] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [bookForm, setBookForm] = useState(emptyBookForm);
  const [savingBook, setSavingBook] = useState(false);
  const [bookNotice, setBookNotice] = useState("");
  const [theme, setTheme] = useState(() => localStorage.getItem("bookverse-theme") || "light");
  const [showInspiration, setShowInspiration] = useState(false);
  const [reelUrl, setReelUrl] = useState("");
  const [reelCaption, setReelCaption] = useState("");
  const [reelImage, setReelImage] = useState(null);
  const [extracting, setExtracting] = useState(false);
  const [extractedBooks, setExtractedBooks] = useState([]);
  const [selectedBooks, setSelectedBooks] = useState([]);
  const [savingExtractedBooks, setSavingExtractedBooks] = useState(false);
  const [extractNotice, setExtractNotice] = useState("");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("bookverse-theme", theme);
  }, [theme]);

  const loadLibrary = useCallback(async () => {
    setLibraryLoading(true);
    setLibraryError("");
    try {
      const [booksResponse, statsResponse] = await Promise.all([
        fetch(`${API_BASE}/books`),
        fetch(`${API_BASE}/stats`),
      ]);
      if (!booksResponse.ok) throw new Error("Could not load your books. Check that the backend is running.");
      const booksData = await booksResponse.json();
      const statsData = statsResponse.ok ? await statsResponse.json() : null;
      setBooks(Array.isArray(booksData) ? booksData : booksData.books || []);
      setStats(statsData);
    } catch (error) {
      setLibraryError(error.message === "Failed to fetch" ? "Cannot connect to the backend. Start the FastAPI server on port 8000." : error.message);
    } finally {
      setLibraryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLibrary();
  }, [loadLibrary]);

  function startNewChat() {
    setMessages([]);
    setInput("");
    setErrorMessage("");
    setActivePage("Discover");
  }

  async function handleSend(messageText) {
    const text = (messageText || input).trim();
    if (!text || isLoading) return;
    setActivePage("Chat");
    setInput("");
    setErrorMessage("");
    setMessages((previous) => [...previous, { role: "user", content: text }]);
    setIsLoading(true);
    try {
      const response = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "The server could not answer.");
      setMessages((previous) => [...previous, { role: "assistant", content: data.reply || "I couldn't generate a response. Please try again." }]);
    } catch (error) {
      setErrorMessage(error.message === "Failed to fetch" ? "Cannot connect to the backend. Make sure it is running on port 8000." : error.message);
    } finally {
      setIsLoading(false);
    }
  }

  async function addBook(event) {
    event.preventDefault();
    if (!bookForm.title.trim() || !bookForm.author.trim()) {
      setBookNotice("Please enter both the book title and author.");
      return;
    }
    setSavingBook(true);
    setBookNotice("");
    const payload = {
      title: bookForm.title.trim(),
      author: bookForm.author.trim(),
      status: bookForm.status,
      rating: bookForm.rating === "" ? null : Number(bookForm.rating),
      review: bookForm.review.trim() || null,
      total_pages: bookForm.total_pages === "" ? null : Number(bookForm.total_pages),
      current_page: Number(bookForm.current_page || 0),
    };
    try {
      const response = await fetch(`${API_BASE}/books`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not save this book.");
      setBookForm(emptyBookForm);
      setShowAddForm(false);
      setBookNotice("Book added to your library!");
      await loadLibrary();
    } catch (error) {
      setBookNotice(error.message === "Failed to fetch" ? "Cannot connect to the backend. Check that it is running." : error.message);
    } finally {
      setSavingBook(false);
    }
  }

  async function updateBookStatus(book, status) {
    try {
      const response = await fetch(`${API_BASE}/books/${book.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not update the book.");
      setBookNotice(`Updated “${book.title}”.`);
      await loadLibrary();
    } catch (error) {
      setBookNotice(error.message === "Failed to fetch" ? "Cannot connect to the backend." : error.message);
    }
  }

  async function deleteBook(book) {
    if (!window.confirm(`Remove “${book.title}” from your library?`)) return;
    try {
      const response = await fetch(`${API_BASE}/books/${book.id}`, { method: "DELETE" });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Could not delete the book.");
      }
      setBookNotice(`Removed “${book.title}” from your library.`);
      await loadLibrary();
    } catch (error) {
      setBookNotice(error.message === "Failed to fetch" ? "Cannot connect to the backend." : error.message);
    }
  }

  async function identifyBooks() {
  if (!reelUrl.trim() && !reelCaption.trim() && !reelImage) {
    setExtractNotice("Please enter an Instagram URL, paste a caption, or upload a screenshot.");
    return;
  }

  setExtracting(true);
  setExtractNotice("");
  setExtractedBooks([]);
  setSelectedBooks([]);

  try {
    const form = new FormData();

    if (reelUrl.trim()) {
      form.append("reel_url", reelUrl.trim());
    }

    if (reelCaption.trim()) {
      form.append("caption", reelCaption.trim());
    }

    if (reelImage) {
      form.append("file", reelImage);
    }

    const response = await fetch(`${API_BASE}/extract-book`, {
      method: "POST",
      body: form,
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Could not identify books.");
    }

    const foundBooks = Array.isArray(data.books)
      ? data.books
      : data.book
        ? [data.book]
        : [];

    if (foundBooks.length === 0) {
      throw new Error("No books were identified. Try a clearer screenshot.");
    }

    const preparedBooks = foundBooks.map((book, index) => ({
      ...book,
      title: book.title || "",
      author: book.author || "Unknown",
      status: book.status || "TBR",
      selected: true,
      temporaryId: `${index}-${book.title}-${book.author}`,
    }));

    setExtractedBooks(preparedBooks);
    setSelectedBooks(preparedBooks.map((book) => book.temporaryId));

    setExtractNotice(
      `Identified ${preparedBooks.length} book${preparedBooks.length === 1 ? "" : "s"}. Review the details before saving.`
    );
  } catch (error) {
    setExtractNotice(
      error.message === "Failed to fetch"
        ? "Cannot connect to the backend. Make sure the FastAPI server is running on port 8000."
        : error.message
    );
  } finally {
    setExtracting(false);
  }
}

function toggleExtractedBook(temporaryId) {
  setSelectedBooks((previous) =>
    previous.includes(temporaryId)
      ? previous.filter((id) => id !== temporaryId)
      : [...previous, temporaryId]
  );
}

function updateExtractedBook(temporaryId, field, value) {
  setExtractedBooks((previous) =>
    previous.map((book) =>
      book.temporaryId === temporaryId
        ? { ...book, [field]: value }
        : book
    )
  );
}

function toggleSelectAll() {
  if (selectedBooks.length === extractedBooks.length) {
    setSelectedBooks([]);
  } else {
    setSelectedBooks(extractedBooks.map((book) => book.temporaryId));
  }
}

async function saveSelectedBooks() {
  const booksToSave = extractedBooks.filter((book) =>
    selectedBooks.includes(book.temporaryId)
  );

  if (booksToSave.length === 0) {
    setExtractNotice("Please select at least one book to save.");
    return;
  }

  const invalidBook = booksToSave.find(
    (book) => !book.title.trim() || !book.author.trim()
  );

  if (invalidBook) {
    setExtractNotice("Every selected book must have a title and author.");
    return;
  }

  setSavingExtractedBooks(true);
  setExtractNotice("");

  let savedCount = 0;
  let duplicateCount = 0;
  let failedCount = 0;

  try {
    for (const book of booksToSave) {
      try {
        const response = await fetch(`${API_BASE}/books`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            title: book.title.trim(),
            author: book.author.trim() || "Unknown",
            status: book.status || "TBR",
            source_url: reelUrl.trim() || null,
            source_platform: reelUrl.includes("instagram.com")
              ? "Instagram"
              : reelImage
                ? "Screenshot"
                : "Manual",
          }),
        });

        const data = await response.json();

        if (response.ok) {
          savedCount++;
        } else if (response.status === 409) {
          duplicateCount++;
        } else {
          failedCount++;
          console.error(`Could not save "${book.title}":`, data.detail);
        }
      } catch (error) {
        failedCount++;
        console.error(`Could not save "${book.title}":`, error);
      }
    }

    const summary = [
      `${savedCount} book${savedCount === 1 ? "" : "s"} added`,
      duplicateCount ? `${duplicateCount} duplicate${duplicateCount === 1 ? "" : "s"} skipped` : "",
      failedCount ? `${failedCount} book${failedCount === 1 ? "" : "s"} failed to save` : "",
    ].filter(Boolean).join(". ");

    setExtractNotice(`${summary}.`);

    if (savedCount > 0) {
      await loadLibrary();
    }

    if (savedCount > 0 && failedCount === 0) {
      setExtractedBooks([]);
      setSelectedBooks([]);
      setReelUrl("");
      setReelCaption("");
      setReelImage(null);
    }
  } catch (error) {
    setExtractNotice("An unexpected error occurred while saving the books.");
  } finally {
    setSavingExtractedBooks(false);
  }
}

  const finishedCount = stats?.finished ?? books.filter((book) => book.status === "Finished").length;
  const currentlyReadingCount = stats?.currently_reading ?? books.filter((book) => book.status === "Currently Reading").length;

  return (
    <div className={`app-shell theme-${theme}`}>
      <aside className="sidebar">
        <button className="brand" onClick={startNewChat} aria-label="Go to Discover">
          <span className="brand-icon">b.</span>
          <span>bookverse<span className="brand-ai"> AI</span></span>
        </button>
        <button className="theme-toggle sidebar-theme-toggle" type="button" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>{theme === "light" ? "☾ Dark mode" : "☀ Light mode"}</button>
        <div className="sidebar-label">YOUR SPACE</div>
        <nav className="navigation">
          <button className={activePage === "Discover" ? "nav-item active" : "nav-item"} onClick={startNewChat}><span>⌂</span> Discover</button>
          <button className={activePage === "Chat" ? "nav-item active" : "nav-item"} onClick={() => setActivePage("Chat")}><span>✧</span> AI Book Chat</button>
          <button className={activePage === "Reading List" ? "nav-item active" : "nav-item"} onClick={() => { setActivePage("Reading List"); loadLibrary(); }}><span>♡</span> Reading List <span className="nav-count">{books.length}</span></button>
        </nav>
        <div className="sidebar-divider" />
        <div className="sidebar-label">YOUR READING VIBE</div>
        <div className="genre-list"><span>✦ Fiction</span><span>✦ Philosophy</span><span>✦ Psychological thrillers</span><span>✦ Self-discovery</span></div>
        <div className="sidebar-note"><span className="note-mark">“</span><p>A room without books is like a body without a soul.</p><span className="note-author">— CICERO</span></div>
        <div className="sidebar-bottom"><div className="profile-avatar">B</div><div><div className="profile-name">Book Explorer</div><div className="profile-caption">Your next chapter awaits</div></div><span className="profile-menu">···</span></div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb"><span>BOOKVERSE</span><span className="breadcrumb-slash">/</span><span>{activePage.toUpperCase()}</span></div>
          <div className="topbar-right"><span className="status-dot" /><span>YOUR PERSONAL BOOK GUIDE</span><button className="theme-toggle" type="button" onClick={() => setTheme(theme === "light" ? "dark" : "light")} aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`} title={`Switch to ${theme === "light" ? "dark" : "light"} mode`}>{theme === "light" ? "☾ Dark" : "☀ Light"}</button></div>
        </header>

        {activePage === "Reading List" ? (
          <section className="library-section">
            <div className="library-heading-row">
              <div><div className="eyebrow"><span className="eyebrow-line" /> YOUR PERSONAL LIBRARY</div><h1>Your stories,<br /><span className="gradient-text">all in one place.</span></h1><p className="welcome-description">Keep track of the books you're saving, reading, and carrying with you.</p></div>
              <button className="primary-button add-book-button" onClick={() => { setShowAddForm((value) => !value); setBookNotice(""); }}><span>＋</span> Add a book</button>
            </div>
            <div className="stats-grid">
              <div className="stat-card"><span className="stat-icon">▤</span><span className="stat-number">{stats?.total_books ?? books.length}</span><span className="stat-label">BOOKS IN LIBRARY</span></div>
              <div className="stat-card"><span className="stat-icon">◷</span><span className="stat-number">{currentlyReadingCount}</span><span className="stat-label">CURRENTLY READING</span></div>
              <div className="stat-card"><span className="stat-icon">✧</span><span className="stat-number">{finishedCount}</span><span className="stat-label">BOOKS FINISHED</span></div>
            </div>

            {showAddForm && <form className="add-book-form" onSubmit={addBook}>
              <div className="form-heading"><div><span className="eyebrow">A NEW CHAPTER</span><h2>Add to your library</h2></div><button className="icon-button" type="button" onClick={() => setShowAddForm(false)} aria-label="Close form">×</button></div>
              <div className="form-grid">
                <label>Book title *<input value={bookForm.title} onChange={(e) => setBookForm({ ...bookForm, title: e.target.value })} placeholder="e.g. The Silent Patient" required /></label>
                <label>Author *<input value={bookForm.author} onChange={(e) => setBookForm({ ...bookForm, author: e.target.value })} placeholder="e.g. Alex Michaelides" required /></label>
                <label>Reading status<select value={bookForm.status} onChange={(e) => setBookForm({ ...bookForm, status: e.target.value })}>{STATUSES.map((status) => <option key={status}>{status}</option>)}</select></label>
                <label>Rating (0–5)<input type="number" min="0" max="5" step="0.5" value={bookForm.rating} onChange={(e) => setBookForm({ ...bookForm, rating: e.target.value })} placeholder="Optional" /></label>
                <label>Current page<input type="number" min="0" value={bookForm.current_page} onChange={(e) => setBookForm({ ...bookForm, current_page: e.target.value })} /></label>
                <label>Total pages<input type="number" min="1" value={bookForm.total_pages} onChange={(e) => setBookForm({ ...bookForm, total_pages: e.target.value })} placeholder="Optional" /></label>
                <label className="full-width">Your thoughts<textarea rows="3" value={bookForm.review} onChange={(e) => setBookForm({ ...bookForm, review: e.target.value })} placeholder="A note to your future self..." /></label>
              </div>
              <div className="form-actions"><button className="secondary-button" type="button" onClick={() => setShowAddForm(false)}>Cancel</button><button className="primary-button" type="submit" disabled={savingBook}>{savingBook ? "Saving..." : "Save book ↗"}</button></div>
            </form>}

            {bookNotice && <div className="notice-message" role="status">{bookNotice}</div>}
            {libraryError && <div className="error-message" role="alert"><p>{libraryError}</p><button type="button" onClick={loadLibrary}>Try again</button></div>}
            <div className="library-list-heading"><div><div className="eyebrow">THE BOOKSHELF</div><h2>Your reading list</h2></div><span className="book-total">{books.length} {books.length === 1 ? "BOOK" : "BOOKS"}</span></div>
            {libraryLoading ? <div className="library-empty"><div className="loading-spinner" /><p>Opening your bookshelf...</p></div> : books.length === 0 ? <div className="library-empty"><div className="empty-book-icon">♡</div><h3>Your bookshelf is waiting.</h3><p>Add the books you've read, want to read, or are currently enjoying.</p><button className="primary-button" onClick={() => setShowAddForm(true)}>Add your first book ↗</button></div> : <div className="book-grid">
              {books.map((book) => <article className="book-card" key={book.id}>
                <div className="book-cover"><span className="cover-ornament">✳</span><span className="cover-title">{book.title}</span><span className="cover-author">{book.author}</span><span className="cover-spine" /></div>
                <div className="book-card-content"><div className="book-status-row"><span className={`status-pill ${book.status === "Finished" ? "finished" : book.status === "Currently Reading" ? "reading" : book.status === "DNF" ? "dnf" : "tbr"}`}>{book.status || "TBR"}</span>{book.rating !== null && book.rating !== undefined && book.rating !== "" && <span className="book-rating">★ {book.rating}</span>}</div>
                  <h3>{book.title}</h3><p className="book-author">{book.author}</p>
                  {book.total_pages ? <div className="reading-progress"><div className="progress-label"><span>{book.current_page || 0} of {book.total_pages} pages</span><span>{Math.min(100, Math.round(((book.current_page || 0) / book.total_pages) * 100))}%</span></div><div className="progress-track"><span style={{ width: `${Math.min(100, Math.round(((book.current_page || 0) / book.total_pages) * 100))}%` }} /></div></div> : null}
                  {book.review && <p className="book-review">“{book.review}”</p>}
                  <div className="book-card-actions"><label className="status-select-label" htmlFor={`status-${book.id}`}>Update status<select id={`status-${book.id}`} value={book.status || "TBR"} onChange={(e) => updateBookStatus(book, e.target.value)}>{STATUSES.map((status) => <option key={status}>{status}</option>)}</select></label><button className="delete-button" onClick={() => deleteBook(book)} aria-label={`Delete ${book.title}`} title="Remove book">×</button></div>
                </div>
              </article>)}
            </div>}
          </section>
        ) : messages.length === 0 && activePage !== "Chat" ? (
          <section className="welcome-section">
            <div className="eyebrow"><span className="eyebrow-line" /> A LITTLE MAGIC BETWEEN THE COVERS</div>
            <h1>Every reader has<br />a <span className="gradient-text">next chapter.</span></h1>
            <p className="welcome-description">Tell me what you've loved, what you're feeling, or what you're searching for. Let's find the book that feels like it was written just for you.</p>
            <button className="source-toggle-button" onClick={() => { setShowInspiration((v) => !v); setExtractNotice(""); setExtractedBook(null); }}><span>▧</span> Found a book on Instagram? Add from a Reel or screenshot <span>↗</span></button>
            {showInspiration && (
  <div className="source-panel">
    <div className="source-panel-heading">
      <div>
        <div className="eyebrow">SAVE THE BOOK THAT CAUGHT YOUR EYE</div>
        <h2>From your feed to your bookshelf</h2>
      </div>

      <button
        className="icon-button"
        onClick={() => setShowInspiration(false)}
        type="button"
        aria-label="Close"
      >
        ×
      </button>
    </div>

    <label>
      Instagram Reel URL
      <input
        value={reelUrl}
        onChange={(e) => setReelUrl(e.target.value)}
        placeholder="https://www.instagram.com/reel/..."
      />
    </label>

    <label>
      Caption or transcript <span className="optional-label">(if available)</span>
      <textarea
        value={reelCaption}
        onChange={(e) => setReelCaption(e.target.value)}
        rows="3"
        placeholder="Paste the Reel caption or transcript..."
      />
    </label>

    <label className="upload-label">
      Or upload a screenshot
      <input
        type="file"
        accept="image/png,image/jpeg,image/webp"
        onChange={(e) => setReelImage(e.target.files?.[0] || null)}
      />
    </label>

    {reelImage && (
      <p className="selected-file">
        Selected screenshot: {reelImage.name}
        <button
          type="button"
          className="secondary-button"
          onClick={() => setReelImage(null)}
        >
          Remove
        </button>
      </p>
    )}

    <button
      className="primary-button"
      type="button"
      disabled={
        extracting ||
        (!reelUrl.trim() && !reelCaption.trim() && !reelImage)
      }
      onClick={identifyBooks}
    >
      {extracting ? "Identifying books..." : "Identify books ↗"}
    </button>

    {extractNotice && (
      <p className="extract-notice" role="status">
        {extractNotice}
      </p>
    )}

    {extractedBooks.length > 0 && (
      <div className="extracted-books-section">
        <div className="extracted-books-heading">
          <div>
            <span className="eyebrow">YOUR DISCOVERIES</span>
            <h3>Review your books</h3>
            <p>
              {selectedBooks.length} of {extractedBooks.length} selected
            </p>
          </div>

          <button
            type="button"
            className="secondary-button"
            onClick={toggleSelectAll}
          >
            {selectedBooks.length === extractedBooks.length
              ? "Deselect all"
              : "Select all"}
          </button>
        </div>

        <div className="extracted-books-list">
          {extractedBooks.map((book) => (
            <article
              className="extracted-book-card"
              key={book.temporaryId}
            >
              <label className="extracted-book-checkbox">
                <input
                  type="checkbox"
                  checked={selectedBooks.includes(book.temporaryId)}
                  onChange={() => toggleExtractedBook(book.temporaryId)}
                />
                <span>Select book</span>
              </label>

              <div className="extracted-book-details">
                <label>
                  Book title
                  <input
                    value={book.title}
                    onChange={(e) =>
                      updateExtractedBook(
                        book.temporaryId,
                        "title",
                        e.target.value
                      )
                    }
                  />
                </label>

                <label>
                  Author
                  <input
                    value={book.author}
                    onChange={(e) =>
                      updateExtractedBook(
                        book.temporaryId,
                        "author",
                        e.target.value
                      )
                    }
                  />
                </label>

                <label>
                  Reading status
                  <select
                    value={book.status}
                    onChange={(e) =>
                      updateExtractedBook(
                        book.temporaryId,
                        "status",
                        e.target.value
                      )
                    }
                  >
                    {STATUSES.map((status) => (
                      <option key={status} value={status}>
                        {status}
                      </option>
                    ))}
                  </select>
                </label>

                <div className="extracted-book-meta">
                  <span>
                    Confidence:{" "}
                    {Math.round((Number(book.confidence) || 0) * 100)}%
                  </span>

                  {book.evidence && (
                    <details>
                      <summary>Why this book was identified</summary>
                      <p>{book.evidence}</p>
                    </details>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>

        <button
          type="button"
          className="primary-button save-extracted-books-button"
          onClick={saveSelectedBooks}
          disabled={savingExtractedBooks || selectedBooks.length === 0}
        >
          {savingExtractedBooks
            ? "Saving books..."
            : `Add ${selectedBooks.length} selected book${selectedBooks.length === 1 ? "" : "s"} to my library ↗`}
        </button>
      </div>
    )}
  </div>
)}
            <div className="chat-hint"><span className="hint-sparkle">✳</span> NOT SURE WHERE TO START? TRY ONE OF THESE</div>
            <div className="suggestion-grid">{suggestions.map((suggestion) => <button className="suggestion-card" key={suggestion.title} onClick={() => handleSend(suggestion.prompt)}><span className="suggestion-icon">{suggestion.icon}</span><span className="suggestion-title">{suggestion.title}</span><span className="suggestion-description">{suggestion.description}</span><span className="suggestion-arrow">↗</span></button>)}</div>
            <div className="quote-strip"><span className="quote-mark">“</span><span>Some books find you exactly when you need them.</span><span className="quote-decoration">✳</span></div>
          </section>
        ) : (
          <section className="chat-section">
            {messages.length === 0 ? <div className="chat-heading"><div className="eyebrow">YOUR READING CONVERSATION</div><h2>Let's find your next read.</h2><p>Tell me a little about your taste, or choose a prompt to get started.</p><div className="chat-quick-prompts">{suggestions.slice(0, 2).map((item) => <button key={item.title} className="secondary-button" onClick={() => handleSend(item.prompt)}>{item.icon} {item.title}</button>)}</div></div> : <div className="chat-heading"><div className="eyebrow">YOUR READING CONVERSATION</div><h2>Let's find your next read.</h2></div>}
            <div className="messages">{messages.map((message, index) => <div className={`message-row ${message.role}`} key={index}><div className="message-avatar">{message.role === "assistant" ? "b." : "Y"}</div><div className="message-body"><div className="message-author">{message.role === "assistant" ? "BookVerse AI" : "You"}</div><div className="message-content">{message.content}</div></div></div>)}
              {isLoading && <div className="typing-indicator"><span /><span /><span /><span>Finding your next chapter...</span></div>}
              {errorMessage && <div className="error-message" role="alert"><p>{errorMessage}</p><button type="button" onClick={() => { const lastMessage = [...messages].reverse().find((message) => message.role === "user"); if (lastMessage) handleSend(lastMessage.content); }}>Try again</button></div>}
            </div>
          </section>
        )}

        {activePage !== "Reading List" && <footer className="composer-area"><form className="chat-composer" onSubmit={(event) => { event.preventDefault(); handleSend(); }}><span className="composer-sparkle">✳</span><input value={input} onChange={(event) => setInput(event.target.value)} placeholder="Recommend a book… or say: Add The Brothers Karamazov by Dostoevsky to my TBR" aria-label="Message BookVerse AI" /><button className="send-button" type="submit" disabled={!input.trim() || isLoading} aria-label="Send message">↗</button></form><p className="composer-disclaimer">MADE FOR THE LOVE OF READING <span>✦</span> POWERED BY AI</p></footer>}
      </main>
    </div>
  );
}

export default App;
