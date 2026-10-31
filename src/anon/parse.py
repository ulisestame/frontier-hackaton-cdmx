"""Parse the raw sources (as laid out by ``anon.sources``) into normalized records.

Values are the REAL ones (nothing is anonymized here). Record shapes follow
api/participante.openapi.yaml:

- chats:  {"id", "thread_id", "author", "ts", "text", "attachments": [{"filename"}]}
          plus private keys prefixed with "_" ("_user", "_channel", "_is_bot",
          "_mentions", "_deleted_user") that must be stripped before writing output
          (see ``public_view``).
- docs:   {"id", "format", "filename", "title", "body", "metadata": {str: str}}
- tables: {"id", "table", "columns": {str: str}}

Every source is reconciled against record_index.json: duplicates and ids the index
does not list are dropped, ids the index lists but the sources lack get a placeholder
record (flagged with "_placeholder"), and each case is reported in ``Corpus.issues``.
"""

from __future__ import annotations

import codecs
import csv
import io
import json
import logging
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .sources import as_list, doc_local_names, safe_name, table_local_names

log = logging.getLogger(__name__)

SOURCES = ("chats", "docs", "tables")
# Whether an HTML <title> also goes into the doc's metadata as "title" (the
# evaluator's expected key set for HTML is not published; flip if it disagrees).
HTML_TITLE_IN_METADATA = False
# Record key per table when the index does not say otherwise.
TABLE_KEYS = {"clientes": "cliente_id", "transacciones": "tx_id", "pqrs": "radicado",
              "empleados": "id"}
# Fallback charset/separator for tables missing from tables/index.json (e.g. sample/).
TABLE_DEFAULTS = {"clientes.csv": ("latin-1", ";"), "transacciones.csv": ("utf-8", ",")}

_MENTION = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]*)?>")


@dataclass
class Corpus:
    chats: list[dict]
    docs: list[dict]
    tables: list[dict]
    users: dict[str, dict]
    channels: list[dict]
    record_index: dict[str, list[str]] | None
    docs_index: list[dict] = field(default_factory=list)
    tables_index: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def corpus_counts(corpus: Corpus) -> dict[str, int]:
    return {"chats": len(corpus.chats), "docs": len(corpus.docs), "tables": len(corpus.tables)}


