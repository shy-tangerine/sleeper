"""Trust-boundary sanitization for daemon, CLI and MCP-visible data."""
import re
import threading
import base64
import binascii
try:
    from detect_secrets.core.scan import scan_line as _ds_scan_line
    from detect_secrets.settings import default_settings as _ds_default_settings
except ImportError as exc:
    raise RuntimeError("detect-secrets==1.5.0 is required; run `uv sync`") from exc

REDACTED = "[REDACTED]"
_DS_LOCK = threading.Lock()
MAX_STRING_CHARS = 65536
MAX_BYTES = 65536
MAX_IMAGE_DATA_URL_CHARS = 8 * 1024 * 1024
PNG_DATA_URL = re.compile(r"^data:image/png;base64,[A-Za-z0-9+/]+={0,2}$", re.I)

def _is_safe_png_artifact(value):
    """Accept only a complete PNG screenshot, never arbitrary base64 data."""
    if len(value) > MAX_IMAGE_DATA_URL_CHARS or not PNG_DATA_URL.fullmatch(value):
        return False
    try:
        data = base64.b64decode(value.split(",", 1)[1], validate=True)
    except (ValueError, binascii.Error):
        return False
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    offset, saw_ihdr, saw_idat = 8, False, False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset:offset + 4], "big")
        end = offset + 12 + length
        if end > len(data):
            return False
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = int.from_bytes(data[offset + 8 + length:end], "big")
        if binascii.crc32(kind + payload) & 0xffffffff != crc:
            return False
        if kind == b"IHDR":
            if saw_ihdr or length != 13:
                return False
            saw_ihdr = True
        elif kind == b"IDAT":
            saw_idat = True
        elif kind == b"IEND":
            return saw_ihdr and saw_idat and length == 0 and end == len(data)
        elif kind in (b"tEXt", b"zTXt", b"iTXt"):
            return False
        offset = end
    return False
SECRET_KEY = re.compile(r"(?:authorization|bearer|basic|cookie|setcookie|password|passwd|secret|token|apikey|accesskey|privatekey|clientsecret)$", re.I)
URL_SECRET = re.compile(r"([?&#](?:token|key|secret|password|access[_-]?token|api[_-]?key|client[_-]?secret)=)[^&#\s]+", re.I)
SHAPES = re.compile(r"(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk(?:-proj)?-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|-----BEGIN (?P<pem>(?:RSA |EC |OPENSSH )?PRIVATE KEY)-----.*?-----END (?P=pem)-----)", re.S)

_INLINE_SECRET_NAMES = r"(?:x[-_. ]*)?(?:api[-_. ]*key|access[-_. ]*token|client[-_. ]*secret|private[-_. ]*key|set[-_. ]*cookie|cookie|authorization|password|passwd|token|secret)"


def _redact_string(value):
    """Apply every textual redaction rule to one string, in escalation order."""
    out = URL_SECRET.sub(r"\1" + REDACTED, value)
    out = re.sub(r"(?i)\b" + _INLINE_SECRET_NAMES + r"\s*[:=]\s*[^,;\r\n]+", REDACTED, out)
    out = re.sub(r"(?i)\b(?:basic|bearer)\s+[A-Za-z0-9+/=_-]{12,}", REDACTED, out)
    out = re.sub(r"(https?://)([^/@\s]+):([^/@\s]+)@", r"\1" + REDACTED + "@", out, flags=re.I)
    out = re.sub(r"(?im)\b(authorization|cookie|set-cookie|bearer|basic)\s*[:=]\s*(?:[^\r\n,;]+)", r"\1: " + REDACTED, out)
    return SHAPES.sub(REDACTED, out)


def _redact_detected_secrets(out):
    """Run the detect-secrets scan when available; conservative on failure.

    Uncertain detector failures never expose long opaque values at a trust
    boundary: a whitespace-free string of 64+ chars is redacted outright.
    """
    if _ds_scan_line is None or len(out) < 20:
        return out
    try:
        with _DS_LOCK:
            with _ds_default_settings():
                findings = list(_ds_scan_line(out))
        for finding in findings:
            secret = getattr(finding, "secret_value", "")
            if len(secret) >= 20:
                out = out.replace(secret, REDACTED)
        return out
    except Exception:
        if len(out) >= 64 and not re.search(r"\s", out): return REDACTED
        return out


def _clean_dict_key(k):
    """Normalize a mapping key so custom-header spellings match SECRET_KEY."""
    normalized = re.sub(r"[^a-z0-9]", "", str(k).lower())
    if normalized.startswith("x") and normalized[1:] in ("apikey", "accesstoken", "clientsecret", "privatekey"):
        normalized = normalized[1:]
    return normalized


def _redact_mapping(value, _depth, _seen, allow_image_artifacts):
    """Redact one dict: secret-looking keys become REDACTED, values recurse."""
    return {str(k)[:200]: (REDACTED if SECRET_KEY.search(_clean_dict_key(k)) else sanitize(v, _depth+1, _seen, allow_image_artifacts))
            for k, v in list(value.items())[:500]}


def _redact_text_or_image(value, allow_image_artifacts):
    """Redact one string; the only allowed pass-through is a safe image artifact."""
    # Screenshots are an explicit binary artifact channel. Preserve only
    # standard image data URLs within a strict transport bound so their
    # base64 stays decodable through daemon and MCP serialization. Pixels
    # themselves are intentionally not text-redacted; callers must treat a
    # requested screenshot as sensitive page content.
    if value.startswith("data:"):
        if allow_image_artifacts and _is_safe_png_artifact(value):
            return value
        return REDACTED
    out = _redact_string(value)
    out = _redact_detected_secrets(out)
    return out[:MAX_STRING_CHARS] + "…[TRUNCATED]" if len(out) > MAX_STRING_CHARS else out


def sanitize(value, _depth=0, _seen=None, allow_image_artifacts=False):
    """Redact any JSON-like value before it crosses the daemon's trust boundary."""
    if _seen is None: _seen = set()
    if _depth > 8: return REDACTED
    if isinstance(value, bytes):
        return "" if not value else REDACTED
    if isinstance(value, str):
        return _redact_text_or_image(value, allow_image_artifacts)
    if value is None or isinstance(value, (bool, int, float)): return value
    ident = id(value)
    if ident in _seen: return REDACTED
    _seen.add(ident)
    if isinstance(value, dict):
        return _redact_mapping(value, _depth, _seen, allow_image_artifacts)
    if isinstance(value, (list, tuple)): return [sanitize(v, _depth+1, _seen, allow_image_artifacts) for v in value[:500]]
    return sanitize(str(value), _depth+1, _seen)
