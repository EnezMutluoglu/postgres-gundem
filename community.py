"""Weekly publisher discovery and append-only PostgreSQL community coverage."""

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree as ET

import translation_jobs as tasks

from bs4 import BeautifulSoup
from flask import jsonify, request
from langdetect import LangDetectException, detect_langs

PLANET = "https://planet.postgresql.org/"
DIRECTORY = PLANET + "feeds.html"
INTL = "https://www.postgresql.org/community/international/"
SEARCH = "https://news.google.com/rss/search"
# Publication paths and article bodies on the projects' own sites.
PROJECTS = {
    "https://postgis.net/sitemap.xml": (
        "PostGIS",
        r"/\d{4}/\d{2}/[^/]+/",
        "section.gdoc-markdown",
    ),
    "https://www.citusdata.com/sitemap.xml": (
        "Citus",
        r"/blog/\d{4}/\d{2}/\d{2}/[^/]+/",
        "main.blog-article-content",
    ),
    "https://cloudnative-pg.io/sitemap.xml": (
        "CloudNativePG",
        r"/(?:blog|releases)/[^/]+/",
        "div.mx-auto.my-10:has(> p)",
    ),
}
# lang, publisher, feed, publisher domain (the French feed aggregates several publishers).
FEEDS = (
    (
        "en",
        "Crunchy Data",
        "https://www.crunchydata.com/blog/rss.xml",
        "crunchydata.com",
    ),
    (
        "en",
        "CYBERTEC",
        "https://www.cybertec-postgresql.com/en/feed/",
        "cybertec-postgresql.com",
    ),
    (
        "en",
        "CloudNativePG",
        "https://cloudnative-pg.io/blog/index.xml",
        "cloudnative-pg.io",
    ),
    (
        "en",
        "PostgreSQL Europe",
        "https://www.postgresql.eu/feeds/news/",
        "postgresql.eu",
    ),
    ("fr", "Dalibo", "https://blog.dalibo.com/feed.xml", "blog.dalibo.com"),
    (
        "fr",
        "Planète PostgreSQL",
        "https://postgresqlfr.github.io/planete/feed.atom",
        "",
    ),
    ("ja", "JPUG", "https://www.postgresql.jp/rss.xml", "postgresql.jp"),
    (
        "tr",
        "PostgreSQL Türkiye",
        "https://postgresql.org.tr/feed/",
        "postgresql.org.tr",
    ),
    ("it", "ITPUG", "https://www.itpug.org/feed.xml", "itpug.org"),
)
MARKETS = {
    "en": "US",
    "de": "DE",
    "fr": "FR",
    "tr": "TR",
    "it": "IT",
    "es": "ES",
    "pt": "BR",
    "ja": "JP",
    "ko": "KR",
    "zh-CN": "CN",
    "ru": "RU",
    "pl": "PL",
    "nl": "NL",
    "cs": "CZ",
    "uk": "UA",
    "id": "ID",
    "hi": "IN",
    "ar": "EG",
}
NETWORK = {
    urlsplit(s).netloc
    for s in [PLANET, DIRECTORY, INTL, SEARCH, *PROJECTS, *[f[2] for f in FEEDS]]
}
WEEK = 7 * 86400
SHARED_HOSTS = {
    "github.com",
    "github.io",
    "medium.com",
    "dev.to",
    "youtube.com",
    "youtu.be",
    "linkedin.com",
    "substack.com",
    "blogspot.com",
    "wordpress.com",
    "feeds.feedburner.com",
    "hashnode.com",
    "hackernoon.com",
    "qiita.com",
    "zenn.dev",
    "reddit.com",
    "gitlab.com",
    "notion.site",
    "x.com",
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS press_sources(host TEXT PRIMARY KEY, name TEXT NOT NULL, evidence TEXT NOT NULL, approved INTEGER NOT NULL, seen INTEGER NOT NULL, verified INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS press_checks(task TEXT PRIMARY KEY, due INTEGER NOT NULL, checked INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS press_project_pages(url TEXT PRIMARY KEY, origin TEXT NOT NULL, due INTEGER NOT NULL, checked INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS press_articles(id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL, host TEXT NOT NULL, title_key TEXT NOT NULL, current_revision INTEGER);
CREATE INDEX IF NOT EXISTS press_title ON press_articles(host,title_key);
CREATE TABLE IF NOT EXISTS press_revisions(id INTEGER PRIMARY KEY, article INTEGER NOT NULL, signature TEXT NOT NULL, lang TEXT NOT NULL, title TEXT NOT NULL, excerpt TEXT NOT NULL, original TEXT NOT NULL, published TEXT NOT NULL, observed INTEGER NOT NULL, origin TEXT NOT NULL, rank INTEGER NOT NULL, link TEXT NOT NULL, title_tr TEXT, excerpt_tr TEXT, retry INTEGER NOT NULL DEFAULT 0, error TEXT, UNIQUE(article, signature));
CREATE INDEX IF NOT EXISTS press_queue ON press_revisions(retry,id) WHERE title_tr IS NULL;
CREATE INDEX IF NOT EXISTS press_link ON press_revisions(link);
CREATE INDEX IF NOT EXISTS press_date ON press_revisions(published DESC,id DESC);
CREATE TABLE IF NOT EXISTS press_chunked(revision INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS press_parts(revision INTEGER NOT NULL,pos INTEGER NOT NULL,length INTEGER NOT NULL,translation TEXT,retry INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(revision,pos));
CREATE INDEX IF NOT EXISTS press_part_queue ON press_parts(retry,revision,pos) WHERE translation IS NULL;
"""


def host(url):
    try:
        p = urlsplit(url)
        if p.scheme != "https" or p.username or p.password or p.port not in (443, None):
            return ""
        h = (p.hostname or "").lower().removeprefix("www.")
        return h if re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z][a-z0-9-]+", h) else ""
    except ValueError:
        return ""


def canonical(url):
    if not host(url):
        return ""
    p = urlsplit(url)
    query = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k not in ("fbclid", "gclid")
    ]
    return urlunsplit(("https", p.netloc.lower(), p.path or "/", urlencode(query), ""))


def network_url(url):
    if not host(url) or urlsplit(url).netloc not in NETWORK:
        raise ValueError("Kaynak adresi doğrulanamadı")
    return url


class Redirect(HTTPRedirectHandler):
    def __init__(self, project=None):
        super().__init__()
        self.project = project

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.project and not project_url(self.project, newurl):
            raise ValueError("Proje sayfası başka bir adrese yönlendirildi")
        return super().redirect_request(
            req, fp, code, msg, headers, network_url(newurl)
        )


def fetch(url, project=None):
    if project and not project_url(project, url):
        raise ValueError("Makale adresi projenin yayın dizinine ait değil")
    req = Request(
        network_url(url),
        headers={
            "User-Agent": "PostgresGundem/1.1 (+https://github.com/EnezMutluoglu/postgres-gundem)"
        },
    )
    with build_opener(Redirect(project)).open(req, timeout=18) as r:
        if project and canonical(r.url) != url:
            raise ValueError("Makalenin son adresi site haritasıyla eşleşmedi")
        raw = r.read(6_000_001)
    if len(raw) > 6_000_000:
        raise ValueError("Akış boyut sınırını aştı")
    return raw


def text(value):
    if not value:
        return ""
    if "<" in value and ">" in value:
        doc = BeautifulSoup(value, "html.parser")
        for tag in doc.select("script,style,noscript"):
            tag.decompose()
        value = doc.get_text(" ", strip=True)
    return " ".join(value.split())


def excerpt(value):
    if len(value) <= 680:
        return value
    cut = re.search(r"^(.{60,665}[.!?。！？])(?:\s|$)", value)
    if cut:
        return cut[1]
    return value[:660].rsplit(" ", 1)[0] + "…"


def date_value(raw):
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00").replace(" at ", "T"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(raw)
        except (ValueError, TypeError, OverflowError):
            return ""
    return (
        (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))
        .astimezone(timezone.utc)
        .isoformat(timespec="seconds")
    )


def record_source(con, h, name, evidence, approved, ts):
    if h:
        approved = approved and h not in SHARED_HOSTS
        con.execute(
            """INSERT INTO press_sources VALUES(?,?,?,?,?,?) ON CONFLICT(host) DO UPDATE SET
          name=CASE WHEN excluded.approved>approved OR name=host THEN excluded.name ELSE name END,
          evidence=CASE WHEN excluded.approved>approved THEN excluded.evidence ELSE evidence END,
          approved=max(approved,excluded.approved),seen=max(seen,excluded.seen),verified=max(verified,excluded.verified)""",
            (h, name or h, evidence, int(approved), ts, ts if approved else 0),
        )


def setup(con):
    con.executescript(SCHEMA)
    for _, name, url, h in FEEDS:
        if h:
            record_source(con, h, name, url, True, 0)
    for url, (name, _, _) in PROJECTS.items():
        record_source(con, host(url), name, url, True, 0)


def directory(con, url, raw, ts):
    doc = BeautifulSoup(raw, "html.parser")
    links = (
        doc.select("#pgContentWrap tr td:first-child a[href]")
        if url == INTL
        else [
            a
            for a in doc.select("li > a[href]")
            if not a.find("img")
            and a.parent.select_one('img[alt="RSS"]')
            and (
                a.parent.find("ul", recursive=False)
                or urlsplit(a["href"]).path in ("", "/")
            )
        ]
    )
    if not links:
        raise ValueError("Kaynak dizini okunamadı")
    for a in links:
        h = host(a["href"].replace("http://", "https://", 1))
        if h in SHARED_HOSTS:
            continue
        record_source(con, h, h, url, True, ts)


def store(con, url, h, lang, title, summary, body, pub, origin, rank, ts):
    url = canonical(url)
    title = text(title)
    if not url or not h or not title:
        return
    lang = (lang or "und").strip().lower().replace("_", "-")
    if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", lang):
        lang = "und"
    key = " ".join(re.findall(r"\w+", title.casefold()))
    hit = con.execute("SELECT * FROM press_articles WHERE url=?", (url,)).fetchone()
    if not hit:
        hit = con.execute(
            "SELECT a.* FROM press_revisions r JOIN press_articles a ON a.id=r.article WHERE r.link=? LIMIT 1",
            (url,),
        ).fetchone()
    if not hit:
        # Newspaper search links are opaque. Merge only the search copy with its publisher's native entry.
        hit = con.execute(
            """SELECT a.* FROM press_articles a JOIN press_revisions r ON r.id=a.current_revision
          WHERE a.host=? AND a.title_key=? AND (r.rank=0 OR ?=0) AND substr(r.published,1,10)=? ORDER BY a.id LIMIT 1""",
            (h, key, rank, pub[:10]),
        ).fetchone()
    short = excerpt(text(summary or body))
    full = text(body or summary)
    if short == title:
        short = ""
    old = None
    if hit:
        article = hit["id"]
        old = con.execute(
            "SELECT rank,signature FROM press_revisions WHERE id=?",
            (hit["current_revision"],),
        ).fetchone()
    else:
        article = con.execute(
            "INSERT INTO press_articles(url,host,title_key) VALUES(?,?,?)",
            (url, h, key),
        ).lastrowid
    signature = hashlib.sha256(
        json.dumps(
            [lang, title, short, full, pub, url, origin], ensure_ascii=False
        ).encode()
    ).hexdigest()
    con.execute(
        """INSERT OR IGNORE INTO press_revisions(article,signature,lang,title,excerpt,original,published,observed,origin,rank,link,title_tr,excerpt_tr)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            article,
            signature,
            lang,
            title,
            short,
            full,
            pub,
            ts,
            origin,
            rank,
            url,
            title if lang.split("-")[0] == "tr" else None,
            short if lang.split("-")[0] == "tr" else None,
        ),
    )
    if old and (old["rank"] > rank or old["signature"] == signature):
        return
    revision = con.execute(
        "SELECT id FROM press_revisions WHERE article=? AND signature=?",
        (article, signature),
    ).fetchone()[0]
    con.execute(
        "UPDATE press_articles SET current_revision=?,url=?,title_key=? WHERE id=?",
        (revision, url if rank or not hit else hit["url"], key, article),
    )


def parse_feed(con, raw, lang, name, domain, origin, ts, search=False, window=None):
    if b"<!ENTITY" in raw.upper() or b"<!DOCTYPE" in raw.upper():
        raise ValueError("Beklenmeyen XML bildirimi")
    root = ET.fromstring(raw)
    if root.tag.split("}")[-1] not in ("rss", "feed", "RDF"):
        raise ValueError("RSS veya Atom bekleniyordu")
    channel = root.find("{*}channel")
    default = (
        root.get("{http://www.w3.org/XML/1998/namespace}lang")
        or (channel.findtext("{*}language") if channel is not None else None)
        or lang
    )
    for entry in root.findall(".//{*}item") + root.findall("{*}entry"):

        def val(tag):
            return entry.findtext("{*}" + tag) or ""

        link = next(
            (
                element.get("href") or element.text or ""
                for element in entry.findall("{*}link")
                if element.get("rel", "alternate") == "alternate"
            ),
            "",
        ).strip()
        h = host(link)
        title = text(val("title"))
        pub = date_value(
            val("published") or val("pubDate") or val("updated") or val("date")
        )
        if window and not window[0] <= pub[:10] <= window[1]:
            continue
        summary = val("summary") or val("description")
        body = val("encoded") or val("content") or summary
        if search:
            publisher = entry.find("{*}source")
            if publisher is None or h != "news.google.com":
                continue
            h = host(publisher.get("url", ""))
            brand = publisher.text or h
            record_source(con, h, brand, origin, False, ts)
            approved = con.execute(
                "SELECT approved FROM press_sources WHERE host=?", (h,)
            ).fetchone()
            if not approved or not approved[0]:
                continue
            title = title.removesuffix(" - " + brand)
            summary = body = ""
        else:
            if not h or (domain and h != domain):
                continue
            record_source(con, h, name if domain else h, origin, True, ts)
        language = (
            entry.get("{http://www.w3.org/XML/1998/namespace}lang")
            or val("language")
            or default
        )
        if search:
            # A country's news search includes headlines in other languages.
            try:
                guess = detect_langs(title)[0]
                language = (
                    guess.lang if guess.prob >= 0.85 and len(title) >= 24 else lang
                )
                if language == "tr" and guess.lang != "tr":
                    language = "und"
            except LangDetectException:
                language = "und"
        store(
            con,
            link,
            h,
            language,
            title,
            summary,
            body,
            pub,
            origin,
            0 if search else 2 if domain else 1,
            ts,
        )


def planet(con, raw, ts):
    cards = BeautifulSoup(raw, "html.parser").select(".card-body:has(.planetpost)")
    if not cards:
        raise ValueError("Planet yazıları bulunamadı")
    for card in cards:
        a = card.select_one("h5 a[href]")
        stamp = card.select_one(".date")
        if not a or not stamp:
            continue
        h = host(a["href"])
        record_source(con, h, h, PLANET, True, ts)
        body = card.select_one(".planetpost").get_text(" ", strip=True)
        store(
            con,
            a["href"],
            h,
            "en",
            a.get_text(" ", strip=True),
            body,
            body,
            date_value(stamp.get_text(strip=True)),
            PLANET,
            1,
            ts,
        )


def project_url(origin, url):
    if not url or canonical(url) != url:
        return False
    parts = urlsplit(url)
    return (
        parts.netloc == urlsplit(origin).netloc
        and not parts.query
        and bool(re.fullmatch(PROJECTS[origin][1], parts.path))
    )


def project_index(con, raw, origin, ts):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Beklenmeyen site haritası bildirimi")
    root = ET.fromstring(raw)
    if root.tag.split("}")[-1] != "urlset":
        raise ValueError("Proje site haritası okunamadı")
    cutoff = datetime.fromtimestamp(ts, timezone.utc).date() - timedelta(days=365)
    found = False
    for entry in root.findall("{*}url"):
        url = entry.findtext("{*}loc") or ""
        if not project_url(origin, url):
            continue
        found = True
        path = urlsplit(url).path
        dated = re.search(r"/(\d{4})/(\d{2})/", path)
        modified = date_value(entry.findtext("{*}lastmod"))
        if dated and "-".join(dated.groups()) < cutoff.isoformat()[:7]:
            continue
        if modified and modified[:10] < cutoff.isoformat():
            continue
        con.execute(
            "INSERT OR IGNORE INTO press_project_pages(url,origin,due) VALUES(?,?,0)",
            (url, origin),
        )
    if not found:
        raise ValueError("Site haritasında proje haberleri bulunamadı")


def project_article(raw, origin, url):
    doc = BeautifulSoup(raw, "html.parser")
    for node in doc.select(
        'link[rel="canonical"][href],meta[property="og:url"][content]'
    ):
        target = node.get("href") or node.get("content")
        if canonical(target).rstrip("/") != url.rstrip("/"):
            raise ValueError("Yayıncının makale adresi eşleşmedi")

    def meta(key):
        n = doc.select_one(f'meta[property="{key}"]')
        return n.get("content", "") if n else ""

    stamp = date_value(meta("article:published_time"))
    if not stamp:
        day = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", urlsplit(url).path)
        stamp = date_value("-".join(day.groups())) if day else ""
    heading = doc.select_one("h1")
    title = meta("og:title") or (heading.get_text(" ", strip=True) if heading else "")
    article = doc.select_one(PROJECTS[origin][2])
    if not stamp or not title or not article:
        raise ValueError("Proje haberinin tarihi, başlığı veya metni doğrulanamadı")
    body = "\n".join(
        n.get_text(" ", strip=True)
        for n in article.select("p,li,pre")
        if not n.find_parent(["li", "pre"])
    )
    if not body.strip():
        raise ValueError("Proje haberinin metni boş")
    return title, meta("og:description"), body, stamp


def check_project_pages(db, fetcher, clock):
    ts = int(clock())
    with db() as con:
        pages = con.execute(
            "SELECT url,origin FROM press_project_pages WHERE due<=? ORDER BY due,url",
            (ts,),
        ).fetchall()
    for url, origin in pages:
        try:
            raw = fetcher(url, project=origin)
            title, summary, body, stamp = project_article(raw, origin, url)
            published = datetime.fromisoformat(stamp).timestamp()
            if published > ts + 86400:
                raise ValueError("Proje haberinin yayın tarihi gelecekte")
            active = published >= ts - 365 * 86400
            with db() as con:
                if active:
                    store(
                        con,
                        url,
                        host(url),
                        "en",
                        title,
                        summary,
                        body,
                        stamp,
                        origin,
                        3,
                        ts,
                    )
                con.execute(
                    "UPDATE press_project_pages SET checked=?,due=?,error=NULL WHERE url=?",
                    (ts, ts + WEEK if active else 2**62, url),
                )
        except Exception as exc:
            logging.warning("Proje haberi doğrulanamadı %s: %s", url, exc)
            with db() as con:
                con.execute(
                    "UPDATE press_project_pages SET due=?,error=? WHERE url=?",
                    (ts + 3600, str(exc)[:160], url),
                )


def jobs(today=None):
    today = today or datetime.now(timezone.utc).date()
    yield DIRECTORY, DIRECTORY, lambda c, b, t: directory(c, DIRECTORY, b, t)
    yield INTL, INTL, lambda c, b, t: directory(c, INTL, b, t)
    for lang, name, url, h in FEEDS:
        yield (
            url,
            url,
            lambda c, b, t, language=lang, publisher=name, domain=h, origin=url: (
                parse_feed(c, b, language, publisher, domain, origin, t)
            ),
        )
    yield PLANET, PLANET, planet
    for origin in PROJECTS:
        yield origin, origin, lambda c, b, t, u=origin: project_index(c, b, u, t)
    cutoff = today - timedelta(days=365)
    end = today
    while end >= cutoff:
        start = max(end.replace(day=1), cutoff)
        month = end.strftime("%Y-%m")
        for lang, country in MARKETS.items():
            query = urlencode(
                {
                    "q": "(PostgreSQL OR Postgres OR PostGIS OR Citus OR CloudNativePG OR pgBackRest OR pgvector) "
                    f"after:{start - timedelta(days=1)} before:{end + timedelta(days=1)}",
                    "hl": lang,
                    "gl": country,
                    "ceid": country + ":" + lang,
                }
            )
            yield (
                f"search/{month}/{lang}",
                SEARCH + "?" + query,
                lambda c, b, t, language=lang, window=(start.isoformat(), end.isoformat()): (
                    parse_feed(
                        c, b, language, "", "", SEARCH, t, search=True, window=window
                    )
                ),
            )
        end = start - timedelta(days=1)


def scan(db, fetcher=fetch, clock=time.time):
    today = datetime.fromtimestamp(clock(), timezone.utc).date()
    with db() as con:
        due = dict(con.execute("SELECT task,due FROM press_checks"))
    projects_checked = False
    for task, url, parse in jobs(today):
        ts = int(clock())
        if task.startswith("search/") and not projects_checked:
            check_project_pages(db, fetcher, clock)
            projects_checked = True
        if due.get(task, 0) > ts:
            continue
        try:
            raw = fetcher(url)
            with db() as con:
                parse(con, raw, ts)
                con.execute(
                    "INSERT OR REPLACE INTO press_checks VALUES(?,?,?,NULL)",
                    (
                        task,
                        ts
                        + (
                            366 * 86400
                            if task.startswith("search/")
                            and task.split("/")[1] != today.strftime("%Y-%m")
                            else WEEK
                        ),
                        ts,
                    ),
                )
        except Exception as exc:
            logging.warning("Dış basın taranamadı %s: %s", task, exc)
            with db() as con:
                con.execute(
                    """INSERT INTO press_checks(task,due,error) VALUES(?,?,?) ON CONFLICT(task)
                  DO UPDATE SET due=excluded.due,error=excluded.error""",
                    (task, ts + 3600, str(exc)[:160]),
                )
    # Only retire directory approvals after both directories have refreshed.
    with db() as con:
        ts = int(clock())
        healthy = con.execute(
            "SELECT count(*) FROM press_checks WHERE task IN (?,?) AND checked>=? AND error IS NULL",
            (DIRECTORY, INTL, ts - WEEK),
        ).fetchone()[0]
        if healthy == 2:
            seeds = [s[3] for s in FEEDS if s[3]] + [host(u) for u in PROJECTS]
            marks = ",".join("?" for _ in seeds)
            con.execute(
                f"UPDATE press_sources SET approved=0 WHERE verified<? AND host NOT IN ({marks})",
                (ts - 3 * WEEK, *seeds),
            )


def weekly(db):
    while True:
        try:
            scan(db)
        except Exception:
            logging.exception("Dış basın takibi kesildi")
        time.sleep(300)


def translate_fragment(db, translate, ts, retry_translate, health):
    with db() as con:
        part = con.execute(
            """SELECT p.revision,p.pos,substr(r.original,p.pos+1,p.length) AS source,r.lang
          FROM press_parts p JOIN press_revisions r ON r.id=p.revision
          LEFT JOIN translation_tasks j ON j.kind='body' AND j.ref=CAST(p.revision AS TEXT) AND j.part=p.pos
          WHERE p.translation IS NULL AND (j.status IS NULL OR j.due<=?)
          ORDER BY p.revision,p.pos LIMIT 1""",
            (ts,),
        ).fetchone()
        if not part:
            row = con.execute("""SELECT id,original FROM press_revisions r WHERE lang NOT LIKE 'tr%' AND original!=''
                AND original!=excerpt AND NOT EXISTS(SELECT 1 FROM press_chunked c WHERE c.revision=r.id)
                ORDER BY id DESC LIMIT 1""").fetchone()
            if not row:
                return False
            pos = 0
            original = row["original"]
            while pos < len(original):
                chunk = original[pos : pos + 620]
                if pos + len(chunk) < len(original):
                    cut = list(re.finditer(r"[.!?。！？](?:\s|$)|\s", chunk))
                    if cut:
                        chunk = chunk[: cut[-1].end()]
                con.execute(
                    "INSERT OR IGNORE INTO press_parts(revision,pos,length) VALUES(?,?,?)",
                    (row["id"], pos, len(chunk)),
                )
                pos += len(chunk)
            con.execute("INSERT OR IGNORE INTO press_chunked VALUES(?)", (row["id"],))
            return True
    source = part["source"].strip()
    return tasks.run(
        db,
        "body",
        part["revision"],
        part["pos"],
        source,
        part["lang"],
        lambda attempt: (
            (retry_translate if attempt > 1 and retry_translate else translate)(
                source, part["lang"]
            )
            if source
            else ""
        ),
        lambda con, value: con.execute(
            "UPDATE press_parts SET translation=? WHERE revision=? AND pos=?",
            (value, part["revision"], part["pos"]),
        ),
        health=health,
    )


def translate_one(db, translate, *, retry_translate=None, health=None):
    ts = int(time.time())
    with db() as con:
        row = con.execute(
            """SELECT r.*, f.part FROM press_revisions r JOIN press_articles a ON a.id=r.article
            CROSS JOIN (SELECT 0 AS part UNION ALL SELECT 1) f
            LEFT JOIN translation_tasks j ON j.kind='press' AND j.ref=CAST(r.id AS TEXT) AND j.part=f.part
            WHERE ((f.part=0 AND r.title_tr IS NULL) OR (f.part=1 AND r.excerpt!='' AND r.excerpt_tr IS NULL))
            AND (j.status IS NULL OR j.due<=?)
            ORDER BY (a.current_revision=r.id) DESC,r.published DESC,r.id,f.part LIMIT 1""",
            (ts,),
        ).fetchone()
    if not row:
        return translate_fragment(db, translate, ts, retry_translate, health)
    field = "title" if row["part"] == 0 else "excerpt"
    return tasks.run(
        db,
        "press",
        row["id"],
        row["part"],
        row[field],
        row["lang"],
        lambda attempt: (
            retry_translate if attempt > 1 and retry_translate else translate
        )(row[field], row["lang"]),
        lambda con, value: con.execute(
            f"UPDATE press_revisions SET {field}_tr=?, error=NULL WHERE id=?",
            (value, row["id"]),
        ),
        health=health,
    )


def translations(db, translate, **options):
    while True:
        try:
            status = translate_one(db, translate, **options)
            if status and status != "offline":
                continue
        except Exception:
            logging.exception("Dış basın çevirisi kesildi")
        time.sleep(20)


def register(app, db):
    @app.get("/api/dis-basin")
    def press():
        host_filter = request.args.get("kaynak", "")
        lang_filter = request.args.get("dil", "")
        page = max(1, min(request.args.get("sayfa", 1, type=int), 1_000_000))
        where = " WHERE 1=1"
        params = []
        if host_filter:
            where += " AND a.host=?"
            params.append(host_filter)
        if lang_filter:
            where += " AND r.lang=?"
            params.append(lang_filter)
        if request.args.get("konu") == "teknoloji":
            where += " AND EXISTS(SELECT 1 FROM press_project_pages p WHERE p.url=a.url AND p.checked IS NOT NULL)"
        joined = (
            " FROM press_articles a JOIN press_revisions r ON r.id=a.current_revision"
        )
        with db() as con:
            con.execute("BEGIN")
            total = con.execute("SELECT count(*)" + joined + where, params).fetchone()[
                0
            ]
            rows = con.execute(
                """SELECT a.id,a.url,a.host,r.id AS revision,r.lang,r.title,r.title_tr,r.excerpt,r.excerpt_tr,r.published,r.observed,r.error,r.origin
                ,EXISTS(SELECT 1 FROM translation_tasks j WHERE j.kind='press' AND j.ref=CAST(r.id AS TEXT) AND j.status='failed') AS original_only
                ,(SELECT count(*) FROM press_revisions v WHERE v.article=a.id) AS versions
                ,(SELECT checked FROM press_project_pages p WHERE p.url=a.url) AS link_checked
                ,(SELECT error IS NOT NULL FROM press_project_pages p WHERE p.url=a.url) AS link_failed
                """
                + joined
                + where
                + " ORDER BY r.published DESC,a.id DESC LIMIT 20 OFFSET ?",
                [*params, (page - 1) * 20],
            ).fetchall()
            sources = con.execute("""SELECT s.host,s.name,count(*) AS articles FROM press_articles a JOIN press_sources s USING(host)
               GROUP BY s.host ORDER BY s.name""").fetchall()
            langs = [
                r[0]
                for r in con.execute(
                    "SELECT DISTINCT r.lang" + joined + " ORDER BY r.lang"
                )
            ]
            active_tasks = {task for task, _, _ in jobs()}
            health = [
                r
                for r in con.execute("SELECT task,checked,error FROM press_checks")
                if r["task"] in active_tasks
            ]
            page_errors = con.execute(
                "SELECT count(*) FROM press_project_pages WHERE error IS NOT NULL"
            ).fetchone()[0]
            candidates = con.execute(
                "SELECT count(*) FROM press_sources WHERE approved=0"
            ).fetchone()[0]
        return jsonify(
            items=[dict(r) for r in rows],
            sources=[dict(s) for s in sources],
            languages=langs,
            total=total,
            page=page,
            checked=max((r["checked"] for r in health if r["checked"]), default=None),
            errors=sum(bool(r["error"]) for r in health) + page_errors,
            checked_tasks=sum(r["checked"] is not None for r in health),
            expected_tasks=len(active_tasks),
            candidates=candidates,
        )

    @app.get("/api/dis-basin/kaynaklar")
    def publishers():
        with db() as con:
            rows = con.execute(
                "SELECT host,name,evidence,approved,seen FROM press_sources ORDER BY approved DESC,name"
            ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.get("/api/dis-basin/<int:article>/gecmis")
    def history(article):
        with db() as con:
            rows = con.execute(
                """SELECT r.id AS revision,r.title,r.excerpt,r.title_tr,r.excerpt_tr,r.observed,r.lang FROM press_revisions r
              JOIN press_articles a ON a.id=r.article WHERE a.id=? AND a.current_revision!=r.id ORDER BY r.id DESC""",
                (article,),
            ).fetchall()
        return jsonify([dict(r) for r in rows])
