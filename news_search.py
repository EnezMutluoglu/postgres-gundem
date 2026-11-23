"""Full-text search over archived revisions, with a durable indexing queue."""

import json
import logging
import re
import time
from datetime import datetime, timezone
from flask import abort, render_template, request

SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(title,body,story UNINDEXED,kind UNINDEXED,tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS news_dirty(doc INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS news_phrases(phrase TEXT NOT NULL,doc INTEGER NOT NULL,PRIMARY KEY(phrase,doc));
CREATE TRIGGER IF NOT EXISTS news_official_insert AFTER INSERT ON item_history BEGIN
  INSERT OR IGNORE INTO news_dirty VALUES(NEW.rowid); END;
CREATE TRIGGER IF NOT EXISTS news_press_insert AFTER INSERT ON press_revisions BEGIN
  INSERT OR IGNORE INTO news_dirty VALUES(-NEW.id); END;
CREATE TRIGGER IF NOT EXISTS news_press_translation AFTER UPDATE OF title_tr,excerpt_tr ON press_revisions BEGIN
  INSERT OR IGNORE INTO news_dirty VALUES(-NEW.id); END;
CREATE TRIGGER IF NOT EXISTS news_body_translation AFTER UPDATE OF translation ON press_parts BEGIN
  INSERT OR IGNORE INTO news_dirty VALUES(-NEW.revision); END;
CREATE TRIGGER IF NOT EXISTS news_text_insert AFTER INSERT ON texts BEGIN
  INSERT OR IGNORE INTO news_dirty SELECT doc FROM news_phrases WHERE phrase=NEW.original; END;
CREATE TRIGGER IF NOT EXISTS news_text_update AFTER UPDATE OF translation ON texts BEGIN
  INSERT OR IGNORE INTO news_dirty SELECT doc FROM news_phrases WHERE phrase=NEW.original; END;
"""
KINDS = {
    "maintenance": "Bakım sürümü notları",
    "release": "Sürüm bülteni",
    "dev": "Geliştirme",
    "security": "Güvenlik",
    "extension": "Eklenti",
    "press": "Dış basın",
}
TABLE = str.maketrans("IİıÇĞÖŞÜçğöşü", "iiiCGOSUcgosu")


def fold(value):
    return value.translate(TABLE).lower()


# Tokenize unspaced scripts by character so a word inside a sentence is searchable.
UNSPACED = re.compile(
    r"([\u3040-\u30ff\u3400-\u9fff\uac00-\ud7a3\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff])"
)
SEARCH_TERM = re.compile(r"cve-\d{4}-\d+|\d+(?:\.\d+)+|[^\W_]+(?:_[^\W_]+)+|[^\W_]+")


def indexed(value):
    return UNSPACED.sub(r" \1 ", fold(value))


def setup(con):
    con.executescript(SCHEMA)
    con.execute(
        "INSERT OR IGNORE INTO news_dirty SELECT rowid FROM item_history h WHERE NOT EXISTS(SELECT 1 FROM news_fts WHERE rowid=h.rowid)"
    )
    con.execute(
        "INSERT OR IGNORE INTO news_dirty SELECT -id FROM press_revisions r WHERE NOT EXISTS(SELECT 1 FROM news_fts WHERE rowid=-r.id)"
    )


def document(con, doc, editorial):
    if doc < 0:
        row = con.execute(
            """SELECT r.*,a.host FROM press_revisions r JOIN press_articles a ON a.id=r.article WHERE r.id=?""",
            (-doc,),
        ).fetchone()
        if not row:
            return None
        parts = con.execute(
            "SELECT translation FROM press_parts WHERE revision=? ORDER BY pos",
            (-doc,),
        ).fetchall()
        complete = bool(parts) and all(part[0] is not None for part in parts)
        tr = list(filter(None, [row["excerpt_tr"], *(part[0] for part in parts)]))
        original = row["original"] or row["excerpt"]
        source_text = [original] if original else []
        if row["excerpt"] and not original.startswith(row["excerpt"].rstrip("…")):
            source_text.insert(0, row["excerpt"])
        return dict(
            title=row["title_tr"] or row["title"],
            original_title=row["title"],
            original=source_text,
            translated=tr,
            partial=not complete
            and row["lang"].split("-")[0] != "tr"
            and bool(original and original != row["excerpt"]),
            source=row["host"],
            kind="press",
            story=str(row["article"]),
            date=row["published"][:10]
            or datetime.fromtimestamp(row["observed"], timezone.utc).date().isoformat(),
            link=row["link"],
            lang=row["lang"],
            phrases=[],
        )
    row = con.execute("SELECT * FROM item_history WHERE rowid=?", (doc,)).fetchone()
    if not row:
        return None
    i = json.loads(row["data"])
    phrases = list(
        dict.fromkeys(
            filter(
                None,
                [
                    i["title"],
                    i.get("fixed_text"),
                    i.get("summary"),
                    *i.get("scope", []),
                    *i.get("notes", []),
                ],
            )
        )
    )
    translations = {}
    for phrase in phrases:
        tr = editorial.get(phrase)
        if not tr:
            stored = con.execute(
                "SELECT translation FROM texts WHERE original=?", (phrase,)
            ).fetchone()
            tr = stored[0] if stored else ""
        if tr:
            translations[phrase] = tr
    extra = [i["id"]] if i["kind"] == "security" else []
    extra.extend(i.get("versions", []))
    for entry in i.get("matrix", []):
        extra.append(
            " · ".join(str(v) for v in [entry.get("major"), entry.get("fixed")] if v)
        )
    if i.get("version"):
        extra.append(i["version"])
    return dict(
        title=translations.get(i["title"], i["title"]),
        original_title=i["title"],
        original=phrases[1:] + extra,
        translated=list(
            dict.fromkeys(translations[p] for p in phrases[1:] if p in translations)
        ),
        source={"pgxn": "PGXN", "commitfest": "CommitFest"}.get(
            row["source"], "PostgreSQL"
        ),
        kind=i["kind"],
        story=i["id"],
        date=i.get("date") or row["observed"][:10],
        link=i.get("url", ""),
        lang="en",
        phrases=phrases,
    )


def batch(db, editorial):
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        docs = con.execute(
            "SELECT doc FROM news_dirty ORDER BY doc LIMIT 32"
        ).fetchall()
        for (doc,) in docs:
            d = document(con, doc, editorial)
            if d:
                con.execute("DELETE FROM news_fts WHERE rowid=?", (doc,))
                con.execute(
                    "INSERT INTO news_fts(rowid,title,body,story,kind) VALUES(?,?,?,?,?)",
                    (
                        doc,
                        indexed(d["title"] + " " + d["original_title"]),
                        indexed(
                            "\n".join([*d["translated"], *d["original"], d["source"]])
                        ),
                        d["story"],
                        d["kind"],
                    ),
                )
                con.executemany(
                    "INSERT OR IGNORE INTO news_phrases VALUES(?,?)",
                    ((p, doc) for p in d["phrases"]),
                )
            con.execute("DELETE FROM news_dirty WHERE doc=?", (doc,))
        return len(docs)


def index(db, editorial):
    while True:
        try:
            if batch(db, editorial):
                continue
        except Exception:
            logging.exception("Haber arama dizini hazırlanamadı")
        time.sleep(3)


def excerpt(d, terms):
    fields = [
        *d["translated"],
        *d["original"],
        d["title"],
        d["original_title"],
        d["source"],
    ]
    match = None
    for value in fields:
        pos = [(fold(value).find(w), w) for w in terms]
        hits = [(i, w) for i, w in pos if i >= 0]
        if hits and (not match or len(hits) > match[0]):
            match = (len(hits), value, min(hits))
    if not match:
        return ((fields[0] if fields else "")[:220], "", "")
    _, value, (i, w) = match
    start = max(0, i - 75)
    end = min(len(value), i + len(w) + 140)
    return (
        ("…" if start else "") + value[start:i],
        value[i : i + len(w)],
        value[i + len(w) : end] + ("…" if end < len(value) else ""),
    )


def register(app, db, editorial):
    @app.get("/arama")
    def search():
        q = request.args.get("q", "").strip()[:180]
        terms = list(dict.fromkeys(SEARCH_TERM.findall(fold(q))))[:12]
        kind = request.args.get("alan", "")
        if kind not in KINDS:
            kind = ""
        page = max(1, min(request.args.get("sayfa", 1, type=int), 100000))
        rows = []
        total = 0
        with db() as con:
            con.execute("BEGIN")
            pending = con.execute("SELECT EXISTS(SELECT 1 FROM news_dirty)").fetchone()[
                0
            ]
            if terms:
                query = " AND ".join(
                    '"'
                    + indexed(word).strip()
                    + '"'
                    + ("" if re.search(r"[-._]", word) else "*")
                    for word in terms
                )
                sql = """WITH hits AS MATERIALIZED (SELECT rowid AS doc,story,kind,rank AS score FROM news_fts WHERE news_fts MATCH ?"""
                params = [query]
                if kind:
                    sql += " AND kind=?"
                    params.append(kind)
                sql += """), ranked AS (SELECT doc,score,row_number() OVER(PARTITION BY kind,story ORDER BY score,abs(doc) DESC) AS n FROM hits)
                  SELECT doc,count(*) OVER() FROM ranked WHERE n=1 ORDER BY score,abs(doc) DESC LIMIT 15 OFFSET ?"""
                for doc, count in con.execute(sql, [*params, (page - 1) * 15]):
                    total = count
                    d = document(con, doc, editorial)
                    rows.append(
                        dict(
                            doc=doc,
                            title=d["title"],
                            kind=KINDS[d["kind"]],
                            source=d["source"],
                            date=d["date"],
                            snippet=excerpt(d, terms),
                        )
                    )
        return render_template(
            "archive-search.html",
            q=q,
            kind=kind,
            kinds=KINDS,
            page=page,
            rows=rows,
            total=total,
            pending=pending,
            doc=None,
        )

    @app.get("/arsiv/oku/<int(signed=True):record>")
    def archived(record):
        if not -(2**63) < record < 2**63:
            abort(404)
        with db() as con:
            d = document(con, record, editorial)
        if not d:
            abort(404)
        return render_template(
            "archive-search.html",
            doc=d,
            kinds=KINDS,
            q=request.args.get("q", "")[:180],
            kind=request.args.get("alan", ""),
            page=max(1, request.args.get("sayfa", 1, type=int)),
        )
