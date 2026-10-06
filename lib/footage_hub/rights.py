"""Rights validation for FootageHub assets.

Policy:
  - Every asset keeps its provider-supplied license string verbatim
    (provenance is never rewritten).
  - `classify()` maps that string to a RightsStatus.
  - `validate(asset, require_verified=True)` rejects UNKNOWN/RESTRICTED
    when the production policy requires verified rights. Rejection is a
    per-asset verdict — never an exception, never a pipeline crash.

No AI-generated footage can pass through here: this module has no
generative capability and no fallback path. Missing footage stays missing
(the caller reports a gap), it is never silently replaced.
"""
from __future__ import annotations

from typing import Any


class RightsStatus:
    VERIFIED_PUBLIC_DOMAIN = "verified_public_domain"
    VERIFIED_CC = "verified_cc"
    VERIFIED_LICENSED = "verified_licensed"  # stock grant (Pexels/Pixabay/Mixkit/...)
    UNKNOWN = "unknown"
    RESTRICTED = "restricted"


class RightsMode:
    """Production rights policy selector.

    strict     — verified rights only (public domain / CC / licensed stock).
                 The production default: unverified and restricted assets
                 are rejected.
    permissive — verified + unknown pass; restricted is still rejected.
                 For research cuts and internal review only.
    audit-only — everything passes, but the reason is flagged for human
                 audit. Nothing is silently approved: the flag travels in
                 the manifest row.
    """

    STRICT = "strict"
    PERMISSIVE = "permissive"
    AUDIT_ONLY = "audit-only"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return (cls.STRICT, cls.PERMISSIVE, cls.AUDIT_ONLY)


_VERIFIED_PD_MARKERS = (
    "public domain", "cc0", "cc-0", "prelinger", "u.s. federal",
    "nasa", "loc", "library of congress",
)
_VERIFIED_CC_MARKERS = (
    "cc-by", "cc by", "cc-by-sa", "cc by-sa", "cc-by-nc", "cc by-nc",
)
_VERIFIED_STOCK_MARKERS = (
    "pexels", "pixabay", "mixkit", "coverr", "videvo", "pond5 public domain",
    "unsplash", "dareful",
)
_RESTRICTED_MARKERS = (
    "all rights reserved", "editorial use only", "non-commercial prohibited",
    "no derivatives allowed",
)


def classify(license_str: str) -> str:
    """Map a provider license string to a RightsStatus. Pure function."""
    text = (license_str or "").lower()
    if not text.strip():
        return RightsStatus.UNKNOWN
    if any(m in text for m in _RESTRICTED_MARKERS):
        return RightsStatus.RESTRICTED
    if any(m in text for m in _VERIFIED_PD_MARKERS):
        return RightsStatus.VERIFIED_PUBLIC_DOMAIN
    if any(m in text for m in _VERIFIED_CC_MARKERS):
        return RightsStatus.VERIFIED_CC
    if any(m in text for m in _VERIFIED_STOCK_MARKERS):
        return RightsStatus.VERIFIED_LICENSED
    if "verify" in text:  # e.g. "Wikimedia Commons (verify per-file license)"
        return RightsStatus.UNKNOWN
    return RightsStatus.UNKNOWN


def validate(asset: Any, require_verified: bool = True) -> tuple[bool, str]:
    """Return (ok, reason). Never raises on bad input — returns (False, reason)."""
    try:
        status = getattr(asset, "rights_status", None)
        if status in (None, "", RightsStatus.UNKNOWN):
            status = classify(getattr(asset, "license", "") or "")
    except Exception as exc:
        return False, f"rights validation error: {type(exc).__name__}"
    if status in (RightsStatus.VERIFIED_PUBLIC_DOMAIN, RightsStatus.VERIFIED_CC,
                  RightsStatus.VERIFIED_LICENSED):
        return True, f"verified ({status})"
    if require_verified:
        return False, (
            f"rejected: rights_status={status!r} does not satisfy "
            f"verified-rights production policy (license={getattr(asset, 'license', '')!r})"
        )
    return True, f"allowed under unverified policy ({status})"


def validate_with_mode(asset: Any, mode: str) -> tuple[bool, str]:
    """Rights check under an explicit RightsMode. Fail-closed on bad mode."""
    if mode == RightsMode.STRICT:
        return validate(asset, require_verified=True)
    if mode == RightsMode.PERMISSIVE:
        try:
            status = getattr(asset, "rights_status", None)
            if status in (None, "", RightsStatus.UNKNOWN):
                status = classify(getattr(asset, "license", "") or "")
        except Exception as exc:
            return False, f"rights validation error: {type(exc).__name__}"
        if status == RightsStatus.RESTRICTED:
            return False, (
                f"rejected: rights_status='restricted' is never allowed, "
                f"even permissive (license={getattr(asset, 'license', '')!r})"
            )
        if status == RightsStatus.UNKNOWN:
            return True, "allowed permissive (unverified, research/review only)"
        return True, f"verified ({status})"
    if mode == RightsMode.AUDIT_ONLY:
        try:
            status = getattr(asset, "rights_status", None)
            if status in (None, "", RightsStatus.UNKNOWN):
                status = classify(getattr(asset, "license", "") or "")
        except Exception:
            status = RightsStatus.UNKNOWN
        return True, f"audit-only: human must clear rights_status={status!r}"
    raise ValueError(
        f"unknown rights mode {mode!r}; expected one of {RightsMode.all()}")
