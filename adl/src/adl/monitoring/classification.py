"""
Read-time failure classification — the untrusted fallback tier.

The trusted tier stamps activity logs at write time from the exception
*type* (:mod:`adl.core.classification`). This module runs only over rows
that tier did not stamp: ordered, first-match text rules with binary
confidence, recomputed on every read and never written back — so improving
the rule table retroactively corrects every historical row with no data
migration.

Two constraints keep the fallback honest:

- **The layer belongs to the rule, not the category.** Where a plugin
  collapses a connect timeout and a read timeout into one string, the text
  rule claims the category but declines the layer (``None``) — a rule with
  no layer creates no layer-4/5 evidence and stays layer-6 detail.
- **Ambiguity declines.** A message no rule matches yields no
  classification rather than a guess, so the headline never confidently
  names the wrong layer.

Every outcome carries the rule's **normalised** text, never the raw
message — raw exception text can embed credentials and belongs to the
activity log row, not to a headline.
"""

from dataclasses import dataclass
from typing import Optional

from django.utils.translation import gettext_lazy as _

# Normalised, credential-free wording for each category in the closed
# vocabulary — what an evidence slot renders in place of raw exception text
CATEGORY_MESSAGES = {
    "DNS_FAILURE": _("The source host name did not resolve (DNS failure)."),
    "TCP_REFUSED": _("The source host refused a TCP connection."),
    "TCP_TIMEOUT": _("A connection to the source timed out."),
    "TLS_FAILURE": _("TLS negotiation with the source failed."),
    "AUTH_FAILED": _("The source rejected the configured credentials."),
    "PERMISSION_DENIED": _("The source denied permission for the requested "
                           "operation."),
    "PATH_NOT_FOUND": _("The configured remote path was not found on the "
                        "source."),
    "PROTOCOL_ERROR": _("The source replied with an unexpected protocol "
                        "response."),
    "UNKNOWN": _("The run failed with an unclassified connection error."),
}


def category_message(category):
    """The normalised text for a category — used for write-time-stamped
    rows too, so no tier ever surfaces raw message text on a slot."""
    return CATEGORY_MESSAGES[category]


@dataclass(frozen=True)
class ReadTimeRule:
    """One ordered rule: a lowercase needle searched in the raw message.
    ``layer`` is 4 (network path), 5 (source), or ``None`` when the text
    alone cannot place the failure."""

    needle: str
    category: str
    layer: Optional[int]


# Ordered, first-match. Specific needles come before generic ones — a
# message naming both an auth failure and a timeout is claimed by the auth
# rule. These target exception literals owned by sibling repositories and
# the standard library; a reworded upstream message silently stops matching,
# which is exactly why this tier is the fallback and the type-keyed
# write-time tier is the contract.
READ_TIME_RULES = (
    # -- Source (layer 5): the host answered; what it said is the evidence
    ReadTimeRule("login incorrect", "AUTH_FAILED", 5),
    ReadTimeRule("login authentication failed", "AUTH_FAILED", 5),
    ReadTimeRule("authentication failed", "AUTH_FAILED", 5),
    ReadTimeRule("530 login", "AUTH_FAILED", 5),
    ReadTimeRule("password is incorrect", "AUTH_FAILED", 5),
    ReadTimeRule("no such file or directory", "PATH_NOT_FOUND", 5),
    ReadTimeRule("permission denied", "PERMISSION_DENIED", 5),
    # -- Network path (layer 4): the host was never reached
    ReadTimeRule("name or service not known", "DNS_FAILURE", 4),
    ReadTimeRule("nodename nor servname provided", "DNS_FAILURE", 4),
    ReadTimeRule("temporary failure in name resolution", "DNS_FAILURE", 4),
    ReadTimeRule("getaddrinfo failed", "DNS_FAILURE", 4),
    ReadTimeRule("connection refused", "TCP_REFUSED", 4),
    # -- Layer declined: the text alone cannot place these
    # "timed out" covers both a connect timeout (layer 4) and a read
    # timeout (layer 5); "certificate verify failed" both handshake and
    # mid-read TLS faults. The category is claimed, the layer is not.
    ReadTimeRule("certificate verify failed", "TLS_FAILURE", None),
    ReadTimeRule("ssl handshake", "TLS_FAILURE", None),
    ReadTimeRule("timed out", "TCP_TIMEOUT", None),
)


@dataclass(frozen=True)
class ReadTimeClassification:
    """The outcome of one matched rule. ``message`` is the rule's
    normalised text — never the raw message it matched."""

    category: str
    layer: Optional[int]
    message: str


def classify_failure_text(text) -> Optional[ReadTimeClassification]:
    """
    Classify a raw failure message by the ordered rule table.

    Returns ``None`` when no rule matches — a genuinely ambiguous error is
    left unclassified rather than guessed. Callers must apply this only to
    rows with no write-time ``error_category``; a write-time stamp is the
    trusted tier and is never second-guessed here.
    """
    if not text:
        return None
    haystack = text.lower()
    for rule in READ_TIME_RULES:
        if rule.needle in haystack:
            return ReadTimeClassification(
                category=rule.category,
                layer=rule.layer,
                message=category_message(rule.category),
            )
    return None
