"""Single-process bulletin service. SQLite keeps the last successful source snapshots."""

import json
import logging
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request, send_from_directory
from waitress import serve
from langdetect import DetectorFactory, LangDetectException, detect_langs
from archive import archive
from admin import register

import feeds
import community
import news_search
import translation_jobs as tasks

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("GUNDEM_DATA", ROOT / ".data"))
MODEL = os.environ.get("GUNDEM_MODEL_URL", "http://127.0.0.1:18081")
MODEL_TIMEOUT = int(os.environ.get("GUNDEM_MODEL_TIMEOUT", "200"))
PORT = int(os.environ.get("GUNDEM_PORT", "8080"))
SOURCES = {
    "releases": "Sürüm duyuruları",
    "security": "Güvenlik kayıtları",
    "notes": "Geliştirme notları",
    "commitfest": "CommitFest",
    "pgxn": "PGXN",
    "contrib": "Birlikte dağıtılan eklentiler",
    "versions": "Sürüm dizini",
}
EDITORIAL = json.loads((ROOT / "turkish.json").read_text(encoding="utf-8"))
app = Flask(__name__)
work = threading.Event()
DetectorFactory.seed = 0


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db():
    con = sqlite3.connect(DATA / "gundem.sqlite", timeout=30)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def initialize():
    DATA.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
          CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, source TEXT NOT NULL, data TEXT NOT NULL, seq INTEGER NOT NULL, observed TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS item_history(id TEXT NOT NULL,source TEXT NOT NULL,data TEXT NOT NULL,seq INTEGER NOT NULL,observed TEXT NOT NULL,PRIMARY KEY(id,seq));
          INSERT OR IGNORE INTO item_history SELECT id,source,data,seq,observed FROM items;
          CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS texts(original TEXT PRIMARY KEY, translation TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sources(name TEXT PRIMARY KEY, success TEXT, error TEXT);
        """)
        tasks.setup(con)
        community.setup(con)
        news_search.setup(con)
        # Apply the same checks to translations produced by earlier releases.
        stale = [
            (original, translation)
            for original, translation in con.execute(
                "SELECT original, translation FROM texts WHERE translation <> ''"
            )
            if not terms_preserved(glossary_for(original), translation)
            or not reasons_supported(original, translation)
            or not safe_instruction(original, translation)
        ]
        con.executemany(
            "UPDATE texts SET translation='' WHERE original=? AND translation=?", stale
        )
        if tasks.import_existing(con, EDITORIAL):
            for (raw,) in con.execute("SELECT data FROM item_history"):
                queue_official(con, json.loads(raw))
        con.executemany(
            "DELETE FROM translation_memory WHERE language='en' AND original=? AND translation=?",
            stale,
        )


def queue_official(con, item):
    for source in set(text_fields(item)) - EDITORIAL.keys():
        con.execute(
            """INSERT OR IGNORE INTO translation_tasks(kind,ref,part,attempts,status,due,detail)
            SELECT 'official',?,0,0,'queued',0,'' WHERE NOT EXISTS
            (SELECT 1 FROM texts WHERE original=? AND translation<>'')""",
            (source, source),
        )


def save(source, items):
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        seq = con.execute("SELECT coalesce(max(seq),0) FROM items").fetchone()[0]
        initial_seq = seq
        for item in items:
            data = json.dumps(item, sort_keys=True, ensure_ascii=False)
            old = con.execute(
                "SELECT data FROM items WHERE id=?", (item["id"],)
            ).fetchone()
            if old and old[0] == data:
                continue
            seq += 1
            row = (item["id"], source, data, seq, now())
            con.execute("INSERT INTO item_history VALUES(?,?,?,?,?)", row)
            queue_official(con, item)
            con.execute(
                "INSERT OR REPLACE INTO items VALUES(?,?,?,?,?)",
                row,
            )
    if seq != initial_seq:
        work.set()


def state(key, value):
    with db() as con:
        con.execute(
            "INSERT OR REPLACE INTO state VALUES(?,?)", (key, json.dumps(value))
        )


def source_status(source, error=None):
    with db() as con:
        if error:
            con.execute(
                "INSERT INTO sources(name,error) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET error=excluded.error",
                (source, str(error)[:180]),
            )
        else:
            con.execute(
                "INSERT OR REPLACE INTO sources VALUES(?,?,NULL)", (source, now())
            )


def collect(source):
    if source == "versions":
        state("versions", feeds.versions())
    elif source == "security":
        errors = []
        # Publish individual verified advisories even if another page is temporarily unavailable.
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [pool.submit(feeds.advisory, i) for i in feeds.security_index()]
            for task in as_completed(jobs):
                try:
                    save(source, [task.result()])
                except Exception as exc:
                    errors.append(exc)
        if errors:
            raise ValueError(f"{len(errors)} güvenlik kaydı okunamadı") from errors[0]
    elif source == "commitfest":
        rows = feeds.proposals()
        with db() as con:
            tracked = {
                r[0]
                for r in con.execute("SELECT id FROM items WHERE source='commitfest'")
            }
        save(source, [r for i, r in enumerate(rows) if i < 12 or r["id"] in tracked])
    else:
        get = {
            "releases": feeds.releases,
            "notes": feeds.development,
            "pgxn": feeds.community_extensions,
            "contrib": feeds.bundled_extensions,
        }[source]
        save(source, get())


def refresh():
    state("attempt", now())
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(collect, src): src for src in SOURCES}
        for job in as_completed(jobs):
            src = jobs[job]
            try:
                job.result()
                source_status(src)
            except Exception as exc:
                logging.exception("Kaynak yenilenemedi: %s", src)
                source_status(src, exc)
    state("completed", now())


def hourly():
    while True:
        start = time.monotonic()
        try:
            refresh()
        except Exception:
            logging.exception("Güncelleme kesildi")
        time.sleep(max(1, 3600 - (time.monotonic() - start)))


def text_fields(item):
    if item["kind"] in ("security", "dev") and not item.get("fixed_text"):
        yield item["title"]
    if item.get("summary"):
        yield item["summary"]
    yield from item.get("scope", [])
    yield from item.get("notes", [])


# The Turkish patterns allow case endings and plural forms, including kaydı/kayıtları.
GLOSSARY = [
    ("maintenance update", "bakım güncellemesi", r"bakım güncelleme"),
    ("maintenance release", "bakım sürümü", r"bakım sürüm"),
    ("maintenance window", "bakım penceresi", r"bakım pencere"),
    ("minor release", "bakım sürümü", r"bakım sürüm"),
    ("security update", "güvenlik güncellemesi", r"güvenlik güncelleme"),
    ("standby server", "bekleme sunucusu", r"bekleme sunucu"),
    ("primary server", "birincil sunucu", r"birincil sunucu"),
    ("WAL record", "WAL kaydı", r"WAL kay(?:dı|ıt\b|ıtlar|ıtta)"),
    ("logical replication", "mantıksal çoğaltma", r"mantıksal çoğaltma"),
    ("query planner", "sorgu planlayıcısı", r"sorgu planlayıcı"),
    ("row-level security", "satır düzeyinde güvenlik", r"satır düzeyinde güvenli[kğ]"),
    ("release candidate", "sürüm adayı", r"sürüm aday"),
    ("full backup", "tam yedek", r"tam (?:bir )?yede[kğ]"),
    ("patch", "yama", r"yama"),
    ("temporary table", "geçici tablo", r"geçici tablo"),
    ("connection pool", "bağlantı havuzu", r"bağlantı havuz"),
    ("system catalog", "sistem kataloğu", r"sistem katalog|sistem kataloğ"),
    ("recovery", "kurtarma", r"kurtar"),
    ("read-only transaction", "salt okunur işlem", r"salt okunur işlem"),
    ("release notes", "sürüm notları", r"sürüm not"),
    ("replication slot", "çoğaltma yuvası", r"(?:çoğaltma|replikasyon) (?:yuva|slot)"),
    ("transaction block", "işlem bloğu", r"işlem blo[kğ]"),
    ("deadlock", "karşılıklı kilitlenme", r"(?:karşılıklı kilitlenme|ölü kilit)"),
    ("isolation level", "yalıtım düzeyi", r"(?:yalıtım|izolasyon) (?:düzey|seviye)"),
]


def glossary_for(original):
    return [
        term
        for term in GLOSSARY
        if re.search(
            r"\b" + re.escape(term[0]) + r"(?:es|s)?\b", original, re.IGNORECASE
        )
    ]


def terms_preserved(terms, translation):
    return all(
        re.search(r"\b" + pattern, translation, re.IGNORECASE)
        for _, _, pattern in terms
    )


SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
TR_REASON = re.compile(
    r"\b(?:amaçlı|amacıyla|amaçlarıyla|gerekçesiyle|gerekçeleriyle|nedeniyle|nedenleriyle|"
    r"sebebiyle|dolayı|çünkü|böylece|bu sayede|aksi (?:halde|takdirde)|"
    r"tedbiren|ihtiyaten|her ihtimale karşı|(?:önlem|tedbir)i? olarak|"
    r"(?<!dahil )(?<!dâhil )\w+(?:mak|mek|ması|mesi|[dt][ıiuü]ğ[ıiuü]) (?:için|üzere))\b",
    re.IGNORECASE,
)
EN_REASON = re.compile(
    r"\b(?:because|due to|owing to|in order to|so (?:that|as to)|as a precaution|"
    r"thereby|therefore|otherwise|in case|as a safeguard|this (?:prevents|allows|ensures)|"
    r"as a .{0,32}?measure|for (?:[\w-]+ ){0,3}(?:reasons?|purposes?)|for \w+ing|"
    r"to (?:avoid|prevent|protect|preserve|ensure|allow|enable|keep|reduce|improve|"
    r"mitigate|recover|fix|resolve|address|restore|reload|support|maintain)|"
    r"since (?:the|this|it|they))\b|^(?:to \w+[^.!?]*|for [\w -]+),",
    re.IGNORECASE,
)
TR_SECURITY_REASON = re.compile(
    r"\b(?:bir )?güvenlik (?:amaçlı|amacıyla|amaçlarıyla|amaçları (?:için|nedeniyle)|açısından|adına|"
    r"(?:neden|sebe[bp]|gerekçe)\w*(?:yle|la|le)|için|"
    r"(?:önlem(?:i|leri)|tedbir(?:i|leri)) olarak)\b|\bgüvenliğ\w* (?:için|(?:sağlamak|korumak|artırmak) için)",
    re.IGNORECASE,
)
EN_INSTRUCTION = re.compile(
    r"(?:^|[,.!?]\s*)(?:(?:please|always|never|do not) )?(?:take|back up|apply|update|upgrade|"
    r"install|run|restart|stop|start|check|verify|use|add|remove|set|enable|disable|"
    r"create|rebuild|reindex|execute|ensure|replace|restore|revoke|make sure)\b|"
    r"\b(?:must|should|needs? to|(?:is|are) required|we recommend)\b",
    re.IGNORECASE,
)
EN_SECURITY_REASON = re.compile(
    r"\bfor (?:security|safety)(?: (?:reasons?|purposes?)\b|(?=[,.!?:;]|$))|"
    r"\bfor (?:your|their|its) (?:own )?safety\b|"
    r"\bas a (?:security|safety) (?:measure|precaution)\b|"
    r"\bto (?:ensure|improve|enhance|maintain) (?:\w+ ){0,2}(?:security|safety)\b",
    re.IGNORECASE,
)

# A different stated purpose must not license an invented operational justification.
MOTIVE_PAIRS = (
    (
        r"veri kaybını (?:önlemek|engellemek) için",
        r"(?:prevent|avoid) (?:losing data|data loss)",
    ),
    (
        r"performansı (?:artırmak|iyileştirmek) için",
        r"(?:improve|boost|increase) performance",
    ),
    (
        r"tedbiren|ihtiyaten|her ihtimale karşı|(?:önlem|tedbir) olarak",
        r"precaution|precautionary measure|just in case|to be safe|safety measure",
    ),
)


def reasons_supported(original, translation):
    security_reason = EN_SECURITY_REASON.search(original)
    translated_security = TR_SECURITY_REASON.search(translation)
    reason = TR_REASON.search(translation)
    instruction = EN_INSTRUCTION.search(original)
    # A second sentence appended to a simple command may explain it without any causal marker.
    if (
        instruction
        and len(original.split()) <= 35
        and SENTENCE_BREAK.search(translation)
        and not SENTENCE_BREAK.search(original)
        and not re.search(r"[,;:]|\b(?:and|or)\b", original, re.IGNORECASE)
        and not (security_reason or EN_REASON.search(original))
    ):
        return False
    if not (translated_security or security_reason or (reason and instruction)):
        return True
    sources = SENTENCE_BREAK.split(original)
    if len(sources) > 1:
        targets = SENTENCE_BREAK.split(translation)
        return len(sources) == len(targets) and all(
            reasons_supported(en, tr) for en, tr in zip(sources, targets)
        )
    # Mentioning a security update does not supply a reason for an instruction.
    if bool(translated_security) != bool(security_reason):
        return False
    if security_reason and translated_security:
        negated_source = re.search(
            r"\bnot\s+$", original[: security_reason.start()], re.IGNORECASE
        )
        negated_target = re.match(
            r"\s+değil\b", translation[translated_security.end() :], re.IGNORECASE
        )
        if bool(negated_source) != bool(negated_target):
            return False
    if not reason:
        return True
    for target, source in MOTIVE_PAIRS:
        if re.search(target, translation, re.IGNORECASE) and not re.search(
            source, original, re.IGNORECASE
        ):
            return False
    return bool(security_reason or EN_REASON.search(original))


def normalize_translation(original, translation):
    translation = normalize_terms(original, translation)
    # A detached introductory adjunct can be removed without rewriting the action.
    # Leave ambiguous clauses to the retry, including source reasons expressed differently.
    prefix = TR_SECURITY_REASON.match(translation)
    if (
        prefix
        and translation[prefix.end() :].startswith(", ")
        and EN_INSTRUCTION.search(original)
        and not SENTENCE_BREAK.search(original)
        and not re.search(
            r"\b(?:for|to|as|against|without|secur\w*|safe\w*|protect\w*|precaution\w*)\b",
            original,
            re.IGNORECASE,
        )
        and not EN_REASON.search(original)
    ):
        action = translation[prefix.end() + 2 :].lstrip()
        first_word = re.match(r"\w+", action)
        if first_word and first_word[0] not in original:
            action = ("İ" if action[0] == "i" else action[0].upper()) + action[1:]
        if action:
            translation = action
    return translation


def normalize_terms(original, translation):
    # Keep the model's case endings. When both meanings occur, let the glossary retry
    # resolve the context instead of editing a potentially legitimate backup or main server.
    for source, competing, modifier, preferred in (
        (
            r"maintenance updates?",
            r"backups?|back-ups?|back up",
            r"yedekleme(?=\s+güncelleme)",
            "bakım",
        ),
        (r"primary servers?", r"main|master", r"ana(?=\s+sunucu)", "birincil"),
    ):
        if re.search(rf"\b{source}\b", original, re.IGNORECASE) and not re.search(
            rf"\b(?:{competing})\b", original, re.IGNORECASE
        ):
            translation = re.sub(
                rf"\b{modifier}",
                lambda m, word=preferred: (
                    word.capitalize() if m[0][0].isupper() else word
                ),
                translation,
                flags=re.IGNORECASE,
            )
    return translation


def model_text(original, *, explicit_terms=False, literal=False, source_lang="en"):
    if os.getenv("GUNDEM_TRANSLATOR") == "gemma":
        glossary = "\n".join(f"{en} = {tr}" for en, tr, _ in glossary_for(original))
        text = re.sub(r"<(?:start_of_turn|end_of_turn|bos|eos)>", "", original)
        instruction = (
            "Translate the following PostgreSQL text from English into Turkish for a "
            "database administrator. Preserve versions, commands, negations and all "
            "conditions. Use only reasons explicitly given. Reply with only the translation."
        )
        if source_lang != "en":
            instruction = instruction.replace(
                "from English",
                f"from the source language (language code: {source_lang})",
            )
        if glossary:
            instruction += "\nTerminology:\n" + glossary
        if explicit_terms or literal:
            instruction += (
                "\nUse the given Turkish terms with natural inflection. "
                "Translate an imperative as a polite imperative. Translate 'commit' "
                "in its database sense. Never insert a precaution or purpose."
            )
        prompt = (
            "<start_of_turn>user\n"
            + instruction
            + "\n\nText:\n"
            + text
            + "<end_of_turn>\n<start_of_turn>model\n"
        )
        payload = {
            "prompt": prompt,
            "temperature": 0,
            "n_predict": 640,
            "stop": ["<end_of_turn>"],
        }
        req = Request(
            MODEL + "/completion",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=tasks.timeout(MODEL_TIMEOUT)) as response:
            result = json.load(response)
        answer = result["content"].strip()
        if not answer or result.get("stop_type") == "limit" or result.get("truncated"):
            raise ValueError("Eksik çeviri")
        return answer
    if source_lang != "en":
        raise ValueError("Çok dilli çeviri için yerel TranslateGemma modeli gerekiyor")
    if os.getenv("GUNDEM_TRANSLATOR") == "opus":
        req = Request(
            MODEL + "/translate",
            data=json.dumps({"text": original}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=tasks.timeout(MODEL_TIMEOUT)) as result:
            answer = json.load(result)["text"].strip()
        if not answer or (answer == original and len(original.split()) > 4):
            raise ValueError("Eksik çeviri")
        return answer
    messages = [{"role": "system", "content": "en-tr"}]
    if explicit_terms and (terms := glossary_for(original)):
        messages[0]["content"] = (
            "You are an expert at translating text from English to Turkish. "
            "Translate the PostgreSQL text using the following terminology. "
            "Inflect the Turkish terms naturally. Keep identifiers unchanged. "
            "Return only the translation.\n"
            + "\n".join(f"{en} = {tr}" for en, tr, _ in terms)
        )
    if literal:
        # Riva's native translation template accepts paired examples.
        messages.extend(
            [
                {"role": "user", "content": "Restart the service."},
                {"role": "assistant", "content": "Hizmeti yeniden başlatın."},
                {
                    "role": "user",
                    "content": "To reload the configuration, restart the service.",
                },
                {
                    "role": "assistant",
                    "content": "Yapılandırmayı yeniden yüklemek için hizmeti yeniden başlatın.",
                },
            ]
        )
    messages.append({"role": "user", "content": original})
    prompt = {
        "messages": messages,
        "temperature": 0,
        "max_tokens": min(1400, max(120, len(original))),
        "stream": False,
    }
    req = Request(
        MODEL + "/v1/chat/completions",
        data=json.dumps(prompt).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=tasks.timeout(MODEL_TIMEOUT)) as result:
        choice = json.load(result)["choices"][0]
    answer = choice["message"]["content"].strip()
    if (
        not answer
        or choice.get("finish_reason") == "length"
        or (answer == original and len(original.split()) > 4)
    ):
        raise ValueError("Eksik çeviri")
    return answer


TECHNICAL = re.compile(
    r"\b(?:CVE-\d{4}-\d+|\d+\.\d+(?:\.\d+)?|[a-z][a-z\d]+_[a-z\d_]+|PostgreSQL|WAL|VACUUM|REINDEX|REPACK|GiST|GIN|SQL|PL/pgSQL|FDW|pgvector|libpq)\b"
)


def translate(original, *, guided=False):
    upgrade = re.fullmatch(
        r"Upgrade from (\d+(?:\.\d+)+) to (\d+(?:\.\d+)+)\.", original
    )
    if upgrade:
        return f"{upgrade[1]} sürümünden {upgrade[2]} sürümüne yükseltin."
    if len(original) > 1000 or guided:
        pieces = SENTENCE_BREAK.split(original)
        if len(pieces) > 1:
            return " ".join(translate(p, guided=guided) for p in pieces)
    expected = sorted(TECHNICAL.findall(original))
    terms = glossary_for(original)
    try:
        answer = (
            model_text(original, explicit_terms=True, literal=True)
            if guided
            else model_text(original)
        )
        result = normalize_translation(original, answer)
    except ValueError:
        if not terms:
            raise
        result = ""
    identifiers_ok = sorted(TECHNICAL.findall(result)) == expected
    reasons_ok = reasons_supported(original, result)
    if result and identifiers_ok and terms_preserved(terms, result) and reasons_ok:
        return result
    # Retry with placeholders when inflection or paraphrasing altered an identifier.
    replacements = {}

    def mark(match):
        tag = f"[[T{len(replacements)}]]"
        replacements[tag] = match[0]
        return tag

    masked = (
        TECHNICAL.sub(mark, original) if result and not identifiers_ok else original
    )
    if reasons_ok:
        result = model_text(masked, explicit_terms=True)
    else:
        result = model_text(masked, explicit_terms=True, literal=True)
    for tag, value in replacements.items():
        if result.count(tag) != 1:
            raise ValueError("Teknik terim çeviride korunmadı")
        result = result.replace(tag, value)
    result = normalize_translation(original, result)
    if sorted(TECHNICAL.findall(result)) != expected:
        raise ValueError("Çevirideki sürüm veya terim uyuşmuyor")
    if not terms_preserved(terms, result):
        raise ValueError("PostgreSQL terimi sözlükteki karşılığıyla çevrilmedi")
    if not reasons_supported(original, result):
        pieces = SENTENCE_BREAK.split(original)
        if len(pieces) > 1:
            return " ".join(translate(p, guided=guided) for p in pieces)
        raise ValueError("Çevirideki gerekçe kaynak cümleyle uyuşmuyor")
    return result


def press_translation(original, language, *, guided=False):
    language = language.split("-")[0]
    if language == "und":
        try:
            language = detect_langs(original)[0].lang
        except LangDetectException as exc:
            raise ValueError("Kaynak dili belirlenemedi") from exc
    if language == "tr":
        return original
    if language == "en":
        result = translate(original, guided=guided)
        if not safe_instruction(original, result):
            raise ValueError("Talimatın anlamı doğrulanamadı")
    else:
        result = model_text(
            original, source_lang=language, explicit_terms=guided, literal=guided
        )
    # Latin identifiers can directly touch Japanese or Chinese characters.
    tokens = r"(?<![A-Za-z0-9_])(?:CVE-\d{4}-\d+|[0-9]+(?:\.[0-9]+)+|[a-z][a-z0-9]*_[a-z0-9_]+|VACUUM|REINDEX|WAL|SQL|PostgreSQL)(?![A-Za-z0-9_])"
    if re.findall(tokens, original) != re.findall(tokens, result):
        raise ValueError("Çevirideki sürüm veya teknik terim doğrulanamadı")
    if len(original.split()) > 3 and original.casefold() == result.casefold():
        raise ValueError("Türkçe çeviri bekleniyor")
    if len(result) >= 50:
        try:
            guess = detect_langs(result)[0]
        except LangDetectException as exc:
            raise ValueError("Çevirinin dili doğrulanamadı") from exc
        if guess.lang != "tr" and guess.prob > 0.85:
            raise ValueError("Türkçe çıktı doğrulanamadı")
    return result


def priority(item):
    kind = item["kind"]
    base = {"release": 0, "extension": 1, "dev": 2, "security": 3}[kind]
    if item.get("label") == "PostgreSQL ile gelir":
        base = 5
    return (
        base,
        -int((item.get("date") or "0").replace("-", "")),
        -(item.get("score") or 0),
        item["id"],
    )


def pending_count(con):
    originals = {
        s
        for (raw,) in con.execute("SELECT data FROM items")
        for s in text_fields(json.loads(raw))
    }
    done = {
        r[0] for r in con.execute("SELECT original FROM texts WHERE translation <> ''")
    }
    fallback = {
        r[0]
        for r in con.execute(
            "SELECT ref FROM translation_tasks WHERE kind='official' AND status='failed'"
        )
    }
    return len(originals - done - fallback - EDITORIAL.keys())


def safe_instruction(source, target):
    """Protect ordered version numbers and the polarity of operational instructions."""
    versions = r"\b\d+(?:\.\d+)+\b"
    if re.findall(versions, source) != re.findall(versions, target):
        return False
    unaffected = re.search(
        r"\betkilen(?:mez|miyor|memekte|memiş|meyecek|medi|meyen|meyebilir)",
        target,
        re.I,
    )
    if (
        re.search(r"\b(?:not|never|unaffected|unnecessary)\b", source, re.I)
        and not unaffected
    ):
        if not re.search(
            r"değil|gerekmez|gerekmi|[a-zçğıöşü](?:mayın|meyin|mamalı|memeli|maz|mez|miyor|mıyor|muyor|müyor|mamak|memek|mamaktadır|memektedir)",
            target,
            re.I,
        ):
            return False
    if re.search(r"\b(?:unaffected|not affected)\b", source, re.I) and not unaffected:
        return False
    if re.search(r"\bfrom [\d.]+ (?:onward|onwards)\b", source, re.I) and not re.search(
        r"\b(?:ve (?:daha )?sonra|d[âa]hil|itibaren|başlayarak)", target, re.I
    ):
        return False
    if re.search(r"\b(?:is|are) affected\b", source, re.I) and (
        unaffected or re.search(r"etkilenen.*değil", target, re.I)
    ):
        return False
    if re.search(r"\bcommit(?:ted)?\b", source, re.I) and re.search(
        r"taahhü|vaat", target, re.I
    ):
        return False
    if re.search(r"\b(?:run|apply|restart|upgrade)\b", source, re.I) and not re.search(
        r"\b(?:not|never|avoid)\b", source, re.I
    ):
        if re.search(
            r"(?:çalıştır|uygula|başlat|yükselt)(?:mayın|meyin|mamalı|memeli)",
            target,
            re.I,
        ):
            return False
    return True


def translate_round():
    with db() as con:
        items = [json.loads(r[0]) for r in con.execute("SELECT data FROM items")]
        done = {
            r[0]
            for r in con.execute("SELECT original FROM texts WHERE translation<>''")
        } | EDITORIAL.keys()
        ts = int(time.time())
        backlog = []
        for source, due in con.execute(
            "SELECT ref,due FROM translation_tasks WHERE kind='official' ORDER BY due"
        ):
            if due > ts:
                done.add(source)
            else:
                backlog.append(source)
    ordered = sorted(items, key=priority)
    head = []
    for kind in ("release", "security", "dev", "extension"):
        head.extend([i for i in ordered if i["kind"] == kind][:5])
    phrases = dict.fromkeys(s for i in head for s in list(text_fields(i))[:2])
    phrases.update(dict.fromkeys(s for i in ordered for s in text_fields(i)))

    phrases.update(dict.fromkeys(backlog))
    for phrase in phrases:
        if phrase in done:
            continue

        def produce(attempt):
            result = translate(phrase, guided=attempt > 1)
            if not safe_instruction(phrase, result):
                raise ValueError("Sürüm sırası veya talimatın anlamı doğrulanamadı")
            return result

        status = tasks.run(
            db,
            "official",
            phrase,
            0,
            phrase,
            "en",
            produce,
            lambda con, value: con.execute(
                "INSERT OR REPLACE INTO texts VALUES(?,?)", (phrase, value)
            ),
            health=lambda: tasks.available(MODEL),
            seconds=3600,
        )
        if status == "offline" or work.is_set():
            break


def translate_pending():
    while True:
        work.clear()
        try:
            translate_round()
        except Exception:
            logging.exception("Resmî haberlerin çeviri kuyruğu okunamadı")
        work.wait(30)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/bulletin")
def bulletin():
    with db() as con:
        con.execute("BEGIN")
        meta = {r[0]: json.loads(r[1]) for r in con.execute("SELECT * FROM state")}
        sources = {r["name"]: dict(r) for r in con.execute("SELECT * FROM sources")}
        tr = dict(con.execute("SELECT original,translation FROM texts"))
        tr.update(EDITORIAL)
        fallback = {
            r[0]
            for r in con.execute(
                "SELECT ref FROM translation_tasks WHERE kind='official' AND status='failed'"
            )
        }
        items = []
        for row in con.execute("SELECT * FROM items ORDER BY id"):
            item = json.loads(row["data"])
            item.update(seq=row["seq"], observed=row["observed"], source=row["source"])
            item["tr"] = {s: tr[s] for s in text_fields(item) if s in tr}
            item["original_only"] = [s for s in text_fields(item) if s in fallback]
            items.append(item)
    response = jsonify(
        items=items,
        meta=meta,
        sources=[
            dict(
                key=k,
                label=v,
                success=sources.get(k, {}).get("success"),
                error=bool(sources.get(k, {}).get("error")),
            )
            for k, v in SOURCES.items()
        ],
    )
    response.add_etag()
    return response.make_conditional(request)


@app.after_request
def no_stale_alerts(response):
    response.headers["Cache-Control"] = (
        "private, no-store" if request.path.startswith("/api/admin/") else "no-cache"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    return response


register(app, DATA, MODEL, db, pending_count)
community.register(app, db)
news_search.register(app, db, EDITORIAL)


@app.get("/dis-basin")
def press_page():
    return send_from_directory(app.static_folder, "press.html")


def monthly():
    while True:
        instant = datetime.now(timezone.utc)
        month = instant.strftime("%Y-%m")
        if (
            (instant.day > 1 or (instant.hour, instant.minute) >= (3, 15))
            and not (DATA / "arsiv" / f"gundem-{month}.sqlite.gz").exists()
            and not (DATA / "arsiv" / f".tasindi-{month}").exists()
        ):
            try:
                archive(DATA, month)
            except Exception:
                logging.exception("Aylık arşiv alınamadı")
        time.sleep(60)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    initialize()
    workers = [hourly, translate_pending]
    workers.append(lambda: news_search.index(db, EDITORIAL))
    workers.extend(
        [
            lambda: community.weekly(db),
            lambda: community.translations(
                db,
                press_translation,
                retry_translate=lambda source, language: press_translation(
                    source, language, guided=True
                ),
                health=lambda: tasks.available(MODEL),
            ),
        ]
    )
    if os.getenv("GUNDEM_CONTAINER") == "1":
        workers.append(monthly)
    for fn in workers:
        threading.Thread(target=fn, daemon=True).start()
    serve(app, host=os.getenv("GUNDEM_BIND", "127.0.0.1"), port=PORT)