def public_view(record: dict) -> dict:
    """Copy of a record without the private "_" keys (what goes into output/)."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------- io


def _read_json(path: Path) -> Any:
    return json.loads(path.read_bytes().decode("utf-8-sig"))


def _decode_text(data: bytes, charset: str | None = None) -> str:
    """Decode bytes with the declared charset; sniff UTF-8 vs Latin-1 when unknown."""
    if charset:
        try:
            name = codecs.lookup(charset).name
        except LookupError:
            name = None
        if name in ("latin-1", "iso8859-1") and re.search(rb"[\x80-\x9f]", data):
            name = "cp1252"  # "Latin-1" exports from Windows often are cp1252
        if name:
            try:
                text = data.decode(name)
                return text[1:] if text.startswith("﻿") else text
            except UnicodeDecodeError:
                log.warning("bytes are not valid %s; sniffing the charset", charset)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return data.decode("cp1252")
        except UnicodeDecodeError:
            return data.decode("latin-1")


def _humanize(filename: str) -> str:
    stem = Path(filename).stem
    words = re.sub(r"[_\-]+", " ", stem).strip()
    return words[:1].upper() + words[1:] if words else filename


# ------------------------------------------------------------------------- chats


def _resolve_author(msg: dict, user: dict | None) -> str:
    profile = (user or {}).get("profile") or {}
    for candidate in (
        (user or {}).get("real_name"),
        profile.get("real_name"),
        msg.get("username"),
        (msg.get("bot_profile") or {}).get("name"),
        (user or {}).get("name"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return ""


def _channel_names(chats_dir: Path, channels: list[dict]) -> list[str]:
    names: list[str] = []
    for ch in channels:
        name = ch.get("name") if isinstance(ch, dict) else ch
        if name and str(name) not in names:
            names.append(str(name))
    # Folders on disk that channels.json does not list (defensive).
    on_disk = {safe_name(n) for n in names}
    if chats_dir.is_dir():
        for p in sorted(chats_dir.iterdir()):
            if p.is_dir() and p.name not in on_disk:
                names.append(p.name)
    return names


def _load_chats(raw: Path, users: dict[str, dict], channels: list[dict],
                issues: list[str]) -> list[dict]:
    chats_dir = raw / "chats"
    records: list[dict] = []
    for channel in _channel_names(chats_dir, channels):
        folder = chats_dir / safe_name(channel)
        if not folder.is_dir():
            continue
        for day_file in sorted(folder.glob("*.json")):
            try:
                messages = as_list(_read_json(day_file), "messages")
            except (ValueError, OSError) as exc:
                issues.append(f"chats: cannot read {channel}/{day_file.name}: {exc}")
                continue
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                rec = _chat_record(msg, channel, users)
                if rec is None:
                    issues.append(f"chats: message without client_msg_id in "
                                  f"{channel}/{day_file.name} (ts={msg.get('ts')})")
                    continue
                records.append(rec)
    return records


def _chat_record(msg: dict, channel: str, users: dict[str, dict]) -> dict | None:
    msg_id = msg.get("client_msg_id")
    if not msg_id:
        return None
    uid = msg.get("user") if isinstance(msg.get("user"), str) else None
    user = users.get(uid) if uid else None
    ts = str(msg.get("ts") or "")
    thread_ts = str(msg.get("thread_ts") or ts)
    text = msg.get("text")
    attachments = []
    for f in msg.get("files") or []:
        if isinstance(f, dict):
            attachments.append({"filename": str(f.get("name") or f.get("title") or "")})
    is_bot = bool((user or {}).get("is_bot")) or msg.get("subtype") == "bot_message" \
        or bool(msg.get("bot_id"))
    return {
        "id": str(msg_id),
        "thread_id": f"{channel}:{thread_ts}",
        "author": _resolve_author(msg, user),
        "ts": ts,
        "text": text if isinstance(text, str) else ("" if text is None else str(text)),
        "attachments": attachments,
        "_user": uid,
        "_channel": channel,
        "_is_bot": is_bot,
        "_mentions": _MENTION.findall(text) if isinstance(text, str) else [],
        "_deleted_user": bool((user or {}).get("deleted")),
    }


# -------------------------------------------------------------------------- docs


def _split_front_matter(text: str) -> tuple[list[str] | None, str]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return lines[1:i], "\n".join(lines[i + 1:])
    return None, text


_FM_KEY = re.compile(r"^([^\s#:][^:]*?)\s*:(?:\s+(.*?))?\s*$")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        return inner.replace("''", "'") if value[0] == "'" else inner.replace('\\"', '"')
    return value


def _parse_front_matter(lines: list[str]) -> dict[str, str]:
    """YAML-lite: 'key: value' lines kept as the original strings.

    yaml.safe_load would turn dates into date objects, '2.3' into a float and fail
    on values starting with '@' (handles such as '@andrea.molina').
    """
    meta: dict[str, str] = {}
    key: str | None = None
    block: str | None = None  # '|' or '>' while reading a block scalar
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            if block == "|" and key is not None and meta.get(key):
                meta[key] += "\n"
            continue
        m = _FM_KEY.match(line)
        if m and not line[:1].isspace():
            key, value = m.group(1).strip(), (m.group(2) or "").strip()
            block = value[0] if value in ("|", ">", "|-", ">-", "|+", ">+") else None
            meta[key] = "" if block else _unquote(value)
            continue
        if key is None:
            continue
        item = line.strip()
        if block == "|":
            meta[key] = f"{meta[key]}\n{item}" if meta[key] else item
        elif block == ">":
            meta[key] = f"{meta[key]} {item}" if meta[key] else item
        else:  # list item or folded continuation
            if item.startswith("- "):
                item = item[2:].strip()
            item = _unquote(item)
            meta[key] = f"{meta[key]}, {item}" if meta[key] else item
    return {k: v.rstrip("\n") for k, v in meta.items()}


def _first_heading(markdown: str) -> str:
    for line in markdown.split("\n"):
        m = re.match(r"^#\s+(.+?)\s*#*\s*$", line)
        if m:
            return m.group(1).strip()
    return ""


def _parse_md(data: bytes, filename: str) -> tuple[str, str, dict[str, str]]:
    text = _decode_text(data, "utf-8").replace("\r\n", "\n").replace("\r", "\n")
    fm_lines, rest = _split_front_matter(text)
    metadata = _parse_front_matter(fm_lines) if fm_lines is not None else {}
    title = metadata.get("title") or _first_heading(rest) or _humanize(filename)
    return title, text, metadata


_COMMENT_TOKEN = "KIPUHTMLCOMMENT{:05d}X"


def _parse_html(data: bytes, filename: str) -> tuple[str, str, dict[str, str]]:
    from bs4 import BeautifulSoup, Comment, NavigableString
    from markdownify import MarkdownConverter

    text = _decode_text(data, _html_charset(data)).replace("\r\n", "\n").replace("\r", "\n")
    soup = BeautifulSoup(text, "html.parser")

    metadata: dict[str, str] = {}
    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""
    for meta in soup.find_all("meta"):
        key = meta.get("name") or meta.get("property")
        if not key:
            continue
        value = str(meta.get("content") or "")
        metadata[key] = f"{metadata[key]}, {value}" if key in metadata else value
    if HTML_TITLE_IN_METADATA and title_tag is not None and "title" not in metadata:
        metadata["title"] = title

    # HTML comments hide PII: markdownify drops them, so swap each for a token,
    # convert, then put the original "<!--...-->" back verbatim.
    restore: dict[str, str] = {}
    leading: list[str] = []
    for i, node in enumerate(soup.find_all(string=lambda s: isinstance(s, Comment))):
        original = f"<!--{node}-->"
        if node.find_parent("head") is not None:
            leading.append(original)
            node.extract()
            continue
        token = _COMMENT_TOKEN.format(i)
        restore[token] = original
        node.replace_with(NavigableString(f"\n\n{token}\n\n"))
    for tag in soup.find_all(["head", "title", "style", "script", "noscript", "template"]):
        tag.decompose()

    converter = MarkdownConverter(
        heading_style="ATX", bullets="-", escape_asterisks=False,
        escape_underscores=False, escape_misc=False,
    )
    body = converter.convert_soup(soup)
    lost: list[str] = []
    for token, original in restore.items():
        if token in body:
            body = body.replace(token, original)
        else:
            lost.append(original)
    body = _tidy_markdown("\n\n".join([*leading, body, *lost]))
    if not title:
        title = _first_heading(body) or _humanize(filename)
    return title, body, metadata


def _html_charset(data: bytes) -> str | None:
    m = re.search(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9_\-]+)", data[:4096], re.I)
    return m.group(1).decode("ascii") if m else "utf-8"


def _tidy_markdown(text: str) -> str:
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


# --------------------------------------------------------------------------- pdf


def _parse_pdf(data: bytes, filename: str) -> tuple[str, str, dict[str, str]]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    metadata: dict[str, str] = {}
    try:
        info = reader.metadata or {}
    except Exception as exc:  # broken info dictionary: keep going with the text
        log.warning("%s: unreadable PDF metadata: %s", filename, exc)
        info = {}
    for key, value in info.items():
        name = str(key).lstrip("/").lower()
        if not name:
            continue
        try:
            value = value.get_object() if hasattr(value, "get_object") else value
        except Exception:
            pass
        metadata[name] = "" if value is None else str(value)
    body = _pdf_body(reader, filename)
    title = metadata.get("title", "").strip()
    if not title:
        first = next((ln for ln in body.split("\n") if ln.strip()), "")
        title = first.lstrip("#").strip() or _humanize(filename)
    return title, body, metadata


def _pdf_body(reader, filename: str) -> str:
    """Text of every page as markdown, pages joined with a blank line.

    pypdf's plain extraction glues runs that wrap inside a table cell
    ("menos" + "efectivo" -> "menosefectivo"). Here each run keeps its position:
    cells come from the stroked rectangles ("re" operators) and become pipe tables,
    bigger fonts become headings and wrapped lines of a paragraph are re-joined.
    Pages the layout pass cannot handle fall back to pypdf's plain text.
    """
    pages: list[dict] = []
    for page in reader.pages:
        entry: dict = {"page": page, "tables": None, "lines": None}
        try:
            frags, rects = _pdf_runs(page)
            if frags:
                entry["tables"] = _pdf_tables(rects, frags)
                in_table = {id(f) for t in entry["tables"] for row in t["rows"]
                            for cell in row for f in cell}
                entry["lines"] = _pdf_lines([f for f in frags if id(f) not in in_table])
        except Exception as exc:
            log.debug("%s: layout extraction failed (%s); using plain text", filename, exc)
            entry["tables"] = entry["lines"] = None
        pages.append(entry)

    # Document-wide typography: body size, heading levels, full line width.
    weights: Counter = Counter()
    for entry in pages:
        for ln in entry["lines"] or []:
            weights[ln["size"]] += len(ln["text"])
    body_size = weights.most_common(1)[0][0] if weights else 0.0
    bigger = sorted({s for s in weights if s > body_size + 0.5}, reverse=True)
    level = {s: min(i + 1, 3) for i, s in enumerate(bigger)}
    widest = max((len(ln["text"]) for e in pages for ln in e["lines"] or []
                  if ln["size"] == body_size), default=1)

    texts = []
    for entry in pages:
        text = ""
        if entry["lines"] is not None:
            blocks = [(t["top"], _render_table(t["rows"])) for t in entry["tables"]]
            blocks += _pdf_paragraphs(entry["lines"], level, widest)
            blocks.sort(key=lambda b: -b[0])
            text = "\n\n".join(b for _, b in blocks if b.strip())
        if not text.strip():
            try:
                text = entry["page"].extract_text() or ""
            except Exception as exc:
                log.warning("%s: cannot extract a page: %s", filename, exc)
                text = ""
        if text.strip():
            texts.append(text.strip())
    return "\n\n".join(texts) + "\n" if texts else ""


def _pdf_runs(page) -> tuple[list[dict], list[tuple[float, float, float, float]]]:
    """Positioned text runs and stroked rectangles of a page."""
    frags: list[dict] = []
    rects: list[tuple[float, float, float, float]] = []

    def mult(m, n):  # affine product, pypdf order [a b c d e f]
        return [m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3],
                m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3],
                m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5]]

    def on_op(op, args, cm, tm):
        if op == b"re" and len(args) == 4:
            x, y, w, h = (float(a) for a in args)
            xs = (cm[0] * x + cm[2] * y + cm[4], cm[0] * (x + w) + cm[2] * (y + h) + cm[4])
            ys = (cm[1] * x + cm[3] * y + cm[5], cm[1] * (x + w) + cm[3] * (y + h) + cm[5])
            rects.append((min(xs), min(ys), max(xs), max(ys)))

    def on_text(text, cm, tm, font, size):
        if not text or not text.strip():
            return
        m = mult(tm, cm)
        scale = (m[2] ** 2 + m[3] ** 2) ** 0.5 or 1.0
        base = str(font.get("/BaseFont", "")) if hasattr(font, "get") else ""
        for piece in text.split("\n"):
            if piece.strip():
                frags.append({"x": m[4], "y": m[5], "text": piece.strip(),
                              "size": round(float(size or 0) * scale, 1),
                              "bold": "bold" in base.lower()})

    page.extract_text(visitor_operand_before=on_op, visitor_text=on_text)
    return frags, rects


def _pdf_tables(rects, frags) -> list[dict]:
    """Group stroked rectangles into rows/tables and drop each text run into its cell."""
    cells = [r for r in rects if (r[2] - r[0]) > 2 and (r[3] - r[1]) > 2]
    rows: dict[tuple[float, float], list] = defaultdict(list)
    for r in cells:
        rows[(round(r[1]), round(r[3]))].append(r)
    row_list = []
    for (y0, y1), rs in rows.items():
        rs.sort(key=lambda r: r[0])
        adjacent = all(abs(rs[i][2] - rs[i + 1][0]) < 2.5 for i in range(len(rs) - 1))
        if len(rs) >= 2 and adjacent:
            row_list.append({"y0": y0, "y1": y1, "rects": rs})
    row_list.sort(key=lambda r: -r["y1"])

    tables: list[dict] = []
    for row in row_list:
        last = tables[-1] if tables else None
        if (last and abs(last["bottom"] - row["y1"]) < 2.5
                and len(last["rows_r"][-1]["rects"]) == len(row["rects"])):
            last["rows_r"].append(row)
            last["bottom"] = row["y0"]
        else:
            tables.append({"top": row["y1"], "bottom": row["y0"], "rows_r": [row]})

    for t in tables:
        t["rows"] = [[[] for _ in r["rects"]] for r in t["rows_r"]]
    for f in frags:
        placed = False
        for t in tables:
            if not (t["bottom"] - 1 <= f["y"] <= t["top"] + 1):
                continue
            for ri, r in enumerate(t["rows_r"]):
                for ci, (x0, y0, x1, y1) in enumerate(r["rects"]):
                    if x0 - 1 <= f["x"] <= x1 + 1 and y0 - 1 <= f["y"] <= y1 + 1:
                        t["rows"][ri][ci].append(f)
                        placed = True
                        break
                if placed:
                    break
            if placed:
                break
    return [t for t in tables if any(cell for row in t["rows"] for cell in row)]


def _render_table(rows: list[list[list[dict]]]) -> str:
    def cell_text(cell):
        cell = sorted(cell, key=lambda f: (-round(f["y"]), f["x"]))
        return " ".join(f["text"] for f in cell).replace("|", "\\|")

    lines = []
    for i, row in enumerate(rows):
        lines.append("| " + " | ".join(cell_text(c) for c in row) + " |")
        if i == 0:
            lines.append("| " + " | ".join("---" for _ in row) + " |")
    return "\n".join(lines)


def _pdf_lines(frags: list[dict]) -> list[dict]:
    lines: list[dict] = []
    for f in sorted(frags, key=lambda f: (-f["y"], f["x"])):
        if lines and abs(lines[-1]["y"] - f["y"]) <= 2.0:
            lines[-1]["frags"].append(f)
        else:
            lines.append({"y": f["y"], "frags": [f]})
    for ln in lines:
        ln["frags"].sort(key=lambda f: f["x"])
        ln["text"] = " ".join(f["text"] for f in ln["frags"])
        ln["size"] = max(f["size"] for f in ln["frags"])
        ln["x"] = ln["frags"][0]["x"]
    return lines


_LIST_ITEM = re.compile(r"^(?:[-*•–]\s|\d{1,2}[.)]\s)")  # not "2026. ..." (a year)


def _pdf_paragraphs(lines: list[dict], level: dict[float, int],
                    widest: int) -> list[tuple[float, str]]:
    """Lines -> paragraphs: headings by font size, wrapped lines re-joined with a space."""
    blocks: list[tuple[float, str]] = []
    para: list[dict] = []

    def flush():
        if para:
            out = para[0]["text"]
            for prev, cur in zip(para, para[1:], strict=False):
                wrapped = (len(prev["text"]) >= 0.75 * widest
                           and not _LIST_ITEM.match(cur["text"]))
                out += (" " if wrapped else "\n") + cur["text"]
            blocks.append((para[0]["y"], out))
            para.clear()

    for ln in lines:
        if ln["size"] in level:
            flush()
            blocks.append((ln["y"], "#" * level[ln["size"]] + " " + ln["text"]))
            continue
        if para:
            prev = para[-1]
            gap = prev["y"] - ln["y"]
            if (gap > 1.75 * max(ln["size"], 1.0) or ln["size"] != prev["size"]
                    or abs(ln["x"] - para[0]["x"]) > 30):
                flush()
        para.append(ln)
    flush()
    return blocks


def _load_docs(raw: Path, issues: list[str]) -> tuple[list[dict], list[dict]]:
    docs_dir = raw / "docs"
    index_path = docs_dir / "index.json"
    if index_path.exists():
        index = as_list(_read_json(index_path), "docs", "documents")
    else:  # no index: one doc per file, id = file stem
        index = [{"id": p.stem, "filename": p.name, "format": p.suffix.lstrip(".").lower()}
                 for p in sorted(docs_dir.glob("*")) if p.is_file() and p.name != "README.txt"]
        if index:
            issues.append("docs: no index.json; ids taken from file names")
    local = doc_local_names(index)
    records = []
    for entry in index:
        if not isinstance(entry, dict) or entry.get("id") is None:
            continue
        doc_id = str(entry["id"])
        filename = str(entry.get("filename") or doc_id)
        fmt = str(entry.get("format") or Path(filename).suffix.lstrip(".")).lower()
        fmt = {"markdown": "md", "htm": "html"}.get(fmt, fmt)
        path = docs_dir / local.get(doc_id, safe_name(filename))
        rec = {"id": doc_id, "format": fmt, "filename": filename,
               "title": "", "body": "", "metadata": {}}
        try:
            data = path.read_bytes()
            parser = {"md": _parse_md, "html": _parse_html, "pdf": _parse_pdf}.get(fmt)
            if parser is None:
                parser = _parse_pdf if data[:5] == b"%PDF-" else _parse_md
                issues.append(f"docs: {doc_id} has unknown format {fmt!r}; parsed as text")
            rec["title"], rec["body"], rec["metadata"] = parser(data, filename)
        except Exception as exc:  # keep the record: an empty doc beats a missing id
            issues.append(f"docs: cannot parse {doc_id} ({filename}): "
                          f"{type(exc).__name__}: {exc}")
            rec["title"] = _humanize(filename)
            rec["_parse_error"] = f"{type(exc).__name__}: {exc}"
        rec["metadata"] = {str(k): "" if v is None else str(v)
                           for k, v in rec["metadata"].items()}
        records.append(rec)
    return records, index


# ------------------------------------------------------------------------ tables


def _table_meta(raw: Path) -> tuple[list[dict], dict[str, dict]]:
    tables_dir = raw / "tables"
    index_path = tables_dir / "index.json"
    entries: list[dict] = []
    if index_path.exists():
        for e in as_list(_read_json(index_path), "tables"):
            entries.append(e if isinstance(e, dict) else {"name": str(e)})
    known = {str(e.get("name")) for e in entries}
    if tables_dir.is_dir():  # files the index does not list (e.g. the sample)
        for p in sorted(tables_dir.iterdir()):
            if p.suffix.lower() in (".csv", ".xml") and p.name not in known:
                entries.append({"name": p.name, "format": p.suffix.lstrip(".").lower()})
    return entries, {str(e.get("name")): e for e in entries}


def _load_tables(raw: Path, issues: list[str]) -> tuple[list[dict], list[dict]]:
    tables_dir = raw / "tables"
    entries, _ = _table_meta(raw)
    local = table_local_names(entries)
    records: list[dict] = []
    for entry in entries:
        name = str(entry.get("name"))
        path = tables_dir / local.get(name, safe_name(name))
        if not path.exists():
            issues.append(f"tables: {name} listed in index.json but missing on disk")
            continue
        table = Path(name).stem
        fmt = str(entry.get("format") or Path(name).suffix.lstrip(".")).lower()
        try:
            data = path.read_bytes()
            if fmt == "xml":
                rows = _xml_rows(data, table, issues)
            else:
                charset, sep = TABLE_DEFAULTS.get(name, (None, None))
                rows = _csv_rows(data, entry.get("charset") or charset,
                                 entry.get("separator") or sep, table, issues)
        except Exception as exc:
            issues.append(f"tables: cannot parse {name}: {type(exc).__name__}: {exc}")
            continue
        declared = entry.get("rows")
        if isinstance(declared, int) and declared != len(rows):
            issues.append(f"tables: {name} has {len(rows)} rows, index.json says {declared}")
        records.extend(rows)
    return records, entries


def _csv_rows(data: bytes, charset: str | None, sep: str | None, table: str,
              issues: list[str]) -> list[dict]:
    text = _decode_text(data, charset)
    if not sep:
        head = text.split("\n", 1)[0]
        sep = max((";", ",", "\t", "|"), key=head.count)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=sep, quotechar='"')
    rows = [r for r in reader if r and any(c.strip() for c in r)]
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    key_col = TABLE_KEYS.get(table) if TABLE_KEYS.get(table) in header else header[0]
    out = []
    for n, row in enumerate(rows[1:], start=2):
        if len(row) > len(header):  # unquoted separator inside the last field
            issues.append(f"tables: {table} line {n} has {len(row)} fields; extra merged")
            row = row[: len(header) - 1] + [sep.join(row[len(header) - 1:])]
        row = row + [""] * (len(header) - len(row))
        columns = dict(zip(header, row, strict=False))
        out.append({"id": f"{table}:{columns[key_col]}", "table": table, "columns": columns})
    return out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else str(tag)


def _xml_text(el: ET.Element) -> str:
    text = "".join(el.itertext())
    # Strip only pretty-print indentation; CDATA and inline text stay as written.
    return re.sub(r"^\s*\n\s*|\s*\n\s*$", "", text)


def _xml_rows(data: bytes, table: str, issues: list[str]) -> list[dict]:
    if re.search(rb"<!ENTITY", data[:65536]):
        raise ValueError("XML with entity declarations refused")
    root = ET.fromstring(data)
    out = []
    for el in root:
        if not isinstance(el.tag, str):
            continue
        columns: dict[str, str] = {}
        for k, v in el.attrib.items():
            columns[_local(k)] = v
        for child in el:
            if not isinstance(child.tag, str):
                continue
            name = _local(child.tag)
            col, n = name, 2
            while col in columns:  # repeated child element
                col, n = f"{name}_{n}", n + 1
            columns[col] = _xml_text(child)
            for k, v in child.attrib.items():
                columns[f"{col}_{_local(k)}"] = v
        key_attr = TABLE_KEYS.get(table)
        if key_attr not in el.attrib:
            key_attr = next(iter(el.attrib), None)
        if key_attr is None:
            issues.append(f"tables: {table} row <{_local(el.tag)}> without a key attribute")
            continue
        out.append({"id": f"{table}:{el.attrib[key_attr]}", "table": table,
                    "columns": columns})
    return out


# ----------------------------------------------------------------------- corpus


def _placeholder(source: str, rid: str) -> dict:
    if source == "chats":
        return {"id": rid, "thread_id": "", "author": "", "ts": "", "text": "",
                "attachments": [], "_user": None, "_channel": "", "_is_bot": False,
                "_mentions": [], "_deleted_user": False, "_placeholder": True}
    if source == "docs":
        return {"id": rid, "format": "", "filename": "", "title": "", "body": "",
                "metadata": {}, "_placeholder": True}
    return {"id": rid, "table": rid.split(":", 1)[0], "columns": {}, "_placeholder": True}


def _reconcile(source: str, records: list[dict], index_ids: list[str] | None,
               issues: list[str]) -> list[dict]:
    seen: dict[str, dict] = {}
    for rec in records:
        if rec["id"] in seen:
            issues.append(f"{source}: duplicate id {rec['id']} (kept the first)")
            continue
        seen[rec["id"]] = rec
    if index_ids is None:
        return list(seen.values())
    wanted = list(dict.fromkeys(str(i) for i in index_ids))
    wanted_set = set(wanted)
    extra = [rid for rid in seen if rid not in wanted_set]
    if extra:
        issues.append(f"{source}: {len(extra)} ids not in record_index dropped, "
                      f"e.g. {extra[:3]}")
    out = [rec for rid, rec in seen.items() if rid in wanted_set]
    missing = [rid for rid in wanted if rid not in seen]
    if missing:
        issues.append(f"{source}: {len(missing)} ids in record_index missing from the "
                      f"sources (placeholders emitted), e.g. {missing[:3]}")
        out.extend(_placeholder(source, rid) for rid in missing)
    return out


def _find_record_index(raw: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return Path(explicit)
    for candidate in (raw / "record_index.json", raw.parent / "record_index.json"):
        if candidate.exists():
            return candidate
    return None


def load_corpus(raw_dir: Path, record_index_path: Path | None = None) -> Corpus:
    """Parse everything under raw_dir (layout of anon.sources.fetch_all).

    record_index.json is looked up in raw_dir, then in its parent (sample/ keeps it
    next to input/). Without one, records are returned unreconciled.
    """
    raw = Path(raw_dir)
    issues: list[str] = []
    ri_path = _find_record_index(raw, record_index_path)
    record_index = None
    if ri_path is not None and ri_path.exists():
        payload = _read_json(ri_path)
        record_index = {s: [str(x) for x in payload.get(s, [])] for s in SOURCES} \
            if isinstance(payload, dict) else None
    else:
        issues.append("record_index.json not found; records not reconciled")

    users_path, channels_path = raw / "chats" / "users.json", raw / "chats" / "channels.json"
    users_list = as_list(_read_json(users_path), "members", "users") if users_path.exists() else []
    users = {str(u["id"]): u for u in users_list if isinstance(u, dict) and u.get("id")}
    channels = as_list(_read_json(channels_path), "channels") if channels_path.exists() else []
    channels = [c for c in channels if isinstance(c, dict)]

    chats = _load_chats(raw, users, channels, issues)
    docs, docs_index = _load_docs(raw, issues) if (raw / "docs").is_dir() else ([], [])
    tables, tables_index = _load_tables(raw, issues) if (raw / "tables").is_dir() else ([], [])

    ri = record_index or {}
    corpus = Corpus(
        chats=_reconcile("chats", chats, ri.get("chats") if record_index else None, issues),
        docs=_reconcile("docs", docs, ri.get("docs") if record_index else None, issues),
        tables=_reconcile("tables", tables, ri.get("tables") if record_index else None, issues),
        users=users,
        channels=channels,
        record_index=record_index,
        docs_index=docs_index,
        tables_index=tables_index,
        issues=issues,
    )
    for issue in issues:
        log.warning("parse: %s", issue)
    return corpus
