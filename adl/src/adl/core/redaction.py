"""
Write-time secret redaction for operator-visible failure text.

An exception's ``str()`` is the richest thing a failed run can record, and
it is also where credentials escape: ``requests`` puts the full request URL
in its ``HTTPError`` text, so a source that authenticates with a query
parameter — several plugins do — turns a 401 into a stored, API-served copy
of its own token.

Redaction happens **at the write point**, not at the serializer. The stored
row is not the only surface: activity logs are rendered in the Wagtail
admin, exported, and echoed into worker logs, and each new reader would
otherwise have to remember to redact. Redacting once, where the text is
produced, bounds the exposure instead of chasing it. The cost is that the
secret is unrecoverable from the row — which is the point; the value of a
credential is never the diagnostic part of the message.

One surface cannot follow that rule: ``django_celery_results`` writes a
failing task's exception text and traceback itself, so core has no write
point to redact at and ``TaskResultSerializer`` redacts on read instead.
That is the exception, and it is named there.

The patterns are deliberately narrow. Only a *named* secret is removed —
a key whose name ends in a sensitive word, or an HTTP authorization scheme
— and the key itself is kept, so the message still says which credential
was involved. Free text that merely looks random is left alone: over-eager
masking destroys the error text operators depend on.
"""

import re

__all__ = [
    "REDACTED",
    "SCHEME_NAMES",
    "SENSITIVE_SUFFIXES",
    "USERINFO_BODY_TEMPLATE",
    "redact_json",
    "redact_secrets",
]

REDACTED = "***"

# A parameter/field name is sensitive when it *ends* in one of these words,
# so ``api_key``, ``x-api-key``, ``client_secret`` and ``ACCESS_TOKEN`` are
# all covered without enumerating every vendor's spelling.
SENSITIVE_SUFFIXES = (
    "tokens?",
    "keys?",
    "secrets?",
    "passwords?",
    "passwd",
    "pwd",
    "credentials?",
    "authorization",
    "auth",
    "signature",
    "sig",
)

# HTTP authorization schemes whose following word is the credential itself.
SCHEME_NAMES = ("Bearer", "Basic", "Token", "Digest")

# Matching on the suffix means an innocent ``sort_key=asc`` is masked too.
# That is the intended bias: a name is only a hint, and losing a sort order
# from an error message costs less than keeping a token in one.
_KEY = r"[A-Za-z0-9_.\-]*(?:" + "|".join(SENSITIVE_SUFFIXES) + r")"

_SCHEMES = r"(?:" + "|".join(SCHEME_NAMES) + r")"

# key <sep> value, where value is a quoted string, a scheme + credential, or
# a bare run of value characters. The bare form stops at the delimiters that
# end a value in a query string, a JSON blob or ordinary prose, and may be
# empty so that ``token=`` is masked rather than left looking untouched.
_KEY_VALUE_RE = re.compile(
    r"(?i)"
    r"\b(?P<key>" + _KEY + r")"
    # A JSON key ("secret": "…") keeps its own closing quote — it is carried
    # through in ``sep`` — while the value's quotes go with the value, so the
    # result reads ``{"secret": ***}``. The output is operator-facing text,
    # not JSON, and is not required to survive a parser.
    r"(?P<sep>[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|" + _SCHEMES + r"\s+\S+|[^\s,;&'\"()<>]*)"
)

# A bare ``Bearer <credential>`` with no key in front of it.
_SCHEME_RE = re.compile(r"(?i)\b(?P<scheme>" + _SCHEMES + r")\s+(?P<token>\S+)")

# scheme://user:password@host — the password is in the URL itself. The user
# half may be empty: ``redis://:password@host:6379/0`` is the canonical form
# of a broker URL for a Redis secured with ``requirepass``, and that URL is
# what a kombu connection error carries into an activity-log message.
#
# Kept as a template because the backfill (monitoring/0010) needs the same
# shape for its SQL pre-filter, where whitespace is spelled ``[:space:]``.
# Deriving both from one source is what stops the sweep from missing what
# this catches — the discipline SENSITIVE_SUFFIXES already imposes on the
# word list, applied to the one branch that had been retyped by hand.
USERINFO_BODY_TEMPLATE = r"://[^/{space}:@]*:[^/{space}@]*@"

_USERINFO_RE = re.compile(
    r"(?i)\b([a-z][a-z0-9+.\-]*)" + USERINFO_BODY_TEMPLATE.format(space=r"\s")
)

# A whole mapping key that names a secret. In parsed data the key and its
# value are already separate, so the value goes whatever it looks like —
# there is no text pattern left to recognise it by.
_SENSITIVE_NAME_RE = re.compile(r"(?i)\A" + _KEY + r"\Z")

_CREDENTIAL_CHARS = set("+/=._~-")


def _looks_like_credential(token):
    """
    Whether the word after an authorization scheme is plausibly a credential.

    "Basic dXNlcjpwYXNz" is; "Basic connection failed" is not. Prose is all
    lower case and short-ish, so anything long enough that mixes case, digits
    or credential punctuation is treated as a secret.
    """
    if len(token) < 8 or token == REDACTED:
        return False
    if any(character.isdigit() or character in _CREDENTIAL_CHARS for character in token):
        return True
    return any(c.islower() for c in token) and any(c.isupper() for c in token)


def _mask_scheme(match):
    token = match.group("token")
    if not _looks_like_credential(token):
        return match.group(0)
    return f"{match.group('scheme')} {REDACTED}"


def redact_secrets(text):
    """
    Return ``text`` with any named credential replaced by ``***``.

    ``None`` passes through unchanged so callers can redact an optional
    message without a guard; anything else is coerced with ``str()``, which
    is what makes ``redact_secrets(exc)`` the natural call at a write point.
    The function is idempotent: redacting already-redacted text is a no-op.
    """
    if text is None:
        return None

    if not isinstance(text, str):
        text = str(text)

    text = _USERINFO_RE.sub(rf"\g<1>://{REDACTED}:{REDACTED}@", text)
    text = _KEY_VALUE_RE.sub(rf"\g<key>\g<sep>{REDACTED}", text)
    text = _SCHEME_RE.sub(_mask_scheme, text)

    return text


def redact_json(value):
    """
    Return parsed JSON with any credential removed, structure intact.

    Two things happen: a mapping key that *names* a secret loses its value
    outright — parsed data has already split key from value, so nothing about
    the value itself would give it away — and every remaining string is run
    through :func:`redact_secrets` for credentials embedded in text.

    Structure is preserved so a caller reading a task result still finds the
    keys it expects, with ``***`` where a secret used to be.
    """
    if isinstance(value, dict):
        return {
            key: REDACTED if _SENSITIVE_NAME_RE.match(str(key)) else redact_json(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [redact_json(item) for item in value]

    if isinstance(value, str):
        return redact_secrets(value)

    return value
