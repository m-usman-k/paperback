import os
import re
import json
import base64
import shutil
import time
import datetime
import requests
import concurrent.futures
import xml.etree.ElementTree as ET

import fitz  # PyMuPDF

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_from_directory,
    abort,
    Response,
)
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Table,
    text,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PDF_DIR = os.path.join(DATA_DIR, "pdfs")
DB_PATH = os.path.join(DATA_DIR, "library.db")

os.makedirs(PDF_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


class Base(DeclarativeBase):
    pass


paper_tags = Table(
    "paper_tags",
    Base.metadata,
    Column("paper_id", Integer, ForeignKey("papers.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)


class Paper(Base):
    __tablename__ = "papers"

    id = Column(Integer, primary_key=True)
    arxiv_id = Column(String(32), unique=True, nullable=False)
    title = Column(Text, nullable=False)
    authors = Column(Text, nullable=False)   # JSON list
    year = Column(Integer)
    category = Column(String(64))
    source = Column(String(64), default="arXiv")
    body_text = Column(Text, default="")
    date_added = Column(DateTime, default=datetime.datetime.utcnow)

    tags = relationship("Tag", secondary=paper_tags, back_populates="papers")
    highlights = relationship(
        "Highlight", back_populates="paper", cascade="all, delete-orphan"
    )


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    colour = Column(String(7), nullable=False)
    display_order = Column(Integer, default=0)

    papers = relationship("Paper", secondary=paper_tags, back_populates="tags")


class Highlight(Base):
    __tablename__ = "highlights"

    id = Column(Integer, primary_key=True)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)
    page = Column(Integer, nullable=False)
    x1 = Column(Integer, nullable=False)
    y1 = Column(Integer, nullable=False)
    x2 = Column(Integer, nullable=False)
    y2 = Column(Integer, nullable=False)
    colour = Column(String(32), default="rgba(255,235,59,0.35)")
    group_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    paper = relationship("Paper", back_populates="highlights")


Base.metadata.create_all(engine)

# Migration for existing databases
try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE highlights ADD COLUMN group_id VARCHAR(36)"))
        conn.commit()
except Exception:
    pass  # Column already exists

# Seed default tags once
DEFAULT_TAGS = [
    ("Red", "#FDA4AF"),
    ("Orange", "#FCD34D"),
    ("Yellow", "#FDE68A"),
    ("Green", "#86EFAC"),
    ("Blue", "#93C5FD"),
    ("Purple", "#C4B5FD"),
]

with Session(engine) as _s:
    for i, (name, colour) in enumerate(DEFAULT_TAGS):
        if not _s.query(Tag).filter_by(name=name).first():
            _s.add(Tag(name=name, colour=colour, display_order=i))
    _s.commit()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ARXIV_ID_RE = re.compile(r"\b(\d{4}\.\d{4,5}(?:v\d+)?)\b")
ARXIV_API = "https://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}


def _extract_arxiv_id_from_pdf(path: str) -> str | None:
    """Read the first few pages of a PDF and return the first arXiv ID found."""
    try:
        doc = fitz.open(path)
        for page_num in range(min(3, len(doc))):
            text = doc[page_num].get_text()
            m = ARXIV_ID_RE.search(text)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def _fetch_arxiv_metadata(arxiv_id: str) -> dict | None:
    """Query the arXiv API and return a metadata dict, or None on failure.

    Retries up to 3 times with exponential backoff when the API returns 429.
    """
    clean_id = re.sub(r"v\d+$", "", arxiv_id)
    for attempt in range(3):
        try:
            resp = requests.get(
                ARXIV_API,
                params={"id_list": clean_id, "max_results": 1},
                timeout=10,
            )
        except requests.RequestException:
            return None

        if resp.status_code == 429:
            time.sleep(3 * (attempt + 1))
            continue

        if not resp.ok:
            return None

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            return None

        entry = root.find("atom:entry", NS)
        if entry is None:
            return None

        title = (entry.findtext("atom:title", "", NS) or "").strip().replace("\n", " ")
        authors = [
            a.findtext("atom:name", "", NS).strip()
            for a in entry.findall("atom:author", NS)
        ]
        published = entry.findtext("atom:published", "", NS)
        year = int(published[:4]) if published else None
        primary = entry.find(
            "{http://arxiv.org/schemas/atom}primary_category"
        )
        category = primary.get("term", "") if primary is not None else ""

        return {
            "arxiv_id": clean_id,
            "title": title,
            "authors": authors,
            "year": year,
            "category": category,
            "source": "arXiv",
        }

    return None


def _extract_body_text(path: str) -> str:
    """Extract plain text from a PDF for full-text search."""
    try:
        doc = fitz.open(path)
        parts = [doc[i].get_text() for i in range(len(doc))]
        return "\n".join(parts)[:200_000]
    except Exception:
        return ""


def _paper_to_dict(paper: Paper) -> dict:
    return {
        "id": paper.id,
        "arxiv_id": paper.arxiv_id,
        "title": paper.title,
        "authors": json.loads(paper.authors) if paper.authors else [],
        "year": paper.year,
        "category": paper.category,
        "source": paper.source,
        "date_added": paper.date_added.isoformat() if paper.date_added else None,
        "tags": [{"id": t.id, "name": t.name, "colour": t.colour} for t in paper.tags],
    }

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


# ------------------------------------------------------------------
# Papers
# ------------------------------------------------------------------

@app.route("/api/papers", methods=["GET"])
def list_papers():
    q = request.args.get("q", "").strip().lower()
    tag_id = request.args.get("tag_id", type=int)

    with Session(engine) as s:
        query = s.query(Paper)
        if tag_id:
            query = query.filter(Paper.tags.any(Tag.id == tag_id))
        papers = query.order_by(Paper.date_added.desc()).all()

        if q:
            papers = [
                p for p in papers
                if q in p.title.lower()
                or q in p.authors.lower()
                or q in (p.body_text or "").lower()
            ]

        return jsonify([_paper_to_dict(p) for p in papers])


@app.route("/api/papers/upload", methods=["POST"])
def upload_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    tmp_path = os.path.join(PDF_DIR, "_tmp_upload.pdf")
    f.save(tmp_path)

    arxiv_id = _extract_arxiv_id_from_pdf(tmp_path)
    if not arxiv_id:
        os.remove(tmp_path)
        return jsonify({"error": "No arXiv ID found in this PDF"}), 422

    meta = _fetch_arxiv_metadata(arxiv_id)
    if not meta:
        os.remove(tmp_path)
        return jsonify({"error": "Could not fetch metadata from arXiv"}), 502

    dest = os.path.join(PDF_DIR, f"{meta['arxiv_id']}.pdf")
    shutil.move(tmp_path, dest)
    body = _extract_body_text(dest)

    with Session(engine) as s:
        existing = s.query(Paper).filter_by(arxiv_id=meta["arxiv_id"]).first()
        if existing:
            return jsonify({"paper": _paper_to_dict(existing), "duplicate": True})

        paper = Paper(
            arxiv_id=meta["arxiv_id"],
            title=meta["title"],
            authors=json.dumps(meta["authors"]),
            year=meta["year"],
            category=meta["category"],
            source=meta["source"],
            body_text=body,
        )
        s.add(paper)
        s.commit()
        s.refresh(paper)
        return jsonify({"paper": _paper_to_dict(paper), "duplicate": False}), 201


@app.route("/api/papers/<int:paper_id>", methods=["DELETE"])
def delete_paper(paper_id):
    with Session(engine) as s:
        paper = s.get(Paper, paper_id)
        if not paper:
            abort(404)
        pdf_path = os.path.join(PDF_DIR, f"{paper.arxiv_id}.pdf")
        s.delete(paper)
        s.commit()
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    return "", 204

@app.route("/api/papers/batch", methods=["DELETE"])
def delete_papers_batch():
    data = request.get_json(silent=True) or {}
    paper_ids = data.get("ids", [])
    if not paper_ids:
        return "", 204
        
    with Session(engine) as s:
        papers = s.query(Paper).filter(Paper.id.in_(paper_ids)).all()
        for paper in papers:
            pdf_path = os.path.join(PDF_DIR, f"{paper.arxiv_id}.pdf")
            s.delete(paper)
            if os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                except OSError:
                    pass
        s.commit()
    return "", 204


# ------------------------------------------------------------------
# PDF serving
# ------------------------------------------------------------------

@app.route("/api/papers/<int:paper_id>/data")
def serve_pdf_data(paper_id):
    with Session(engine) as s:
        paper = s.get(Paper, paper_id)
        if not paper:
            abort(404)
        arxiv_id = paper.arxiv_id
        
    pdf_path = os.path.join(PDF_DIR, f"{arxiv_id}.pdf")
    if not os.path.exists(pdf_path):
        abort(404)
        
    with open(pdf_path, "rb") as f:
        # Prepend magic bytes so IDM doesn't recognize it as a PDF
        raw_data = b"NOT_A_PDF_" + f.read()
        
    return Response(raw_data, mimetype="application/x-paperback-data")


@app.route("/viewer/<int:paper_id>")
def viewer(paper_id):
    with Session(engine) as s:
        paper = s.get(Paper, paper_id)
        if not paper:
            abort(404)
        data = _paper_to_dict(paper)
    return render_template("viewer.html", paper=data)


# ------------------------------------------------------------------
# Tags
# ------------------------------------------------------------------

@app.route("/api/tags", methods=["GET"])
def list_tags():
    with Session(engine) as s:
        tags = s.query(Tag).order_by(Tag.display_order).all()
        return jsonify(
            [{"id": t.id, "name": t.name, "colour": t.colour} for t in tags]
        )


@app.route("/api/tags", methods=["POST"])
def create_tag():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    colour = (data.get("colour") or "#93C5FD").strip()
    if not name:
        return jsonify({"error": "Tag name required"}), 400

    with Session(engine) as s:
        if s.query(Tag).filter_by(name=name).first():
            return jsonify({"error": "Tag already exists"}), 409
        max_order = s.query(Tag).count()
        tag = Tag(name=name, colour=colour, display_order=max_order)
        s.add(tag)
        s.commit()
        s.refresh(tag)
        return jsonify({"id": tag.id, "name": tag.name, "colour": tag.colour}), 201


@app.route("/api/tags/<int:tag_id>", methods=["DELETE"])
def delete_tag(tag_id):
    with Session(engine) as s:
        tag = s.get(Tag, tag_id)
        if not tag:
            abort(404)
        s.delete(tag)
        s.commit()
    return "", 204


@app.route("/api/papers/<int:paper_id>/tags", methods=["POST"])
def add_tag_to_paper(paper_id):
    data = request.get_json(silent=True) or {}
    tag_id = data.get("tag_id")
    if not tag_id:
        return jsonify({"error": "tag_id required"}), 400

    with Session(engine) as s:
        paper = s.get(Paper, paper_id)
        tag = s.get(Tag, tag_id)
        if not paper or not tag:
            abort(404)
        if tag not in paper.tags:
            paper.tags.append(tag)
            s.commit()
        return jsonify(_paper_to_dict(paper))


@app.route("/api/papers/<int:paper_id>/tags/<int:tag_id>", methods=["DELETE"])
def remove_tag_from_paper(paper_id, tag_id):
    with Session(engine) as s:
        paper = s.get(Paper, paper_id)
        tag = s.get(Tag, tag_id)
        if not paper or not tag:
            abort(404)
        if tag in paper.tags:
            paper.tags.remove(tag)
            s.commit()
        return jsonify(_paper_to_dict(paper))


# ------------------------------------------------------------------
# Highlights
# ------------------------------------------------------------------

@app.route("/api/papers/<int:paper_id>/highlights", methods=["GET"])
def get_highlights(paper_id):
    with Session(engine) as s:
        hl = s.query(Highlight).filter_by(paper_id=paper_id).all()
        return jsonify(
            [
                {
                    "id": h.id,
                    "page": h.page,
                    "x1": h.x1,
                    "y1": h.y1,
                    "x2": h.x2,
                    "y2": h.y2,
                    "colour": h.colour,
                    "group_id": h.group_id,
                }
                for h in hl
            ]
        )


@app.route("/api/papers/<int:paper_id>/highlights", methods=["POST"])
def add_highlight(paper_id):
    data = request.get_json(silent=True) or {}
    try:
        hl = Highlight(
            paper_id=paper_id,
            page=int(data["page"]),
            x1=int(data["x1"]),
            y1=int(data["y1"]),
            x2=int(data["x2"]),
            y2=int(data["y2"]),
            colour=data.get("colour", "rgba(255,235,59,0.35)"),
        )
    except (KeyError, ValueError):
        return jsonify({"error": "Invalid highlight data"}), 400

    with Session(engine) as s:
        s.add(hl)
        s.commit()
        s.refresh(hl)
        return (
            jsonify(
                {
                    "id": hl.id,
                    "page": hl.page,
                    "x1": hl.x1,
                    "y1": hl.y1,
                    "x2": hl.x2,
                    "y2": hl.y2,
                    "colour": hl.colour,
                }
            ),
            201,
        )


@app.route("/api/papers/<int:paper_id>/highlights/batch", methods=["POST"])
def add_highlight_batch(paper_id):
    data = request.get_json(silent=True) or {}
    group_id = data.get("group_id")
    colour = data.get("colour", "rgba(255,235,59,0.35)")
    rects = data.get("rects", [])

    created_highlights = []
    with Session(engine) as s:
        for r in rects:
            try:
                hl = Highlight(
                    paper_id=paper_id,
                    page=int(r["page"]),
                    x1=int(r["x1"]),
                    y1=int(r["y1"]),
                    x2=int(r["x2"]),
                    y2=int(r["y2"]),
                    colour=colour,
                    group_id=group_id,
                )
                s.add(hl)
                created_highlights.append(hl)
            except (KeyError, ValueError):
                continue
        s.commit()
        for hl in created_highlights:
            s.refresh(hl)

        return (
            jsonify(
                [
                    {
                        "id": h.id,
                        "page": h.page,
                        "x1": h.x1,
                        "y1": h.y1,
                        "x2": h.x2,
                        "y2": h.y2,
                        "colour": h.colour,
                        "group_id": h.group_id,
                    }
                    for h in created_highlights
                ]
            ),
            201,
        )


@app.route("/api/highlights/<int:hl_id>", methods=["DELETE"])
def delete_highlight(hl_id):
    with Session(engine) as s:
        hl = s.get(Highlight, hl_id)
        if hl:
            s.delete(hl)
            s.commit()
        return "", 204


@app.route("/api/highlights/group/<string:group_id>", methods=["DELETE"])
def delete_highlight_group(group_id):
    with Session(engine) as s:
        hls = s.query(Highlight).filter_by(group_id=group_id).all()
        for hl in hls:
            s.delete(hl)
        s.commit()
        return "", 204


@app.route("/api/papers/<int:paper_id>/highlights/page/<int:page_num>", methods=["DELETE"])
def delete_highlight_page(paper_id, page_num):
    with Session(engine) as s:
        hls = s.query(Highlight).filter_by(paper_id=paper_id, page=page_num).all()
        for hl in hls:
            s.delete(hl)
        s.commit()
        return "", 204


# ------------------------------------------------------------------
# Hugging Face paper search
# ------------------------------------------------------------------

HF_PAPERS_API = "https://huggingface.co/api/papers"


@app.route("/api/hf/search")
def hf_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])

    try:
        resp = requests.get("https://huggingface.co/api/quicksearch", params={"q": q, "type": "paper", "limit": 10}, timeout=10)
        resp.raise_for_status()
        raw = resp.json().get("papers", [])
    except requests.RequestException as exc:
        return jsonify({"error": str(exc)}), 502

    def fetch_paper(item):
        try:
            p_resp = requests.get(f"https://huggingface.co/api/papers/{item['_id']}", timeout=5)
            p_resp.raise_for_status()
            return p_resp.json()
        except:
            return None

    top_items = raw[:10]
    papers_data = []
    if top_items:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            papers_data = list(executor.map(fetch_paper, top_items))

    results = []
    with Session(engine) as s:
        for p_data in papers_data:
            if not p_data:
                continue
            
            arxiv_id = p_data.get("id", "")
            title = p_data.get("title", "")
            authors_raw = p_data.get("authors", [])
            authors = (
                [a.get("name", a) if isinstance(a, dict) else a for a in authors_raw]
                if isinstance(authors_raw, list)
                else []
            )
            
            clean_id = re.sub(r"v\d+$", "", arxiv_id) if arxiv_id else ""
            in_library = s.query(Paper).filter_by(arxiv_id=clean_id).first() is not None if clean_id else False

            results.append({
                "arxiv_id": arxiv_id, 
                "title": title, 
                "authors": authors,
                "in_library": in_library
            })

    return jsonify(results)


@app.route("/api/hf/import", methods=["POST"])
def hf_import():
    """Import a paper by arXiv ID.

    The caller may pass `title`, `authors`, and `year` fields from the HF
    search result so we can save the paper even when arXiv rate-limits us.
    """
    data = request.get_json(silent=True) or {}
    arxiv_id = (data.get("arxiv_id") or "").strip()
    if not arxiv_id:
        return jsonify({"error": "arxiv_id required"}), 400

    clean_id = re.sub(r"v\d+$", "", arxiv_id)

    with Session(engine) as s:
        existing = s.query(Paper).filter_by(arxiv_id=clean_id).first()
        if existing:
            return jsonify({"paper": _paper_to_dict(existing), "duplicate": True})

    # Try arXiv API first; fall back to caller-supplied HF data on failure.
    meta = _fetch_arxiv_metadata(clean_id)
    if not meta:
        hf_title   = (data.get("title")   or "").strip()
        hf_authors = data.get("authors") or []
        hf_year    = data.get("year")
        if not hf_title:
            return jsonify({"error": "Could not fetch metadata from arXiv and no fallback data provided"}), 502
        meta = {
            "arxiv_id": clean_id,
            "title":    hf_title,
            "authors":  hf_authors if isinstance(hf_authors, list) else [],
            "year":     int(hf_year) if hf_year else None,
            "category": "",
            "source":   "arXiv",
        }

    pdf_url = f"https://arxiv.org/pdf/{clean_id}.pdf"
    dest = os.path.join(PDF_DIR, f"{clean_id}.pdf")
    try:
        r = requests.get(pdf_url, timeout=30, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(65536):
                fh.write(chunk)
    except requests.RequestException as exc:
        return jsonify({"error": f"PDF download failed: {exc}"}), 502

    body = _extract_body_text(dest)

    with Session(engine) as s:
        paper = Paper(
            arxiv_id=clean_id,
            title=meta["title"],
            authors=json.dumps(meta["authors"]),
            year=meta["year"],
            category=meta["category"],
            source=meta["source"],
            body_text=body,
        )
        s.add(paper)
        s.commit()
        s.refresh(paper)
        return jsonify({"paper": _paper_to_dict(paper), "duplicate": False}), 201


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=5000)
