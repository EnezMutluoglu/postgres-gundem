"""Collect public PostgreSQL and PGXN records. All version facts come from the sources."""

import hashlib
import json
import re
import threading
import time
from datetime import date
from http.client import IncompleteRead
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bs4 import BeautifulSoup

PG = "https://www.postgresql.org"
CF = "https://commitfest.postgresql.org"
PGXN = "https://pgxn.org"
SOURCE_HOSTS = {urlsplit(site).hostname for site in (PG, CF, PGXN)}
_cache = {}
_lock = threading.Lock()


def trusted(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc not in SOURCE_HOSTS:
        raise ValueError("Beklenmeyen kaynak adresi")
    return url


class SourceRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, trusted(newurl))


def fetch(url):
    for attempt in range(3):
        try:
            return fetch_once(url)
        except HTTPError as exc:
            if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (OSError, IncompleteRead):
            if attempt == 2:
                raise
        time.sleep(2**attempt)


def fetch_once(url):
    headers = {"User-Agent": "PostgresGundem/1.0 (hourly release reader)"}
    with _lock:
        cached = _cache.get(url)
    if cached:
        headers.update(cached[0])
    try:
        response = build_opener(SourceRedirect()).open(
            Request(trusted(url), headers=headers), timeout=25
        )
    except HTTPError as error:
        if error.code == 304 and cached:
            error.close()
            return cached[1]
        raise
    with response:
        trusted(response.url)
        data = response.read(8_000_001)
        if len(data) > 8_000_000:
            raise ValueError("Kaynak boyut sınırı aşıldı")
        validators = {
            cond: response.headers[key]
            for key, cond in (
                ("ETag", "If-None-Match"),
                ("Last-Modified", "If-Modified-Since"),
            )
            if response.headers.get(key)
        }
        if validators:
            with _lock:
                if len(_cache) >= 350 and url not in _cache:
                    _cache.pop(next(iter(_cache)))
                _cache[url] = validators, data
        return data


def page(url):
    return BeautifulSoup(fetch(url).decode("utf-8"), "html.parser")


def clean(node):
    return " ".join(node.stripped_strings).replace("\xa0", " ").strip() if node else ""


def compact(value):
    return " ".join(value.split())


def record(kind, url, title, **kwargs):
    return dict(kind=kind, id=kwargs.pop("id", url), url=url, title=title, **kwargs)


def versions():
    rows = json.loads(fetch(PG + "/versions.json"))
    return {
        r["major"]: {
            "latest": r["major"] + "." + r["latestMinor"],
            "supported": r["supported"] and r["eolDate"] >= date.today().isoformat(),
            "eol": r["eolDate"],
            "date": r["relDate"],
        }
        for r in rows
    }


def paragraphs_between(heading):
    if heading:
        for node in heading.find_next_siblings():
            if re.fullmatch(r"h[1-6]", node.name) and int(node.name[1]) <= int(
                heading.name[1]
            ):
                break
            if node.name in ("p", "ul", "ol"):
                yield compact(clean(node))


def releases():
    archive = page(PG + "/about/newsarchive/pgsql/")
    items = []
    for link in archive.select("#pgContentWrap h2 a"):
        title = clean(link)
        if not re.match(r"PostgreSQL \d", title) or not re.search(
            r"releas|available", title, re.I
        ):
            continue
        url = trusted(urljoin(PG, link["href"]))
        doc = page(url).select_one("#pgContentWrap")
        when = clean(doc.select_one(".newsdate strong"))
        first = compact(clean(doc.select_one(":scope > p")))
        stable = re.findall(r"\b\d+\.\d+\b", title)
        pre = re.search(r"\b(\d+)\s*(Beta|RC)\s*(\d+)", title, re.I)
        if stable and len([r for r in items if r["kind"] == "release"]) < 5:
            header = next(
                (
                    h
                    for h in doc.select("h2,h3")
                    if re.match(r"Updat|Upgrad", clean(h), re.I)
                ),
                None,
            )
            notes = list(paragraphs_between(header))
            # Keep operational conditions together. Full procedures are linked at the source.
            steps = [
                p
                for p in notes
                if not re.match(
                    r"All PostgreSQL update releases|For more details|Users who have skipped|(?:REINDEX|SELECT|ALTER|UPDATE|CREATE|DROP|DELETE)\s",
                    p,
                    re.I,
                )
            ]
            count = re.search(r"(\d+) security vulnerabilit", first, re.I)
            items.append(
                record(
                    "release",
                    url,
                    "PostgreSQL " + stable[0],
                    date=when,
                    versions=stable,
                    summary=first,
                    notes=steps,
                    count=int(count[1]) if count else None,
                    guidance_revision=hashlib.sha256(
                        "\n".join(notes).encode()
                    ).hexdigest(),
                )
            )
        if pre:
            stage = "Beta" if pre[2].lower() == "beta" else "RC"
            stage_name = f"PostgreSQL {pre[1]} {stage} {pre[3]}"
            items.append(
                record(
                    "dev",
                    url,
                    stage_name,
                    id=url + "#preview",
                    date=when,
                    label="Beta" if stage == "Beta" else "Sürüm adayı",
                    summary="",
                    fixed_text="Üretim öncesi test sürümü. Geçiş ve uyumluluk kontrolleri için yayımlandı.",
                )
            )
        if re.match(r"^PostgreSQL \d+ Released", title, re.I):
            major = re.search(r"\d+", title)[0]
            items.append(
                record(
                    "release",
                    url,
                    "PostgreSQL " + major,
                    date=when,
                    versions=[major],
                    summary=first,
                    notes=[],
                    count=None,
                )
            )
    if not items:
        raise ValueError("Sürüm duyuruları okunamadı")
    return items


