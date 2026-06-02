# Paper Library

A lightweight, fully local web app for researchers. Drop any arXiv PDF onto the page — the app extracts the arXiv ID from the file content, pulls metadata from the arXiv API, and saves everything to a local SQLite database. No cloud, no login, no account required.

## Features

- **Drag & drop import** — drop any arXiv PDF; metadata is fetched automatically
- **Built-in PDF viewer** — open papers inline with text selection and persistent highlights
- **Tag system** — six default colours; filter your library by tag
- **Bulk management** — select multiple papers to batch delete from your library
- **Full-text search** — searches title, authors, and extracted PDF body text; press `/` to focus
- **Hugging Face import** — search HF papers and import with one click via the associated arXiv ID

## Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.10+ · Flask |
| Database | SQLite (SQLAlchemy) |
| PDF viewer | PDF.js (Mozilla, CDN) |
| arXiv | arXiv public API — no key required |
| HF Hub | Hugging Face Hub REST API — no token required |
| Frontend | Vanilla JS + CSS custom properties |

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Then open [http://localhost:5000](http://localhost:5000).

The database and PDF files are created automatically under `data/` on first run.

## Project layout

```
paperback/
├── app.py                 # Flask entry-point; all routes and API handlers
├── requirements.txt       # Python dependencies
├── data/
│   ├── library.db         # SQLite database (auto-created)
│   └── pdfs/              # Stored PDFs keyed by arXiv ID (auto-created)
├── docs/                  # Project documentation (git-ignored)
├── templates/
│   ├── index.html         # Library page (list + sidebar + search)
│   └── viewer.html        # In-app PDF viewer with highlight support
└── static/
    ├── main.js            # Drag-drop, search, tag UI
    └── style.css          # App-wide stylesheet
```

## Data model

| Table | Key columns |
|-------|-------------|
| `papers` | arXiv ID, title, authors, year, category, source, extracted text, date added |
| `tags` | name, hex colour, display order |
| `paper_tags` | paper_id ↔ tag_id (join table) |
| `highlights` | paper_id, page, bounding-box coordinates, colour, created_at |

All state survives a full server restart — nothing lives only in process memory or browser `localStorage`.

## Notes

- Internet is only required for the initial arXiv / Hugging Face fetch. Everything else works offline.
- Renamed PDF files (e.g. `paper.pdf`) still resolve correctly because the ID is read from the file content, not the filename.
