"""
Redact credentials already stored in operator-visible failure text.

The forward fix (``adl.core.redaction``) only covers rows written from now
on. Rows written before it — a 401 from a source that authenticates with a
query parameter, say — still carry the token in ``message``, and the
monitoring API still serves it. This sweeps them.

Irreversible on purpose: the reverse is a no-op because the secret is gone,
which is the whole point. Only rows the redactor actually changes are
written back, so an install with no leaked rows pays one scan and no
updates.

Runs outside a transaction and writes one row at a time. The activity log
is a TimescaleDB hypertable: an update that names only the primary key
cannot exclude a chunk, so each write carries the row's ``time`` as well and
touches one chunk instead of all of them. Installs that have enabled
compression on old chunks must decompress them before migrating — Timescale
refuses updates to a compressed chunk, and that is a deployment decision,
not something a migration should make silently.
"""

from django.db import migrations

from adl.core.redaction import SCHEME_NAMES, SENSITIVE_SUFFIXES

BATCH_SIZE = 1000

# Cheap SQL pre-filter: any row whose text mentions a credential-ish word at
# all. Built from the redactor's own vocabulary — retyping the word list here
# is how the backfill would come to miss what the forward fix catches. The
# redactor still decides whether anything is really there; this only keeps
# the sweep from loading every log row ever written.
#
# ``tokens?`` is the redactor's spelling of an optional plural, which POSIX
# does not read the same way. The optional character is dropped and a
# trailing ``[a-z]*`` put back instead, so the pre-filter still catches
# ``tokens=`` — and over-matches, which costs a pre-filter nothing.
_WORDS = "|".join(
    suffix[:-2] if suffix.endswith("?") else suffix for suffix in SENSITIVE_SUFFIXES
)
_SCHEMES = "|".join(SCHEME_NAMES)

CANDIDATE_REGEX = (
    rf"({_WORDS})[a-z]*[[:space:]]*[\"']?[[:space:]]*[:=]"
    r"|://[^/@[:space:]]+:[^/@[:space:]]*@"
    rf"|({_SCHEMES})[[:space:]]"
)


def _redact_model(model, field, redact, keys):
    candidates = (
        model.objects.filter(**{f"{field}__iregex": CANDIDATE_REGEX})
        .only(*keys, field)
        .order_by("pk")
    )

    for row in candidates.iterator(chunk_size=BATCH_SIZE):
        original = getattr(row, field)
        redacted = redact(original)
        if redacted == original:
            continue
        lookup = {key: getattr(row, key) for key in keys}
        model.objects.filter(**lookup).update(**{field: redacted})


def redact_stored_secrets(apps, schema_editor):
    from adl.core.redaction import redact_secrets

    # The activity log is partitioned on ``time``; carrying it in the lookup
    # is what lets Timescale touch a single chunk per write.
    sweeps = (
        ("StationLinkActivityLog", "message", ("pk", "time")),
        ("SourceProbeResult", "message", ("pk",)),
        ("NetworkConnectionHealth", "headline_message", ("pk",)),
    )

    for model_name, field, keys in sweeps:
        _redact_model(
            apps.get_model("monitoring", model_name), field, redact_secrets, keys
        )


class Migration(migrations.Migration):
    # A data sweep over the whole activity-log history has no business
    # holding one transaction open across every chunk it rewrites.
    atomic = False

    dependencies = [
        ("monitoring", "0009_sourceproberesult"),
    ]

    operations = [
        migrations.RunPython(redact_stored_secrets, migrations.RunPython.noop),
    ]