def security_index():
    rows = []
    for tr in page(PG + "/support/security/").select("tbody tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) != 5:
            continue
        ref = cells[0].select_one('a[href*="/CVE-"]')
        announcement = cells[0].select_one('a[href*="/about/news/"]')
        if not ref:
            continue
        score = cells[3].find("a")
        rows.append(
            dict(
                cve=clean(ref),
                url=trusted(urljoin(PG, ref["href"])),
                title=str(next(cells[4].stripped_strings)),
                component=str(next(cells[3].stripped_strings)),
                score=float(clean(score))
                if score and re.fullmatch(r"\d+(\.\d+)?", clean(score))
                else None,
                bulletin=urljoin(PG, announcement["href"]) if announcement else "",
            )
        )
    if not rows:
        raise ValueError("Güvenlik dizini okunamadı")
    return rows


def advisory(info):
    doc = page(info["url"]).select_one("#pgContentWrap")
    heading = doc.find(["h2", "h3"], string=re.compile("Version Information", re.I))
    table = heading.find_next_sibling("table") if heading else None
    if not table:
        raise ValueError("CVE sürüm tablosu okunamadı")
    matrix = []
    dates = []
    for tr in table.select("tbody tr"):
        cells = [compact(clean(c)) for c in tr.find_all("td", recursive=False)]
        if len(cells) >= 2:
            matrix.append({"major": cells[0], "fixed": cells[1]})
            if len(cells) >= 3 and re.fullmatch(r"\d{4}-\d\d-\d\d", cells[2]):
                dates.append(cells[2])
    if not matrix:
        raise ValueError("CVE sürüm eşleşmeleri eksik")
    intro = []
    for node in heading.find_previous_siblings():
        if node.name == "p":
            intro.insert(0, compact(clean(node)))
    body = " ".join(intro)
    # Only publish the impact and source-qualified scope, not proof-of-concept or SQL walkthroughs.
    impact = (
        re.split(r"(?<=[.!?])\s+(?=[A-Z])", intro[0])[0] if intro else info["title"]
    )
    scope = [
        s
        for s in re.split(r"(?<=[.!?])\s+", body)
        if re.search(r"\b(?:are|is|were) (?:un)?affected\b", s, re.I)
        and re.search(r"\d", s)
        and len(s) < 900
    ]
    extra = bool(
        re.search(
            r"remediation steps|additional steps|extra steps|remain vulnerable|only fixes fresh|must .*after updat",
            body,
            re.I,
        )
    )
    guidance = " ".join(
        compact(clean(n))
        for n in reversed(heading.find_previous_siblings())
        if n.name in ("p", "ol", "ul", "pre")
    )
    remediation = []
    if extra:
        for node in reversed(heading.find_previous_siblings()):
            if node.name in ("ol", "ul"):
                for li in node.find_all("li", recursive=False):
                    step = compact(clean(li))
                    if "https://" not in step and len(step) > 30:
                        remediation.append(
                            re.split(r"\s+For example[:,]", step, maxsplit=1)[0]
                        )
            elif node.name == "p" and clean(node).startswith("After executing"):
                remediation.append(compact(clean(node)).split(" You can do this")[0])
    return record(
        "security",
        info["url"],
        info["title"],
        id=info["cve"],
        date=max(dates, default=""),
        summary=impact,
        matrix=matrix,
        scope=scope,
        extra=extra,
        notes=remediation,
        bulletin=info["bulletin"],
        guidance_revision=hashlib.sha256(guidance.encode()).hexdigest(),
        score=info["score"],
        component=info["component"],
    )


def development():
    home = PG + "/docs/devel/release.html"
    doc = page(home)
    link = doc.select_one('.toc a[href^="release-"]')
    if not link:
        raise ValueError("Geliştirme sürümü bulunamadı")
    urls = [urljoin(home, link["href"])]
    for anchor in doc.select("a[href]"):
        match = re.fullmatch(r"/docs/(\d+)/release\.html", anchor.get("href", ""))
        if (
            match
            and "Development Versions"
            in clean(anchor.parent).split("Unsupported Versions")[0]
            and len(clean(anchor.parent)) < 120
        ):
            urls.append(f"{PG}/docs/{match[1]}/release-{match[1]}.html")
    items = []
    for url in dict.fromkeys(urls):
        major = re.search(r"release-(\d+)", url)[1]
        article = page(url).select_one("#docContent .sect1")
        if not article:
            raise ValueError("Geliştirme notları okunamadı")
        for li in article.select(".itemizedlist li > p:first-child")[:10]:
            phrase = compact(clean(li))
            if not phrase:
                continue
            anchor = (
                li.find_parent("li").get("id")
                or hashlib.sha256(phrase.split(". ")[0].encode()).hexdigest()[:16]
            )
            items.append(
                record(
                    "dev",
                    url,
                    phrase.split(". ")[0].rstrip("."),
                    id=f"notes:{major}:{anchor}",
                    summary=phrase,
                    date="",
                    label="Sürüme alındı",
                    series=major,
                )
            )
    return items


def proposals():
    home = page(CF)
    agenda = {
        clean(t.find("strong")).rstrip(":"): t.a
        for t in home.select("tr")
        if t.find("strong") and t.a
    }
    link = agenda.get("In Progress") or agenda.get("Open")
    url = trusted(urljoin(CF, link["href"]))
    stages = {
        "Needs review": "İncelemede",
        "Ready for Committer": "Son incelemede",
        "Waiting on Author": "Yazardan yanıt bekleniyor",
        "Committed": "Sürüme alındı",
        "Withdrawn": "Geri çekildi",
        "Rejected": "Reddedildi",
        "Returned with feedback": "Yazara iade edildi",
        "Moved to next CF": "Sonraki döneme taşındı",
    }
    result = []
    for td in page(url).select("td.patch-column"):
        cells = td.parent.find_all("td", recursive=False)
        status = clean(cells[2])
        if not td.a or status not in stages:
            continue
        when = (cells[-1].get("title") or "")[:10]
        result.append(
            record(
                "dev",
                trusted(urljoin(CF, td.a["href"])),
                clean(td.a),
                date=when,
                label=stages[status],
                series=clean(cells[4]),
                summary="",
                meeting=clean(link),
            )
        )
    if not result:
        raise ValueError("CommitFest kayıtları okunamadı")
    return sorted(result, key=lambda x: x["date"], reverse=True)


def bundled_extensions():
    url = PG + "/docs/current/contrib.html"
    doc = page(url)
    version = re.search(r"Documentation:\s*(\d+)", clean(doc.title))[1]
    notes_url = f"{PG}/docs/{version}/release-{version}.html"
    notes = page(notes_url).select('[id$="-MODULES"] li > p:first-child')
    result = []
    for link in doc.select(".toc > dl > dt > span > a"):
        name, sep, desc = re.sub(r"^F\.\d+\.\s*", "", clean(link)).partition(" — ")
        if not sep or not re.fullmatch(r"[\w-]+", name):
            continue
        target = urljoin(f"{PG}/docs/{version}/contrib.html", link["href"])
        changes = []
        for note in notes:
            if any(
                a["href"].split("#")[0] == link["href"] for a in note.select("a[href]")
            ) or re.search(r"\b" + re.escape(name) + r"\b", clean(note)):
                changes.append(
                    re.sub(r"\s*\([^()]+\)\s*(?:§\s*)+$", "", compact(clean(note)))
                )
        result.append(
            record(
                "extension",
                target,
                name,
                id="contrib:" + name,
                date="",
                summary=desc,
                label="PostgreSQL ile gelir",
                version="PostgreSQL " + version,
                notes=changes,
                notes_url=notes_url + "#RELEASE-" + version + "-MODULES",
            )
        )
    if not result:
        raise ValueError("Birlikte dağıtılan eklentiler okunamadı")
    return result


def community_extensions():
    doc = page(PGXN + "/recent/")
    result = []
    for row in doc.select(".res"):
        link = row.select_one("h2 a")
        if not link or not row.time:
            continue
        url = trusted(urljoin(PGXN, link["href"]))
        _, name, version = urlsplit(url).path.strip("/").split("/")
        notes = []
        article = page(url)
        log = next(
            (
                a
                for a in article.select("a[href]")
                if re.search(
                    r"/(?:Changes|Changelog|Change[-_]Log|History)\.html$",
                    a["href"],
                    re.I,
                )
            ),
            None,
        )
        if log:
            log_url = trusted(urljoin(url, log["href"]))
            change_doc = page(log_url)
            h = next(
                (
                    h
                    for h in change_doc.select("h1,h2,h3,h4")
                    if re.search(
                        r"(?<![\d.])" + re.escape(version) + r"(?![\d.])", clean(h)
                    )
                ),
                None,
            )
            if h:
                notes = list(paragraphs_between(h))[:2]
        result.append(
            record(
                "extension",
                url,
                name,
                date=row.time.get("datetime", "")[:10],
                summary=compact(clean(row.p)),
                label="PGXN",
                version=version,
                notes=notes,
                notes_url=log_url if log else "",
            )
        )
        if len(result) >= 15:
            break
    if not result:
        raise ValueError("PGXN yayınları okunamadı")
    return result
