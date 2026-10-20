"""Small shared helpers: time, hashing, URL canonicalisation, text cleanup."""
from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

UTC = timezone.utc

_now_override: datetime | None = None


def now() -> datetime:
    return _now_override or datetime.now(UTC)


def set_now(dt: datetime | None) -> None:
    """Freeze the clock (tests)."""
    global _now_override
    _now_override = dt


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value) -> datetime | None:
    """Parse ISO8601, RFC822, unix seconds or a feedparser struct_time into an aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    if hasattr(value, "tm_year"):
        return datetime(*value[:6], tzinfo=UTC)
    s = str(value).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def hours_since(value, ref: datetime | None = None) -> float | None:
    dt = parse_time(value)
    if dt is None:
        return None
    return max(0.0, ((ref or now()) - dt).total_seconds() / 3600.0)


def ago(**kw) -> datetime:
    return now() - timedelta(**kw)


def sha(text: str, n: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "ref", "ref_src", "source", "fbclid", "gclid", "mc_cid", "mc_eid", "s", "sh", "si",
    "_hsenc", "_hsmi", "mkt_tok", "cmpid", "taid",
}


def canonical_url(url: str) -> str:
    """Normalise a URL so the same page from different sources dedupes to one key."""
    if not url:
        return ""
    url = url.strip()
    parts = urlsplit(url)
    scheme = "https" if parts.scheme in ("http", "https", "") else parts.scheme
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m.") and host not in ("m.youtube.com",):
        host = host[2:]
    path = re.sub(r"/+", "/", parts.path or "/")
    # arXiv: abs/pdf/html variants and version suffixes are the same paper
    if host in ("arxiv.org", "export.arxiv.org"):
        host = "arxiv.org"
        m = re.match(r"^/(abs|pdf|html)/([0-9]{4}\.[0-9]{4,5})(v\d+)?(\.pdf)?/?$", path)
        if m:
            return f"https://arxiv.org/abs/{m.group(2)}"
    if host == "huggingface.co":
        m = re.match(r"^/papers/([0-9]{4}\.[0-9]{4,5})", path)
        if m:
            return f"https://arxiv.org/abs/{m.group(1)}"
    if host == "github.com":
        segs = [s for s in path.split("/") if s]
        if len(segs) >= 2 and segs[0] not in ("orgs", "topics", "collections", "trending", "sponsors"):
            owner, name = segs[0].lower(), segs[1].lower().removesuffix(".git")
            if len(segs) == 2 or (len(segs) >= 3 and segs[2] in ("tree", "blob") and len(segs) <= 4):
                return f"https://github.com/{owner}/{name}"
            path = "/" + "/".join([owner, name] + segs[2:])
    if host in ("youtube.com", "youtu.be"):
        q = dict(parse_qsl(parts.query))
        vid = q.get("v") or (path.strip("/") if host == "youtu.be" else None)
        if vid:
            return f"https://youtube.com/watch?v={vid}"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
                             if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")))
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    path = re.sub(r"/index\.html?$", "", path) or "/"
    return urlunsplit((scheme, host, path, query, ""))


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(value: str | None, limit: int | None = None) -> str:
    """Strip HTML, decode entities, collapse whitespace."""
    if not value:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", value)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = text.replace(" ", " ")
    lines = [_WS_RE.sub(" ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(ln for ln in lines if ln)
    if limit and len(text) > limit:
        cut = text[:limit]
        sp = cut.rfind(" ")
        text = (cut[:sp] if sp > limit * 0.7 else cut).rstrip(" ,.;:") + "…"
    return text


def first_sentences(text: str, max_chars: int = 280) -> str:
    """A short, purely extractive snippet of the source text."""
    text = clean_text(text).replace("\n", " ")
    if len(text) <= max_chars:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for s in sentences:
        if len(out) + len(s) + 1 > max_chars:
            break
        out = (out + " " + s).strip()
    return out or clean_text(text, max_chars)


def title_tokens(title: str) -> set[str]:
    stop = {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "by", "from",
        "at", "as", "its", "it", "new", "how", "why", "what", "we", "our", "you", "your", "this", "that",
        "show", "hn", "ask", "launch", "introducing", "announcing", "now", "available", "be", "can", "will",
    }
    toks = re.findall(r"[a-z0-9][a-z0-9\.\-\+]*[a-z0-9]|[a-z0-9]", title.lower())
    return {t for t in toks if t not in stop and len(t) > 1}
