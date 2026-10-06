"""FootageHub tests — success + failure fixtures, all offline.

Covers: normalized contract fields, rights matrix + verified-policy
rejection, registry capabilities (8 factory providers, none mandatory),
provider-failure isolation, deterministic ranking, checksum dedupe,
vault provenance manifest, no-AI-substitution guarantee, tool wrapper ops.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures" / "footage_hub"


def _load(name: str):
    with open(FIX / name, encoding="utf-8") as f:
        return json.load(f)


# -- normalized contract -------------------------------------------------

def test_contract_has_all_required_fields():
    from lib.footage_hub.contracts import NormalizedAsset

    asset = NormalizedAsset(provider="nasa", source_id="1", title="t",
                            source_url="s", download_url="d")
    d = asset.to_dict()
    for f in NormalizedAsset.required_fields():
        assert f in d, f
    assert asset.asset_id == "nasa_1"
    assert NormalizedAsset.from_dict(d).asset_id == "nasa_1"
    assert asset.media_type == "video"  # kind alias
    assert asset.orientation == "unknown"  # zero dims
    wide = NormalizedAsset(provider="p", source_id="1", kind="image",
                           width=1920, height=1080)
    assert wide.orientation == "landscape" and wide.media_type == "image"
    tall = NormalizedAsset(provider="p", source_id="2", width=1080, height=1920)
    assert tall.orientation == "portrait"
    sq = NormalizedAsset(provider="p", source_id="3", width=512, height=512)
    assert sq.orientation == "square"


# -- rights ---------------------------------------------------------------

def test_rights_matrix_from_fixture():
    from lib.footage_hub.rights import classify

    for row in _load("rights_matrix.json")["licenses"]:
        assert classify(row["license"]) == row["expect"], row


def test_verified_policy_rejects_unknown_rights():
    from lib.footage_hub.contracts import NormalizedAsset
    from lib.footage_hub.rights import validate

    unknown = NormalizedAsset(provider="x", source_id="1", license="")
    ok, reason = validate(unknown, require_verified=True)
    assert ok is False and "rejected" in reason
    ok2, _ = validate(unknown, require_verified=False)
    assert ok2 is True  # unverified policy still explicit, never silent
    pd = NormalizedAsset(provider="nasa", source_id="1",
                         license="Public domain (U.S. federal government work)")
    assert validate(pd, require_verified=True)[0] is True


def test_rights_modes_matrix():
    from lib.footage_hub.contracts import NormalizedAsset
    from lib.footage_hub.rights import RightsMode, validate_with_mode

    assert sorted(RightsMode.all()) == ["audit-only", "permissive", "strict"]
    verified = NormalizedAsset(provider="nasa", source_id="1",
                               license="Public domain (U.S. federal work)")
    unknown = NormalizedAsset(provider="x", source_id="2", license="")
    restricted = NormalizedAsset(provider="y", source_id="3",
                                 license="All rights reserved")
    assert validate_with_mode(verified, "strict")[0] is True
    assert validate_with_mode(unknown, "strict")[0] is False
    assert validate_with_mode(restricted, "strict")[0] is False
    assert validate_with_mode(verified, "permissive")[0] is True
    assert validate_with_mode(unknown, "permissive")[0] is True
    assert validate_with_mode(restricted, "permissive")[0] is False
    ok, reason = validate_with_mode(restricted, "audit-only")
    assert ok is True and "audit" in reason  # flagged, never silent
    with pytest.raises(ValueError):
        validate_with_mode(verified, "yolo")


def test_strict_is_the_default_search_policy(monkeypatch):
    from lib.footage_hub import hub as fh
    from tools.video.stock_sources.base import Candidate

    class _Mixed:
        name = "mixed"
        def is_available(self): return True
        def search(self, q, f):
            return [Candidate(source="mixed", source_id="1", source_url="s",
                              download_url="http://x/1.mp4", kind="video",
                              width=640, height=480, license="CC0 1.0",
                              source_tags="river"),
                    Candidate(source="mixed", source_id="2", source_url="s",
                              download_url="http://x/2.mp4", kind="video",
                              width=640, height=480, license="",
                              source_tags="river")]
        def download(self, c, p): raise AssertionError("unreachable")

    monkeypatch.setattr("tools.video.stock_sources.all_sources",
                        lambda: [_Mixed()])
    strict = fh.search("river", kind="video")
    assert [a.source_id for a in strict.assets] == ["1"]  # unknown filtered
    permissive = fh.search("river", kind="video", rights_mode="permissive")
    assert {a.source_id for a in permissive.assets} == {"1", "2"}
    audit = fh.search("river", kind="video", rights_mode="audit-only")
    assert {a.source_id for a in audit.assets} == {"1", "2"}


# -- adapters (fixture-driven, no network) ---------------------------------

def _fake_response(payload):
    class R:
        def raise_for_status(self): pass
        def json(self): return payload
    return R()


def test_openverse_parses_fixture(monkeypatch):
    import tools.video.stock_sources.openverse as ov
    from tools.video.stock_sources.base import SearchFilters

    payload = _load("openverse_images.json")
    monkeypatch.setattr("requests.get", lambda *a, **k: _fake_response(payload))
    cands = ov.OpenverseSource().search("river", SearchFilters(kind="image"))
    assert len(cands) == 2
    assert cands[0].source == "openverse" and cands[0].kind == "image"
    assert "CC-BY" in cands[0].license
    assert cands[0].clip_id == "openverse_ov-img-001"
    assert ov.OpenverseSource().search("river", SearchFilters(kind="video")) == []
    assert ov.OpenverseSource().is_available() is True  # free, no key


def test_dvids_parses_fixture_and_gates_on_key(monkeypatch, tmp_path):
    import os
    import tools.video.stock_sources.dvids as dv
    from tools.video.stock_sources.base import SearchFilters

    os.environ.pop("DVIDS_API_KEY", None)
    assert dv.DvidsSource().is_available() is False  # never mandatory
    monkeypatch.setenv("DVIDS_API_KEY", "test-key")
    assert dv.DvidsSource().is_available() is True
    payload = _load("dvids_search.json")
    monkeypatch.setattr("requests.get", lambda *a, **k: _fake_response(payload))
    cands = dv.DvidsSource().search("river", SearchFilters(kind="any"))
    assert len(cands) == 2
    assert cands[0].kind == "video" and cands[1].kind == "image"
    assert "Public domain" in cands[0].license


# -- registry ---------------------------------------------------------------

def test_registry_reports_factory_providers_and_capabilities():
    from lib.footage_hub.registry import FACTORY_PROVIDERS, capabilities

    caps = {c.name: c for c in capabilities()}
    for name in FACTORY_PROVIDERS:
        assert name in caps, f"missing provider: {name}"
    assert caps["openverse"].supports_image and not caps["openverse"].supports_video
    # no provider is mandatory: availability is reported, never enforced here
    assert all(hasattr(c, "available") for c in caps.values())


# -- hub: failure isolation + deterministic ranking ---------------------------

class _Flaky:
    name = "flaky_a"
    def is_available(self): return True
    def search(self, q, f): raise ConnectionError("dns failure")
    def download(self, c, p): raise AssertionError("unreachable")


class _Good:
    name = "good_b"
    def is_available(self): return True
    def search(self, q, f):
        from tools.video.stock_sources.base import Candidate
        return [Candidate(source="good_b", source_id="2", source_url="s",
                          download_url="http://x/2.mp4", kind="video",
                          width=640, height=480, creator="c",
                          license="CC0 1.0", source_tags="river dawn")]
    def download(self, c, p): raise AssertionError("unreachable")


def test_provider_failure_does_not_crash_pipeline(monkeypatch):
    from lib.footage_hub import hub as fh

    monkeypatch.setattr("tools.video.stock_sources.all_sources",
                        lambda: [_Flaky(), _Good()])
    res = fh.search("river", kind="video")
    assert len(res.assets) == 1 and res.assets[0].provider == "good_b"
    assert len(res.failures) == 1 and res.failures[0].provider == "flaky_a"
    case = _load("provider_failure.json")
    assert case["expect"]["pipeline_crashes"] is False


def test_ranking_is_deterministic():
    from lib.footage_hub import hub as fh
    from lib.footage_hub.contracts import NormalizedAsset

    def mk(p, sid, title, w=640, h=480):
        return NormalizedAsset(provider=p, source_id=sid, title=title,
                               source_url="s", download_url="d", width=w,
                               height=h, license="CC0")
    assets = [mk("nasa", "9", " unrelated clip "),
              mk("archive_org", "1", "river dawn valley", 1920, 1080),
              mk("pexels", "3", "river morning")]
    once = [a.asset_id for a in fh.rank_assets("river dawn", assets)]
    twice = [a.asset_id for a in fh.rank_assets("river dawn", list(reversed(assets)))]
    assert once == twice  # input order cannot change output order
    assert once[0] == "archive_org_1"  # token overlap + resolution wins


# -- download manager: checksum dedupe + vault ---------------------------------

class _BytesAdapter:
    def __init__(self, payload: bytes): self.payload = payload
    def download(self, cand, out_path):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(self.payload)
        return out_path


def test_download_dedupes_identical_bytes(tmp_path):
    from lib.footage_hub import hub as fh
    from lib.footage_hub.contracts import NormalizedAsset

    mgr = fh.DownloadManager(tmp_path / "vault")
    payload = b"x" * 4096
    a1 = NormalizedAsset(provider="pexels", source_id="1", title="river",
                         source_url="s", download_url="http://x/1.mp4",
                         license="Pexels License")
    a2 = NormalizedAsset(provider="pixabay_video", source_id="7", title="river",
                         source_url="s", download_url="http://y/7.mp4",
                         license="Pixabay License")
    a1, new1 = mgr.download(a1, _BytesAdapter(payload))
    a2, new2 = mgr.download(a2, _BytesAdapter(payload))
    assert new1 is True and new2 is False  # identical bytes, one blob
    assert a1.checksum == a2.checksum and a1.checksum.startswith("sha256:")
    assert a1.local_path == a2.local_path
    rows = fh.manifest_rows(tmp_path / "vault")
    assert len(rows) == 2  # provenance kept per alias, never merged
    assert {r["provider"] for r in rows} == {"pexels", "pixabay_video"}


def test_download_failure_propagates_without_substitution(tmp_path):
    from lib.footage_hub import hub as fh
    from lib.footage_hub.contracts import NormalizedAsset

    class _Boom:
        def download(self, c, p): raise ConnectionError("cut cable")
    mgr = fh.DownloadManager(tmp_path / "vault")
    asset = NormalizedAsset(provider="nasa", source_id="9", title="t",
                            source_url="s", download_url="http://x/9.mp4")
    with pytest.raises(ConnectionError):
        mgr.download(asset, _Boom())
    assert fh.manifest_rows(tmp_path / "vault") == []  # nothing fabricated


# -- no-AI guarantee ------------------------------------------------------------

def test_no_generative_fallback_anywhere():
    import pathlib
    banned = ("image_selector", "video_selector", "flux", "diffusion",
              "video_gen", "image_gen", "generate_video", "generate_image")
    files = [Path("lib/footage_hub/contracts.py"), Path("lib/footage_hub/rights.py"),
             Path("lib/footage_hub/registry.py"), Path("lib/footage_hub/hub.py"),
             Path("lib/footage_hub/verify.py"),
             Path("tools/video/footage_hub.py"),
             Path("tools/video/stock_sources/openverse.py"),
             Path("tools/video/stock_sources/dvids.py")]
    for f in files:
        text = f.read_text(encoding="utf-8").lower()
        assert not any(b in text for b in banned), f


# -- tool wrapper ---------------------------------------------------------------

def test_tool_capabilities_and_offline_search(monkeypatch):
    from tools.video.footage_hub import FootageHub

    tool = FootageHub()
    assert tool.estimate_cost({}) == 0.0
    assert tool.fallback_tools == ["direct_clip_search", "corpus_builder"]
    out = tool.execute({"operation": "capabilities"})
    assert out.success and "openverse" in out.data["providers"]
    monkeypatch.setattr("tools.video.stock_sources.all_sources",
                        lambda: [_Good()])
    out = tool.execute({"operation": "search", "query": "river"})
    assert out.success and len(out.data["assets"]) == 1
    assert out.data["assets"][0]["rights_status"] == "verified_public_domain"


# -- filters: resolution / duration / orientation ---------------------------------

class _Dims:
    name = "dims"
    def is_available(self): return True
    def search(self, q, f):
        from tools.video.stock_sources.base import Candidate
        def cand(sid, w, h, dur, kind="video"):
            return Candidate(source="dims", source_id=sid, source_url="s",
                             download_url=f"http://x/{sid}.mp4", kind=kind,
                             width=w, height=h, duration=dur,
                             license="CC0 1.0", source_tags="river")
        return [cand("hd", 1920, 1080, 12.0),
                cand("sd", 640, 480, 4.0),
                cand("nodims", 0, 0, 12.0),
                cand("photo", 1920, 1080, 0.0, kind="image")]
    def download(self, c, p): raise AssertionError("unreachable")


def test_search_enforces_kind_and_filters(monkeypatch):
    from lib.footage_hub import hub as fh

    monkeypatch.setattr("tools.video.stock_sources.all_sources",
                        lambda: [_Dims()])
    videos = fh.search("river", kind="video")
    assert {a.source_id for a in videos.assets} == {"hd", "sd", "nodims"}
    wide = fh.search("river", kind="video", min_width=1280)
    assert [a.source_id for a in wide.assets] == ["hd"]
    long = fh.search("river", kind="video", min_duration=10.0)
    assert {a.source_id for a in long.assets} == {"hd", "nodims"}
    short = fh.search("river", kind="video", max_duration=5.0)
    assert [a.source_id for a in short.assets] == ["sd"]
    land = fh.search("river", kind="video", orientation="landscape")
    assert {a.source_id for a in land.assets} == {"hd", "sd"}  # unknown dims fail closed
    assert land.assets[0].orientation == "landscape"
    images = fh.search("river", kind="image")
    assert [a.source_id for a in images.assets] == ["photo"]


# -- verification: sniffers + download record --------------------------------------

def _png_1x1() -> bytes:
    import os
    import struct
    import zlib

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = struct.pack(">I", len(data)) + typ + data
        return body + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    # zTXt filler: a legitimate ancillary chunk that pushes the file past
    # the hub's 1024B empty-download floor (urandom ~incompressible).
    ztXt = b"Comment\x00\x00" + zlib.compress(os.urandom(2048), 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"zTXt", ztXt) + chunk(b"IDAT", idat)
            + chunk(b"IEND", b""))


def test_sniff_verifies_valid_and_rejects_truncated(tmp_path):
    from lib.footage_hub.verify import (
        MediaCorruptError,
        orientation_of,
        probe_file,
    )

    good = tmp_path / "good.png"
    good.write_bytes(_png_1x1())
    report = probe_file(good, kind="image")
    assert report["verified"] is True
    assert report["container"] == "png"
    assert (report["width"], report["height"]) == (1, 1)
    bad = tmp_path / "trunc.png"
    bad.write_bytes(_png_1x1()[:40])  # magic + IHDR, IDAT/IEND cut off
    with pytest.raises(MediaCorruptError):
        probe_file(bad, kind="image")
    mystery = tmp_path / "mystery.bin"
    mystery.write_bytes(b"x" * 4096)
    rep = probe_file(mystery)
    assert rep["verified"] is False  # unknown != corrupt: never false-positive
    jpeg = tmp_path / "photo.jpg"
    jpeg.write_bytes(b"\xff\xd8" + b"\x00" * 2048 + b"\xff\xd9")
    assert probe_file(jpeg, kind="image")["container"] == "jpeg"
    assert orientation_of(1920, 1080) == "landscape"
    assert orientation_of(0, 0) == "unknown"


def test_download_records_verification_and_enriches(tmp_path):
    from lib.footage_hub import hub as fh
    from lib.footage_hub.contracts import NormalizedAsset

    mgr = fh.DownloadManager(tmp_path / "vault")
    payload = _png_1x1()
    assert len(payload) > 1024  # past the hub's empty-download floor
    asset = NormalizedAsset(provider="wikimedia", source_id="img1",
                            title="river", source_url="s",
                            download_url="http://x/img1.png", kind="image",
                            license="CC-BY-SA 4.0")
    asset, is_new = mgr.download(asset, _BytesAdapter(payload))
    assert is_new is True
    assert asset.checksum.startswith("sha256:")
    assert (asset.width, asset.height) == (1, 1)  # enriched from probe
    rows = fh.manifest_rows(tmp_path / "vault")
    assert rows[-1]["extra"]["verification"]["verified"] is True
    assert rows[-1]["extra"]["verification"]["container"] == "png"


def test_download_rejects_proven_corrupt_bytes(tmp_path):
    from lib.footage_hub import hub as fh
    from lib.footage_hub.contracts import NormalizedAsset
    from lib.footage_hub.verify import MediaCorruptError

    mgr = fh.DownloadManager(tmp_path / "vault")
    corrupt = _png_1x1()[:40] + b"\x00" * 2048  # truncated PNG, past size floor
    asset = NormalizedAsset(provider="wikimedia", source_id="bad",
                            title="t", source_url="s",
                            download_url="http://x/bad.png", kind="image",
                            license="CC-BY-SA 4.0")
    with pytest.raises(MediaCorruptError):
        mgr.download(asset, _BytesAdapter(corrupt))
    assert fh.manifest_rows(tmp_path / "vault") == []  # nothing fabricated


def test_download_retries_transient_then_succeeds(tmp_path):
    from lib.footage_hub import hub as fh
    from lib.footage_hub.contracts import NormalizedAsset

    class _FlakyOnce:
        attempts = 0
        def download(self, cand, out_path):
            type(self).attempts += 1
            if type(self).attempts == 1:
                raise ConnectionError("tls blip")
            return _BytesAdapter(b"y" * 4096).download(cand, out_path)

    _FlakyOnce.attempts = 0
    mgr = fh.DownloadManager(tmp_path / "vault")
    asset = NormalizedAsset(provider="nasa", source_id="r1", title="t",
                            source_url="s", download_url="http://x/r1.mp4",
                            license="Public domain (NASA)")
    asset, is_new = mgr.download(asset, _FlakyOnce(),
                                 retry_backoff_seconds=0)
    assert is_new is True and _FlakyOnce.attempts == 2
    assert asset.checksum.startswith("sha256:")


def test_download_failure_still_propagates_without_substitution(tmp_path):
    # _Boom (existing test) covers the default path; here the no-retry path.
    from lib.footage_hub import hub as fh
    from lib.footage_hub.contracts import NormalizedAsset

    class _Boom:
        def download(self, c, p): raise ConnectionError("cut cable")
    mgr = fh.DownloadManager(tmp_path / "vault")
    asset = NormalizedAsset(provider="nasa", source_id="9", title="t",
                            source_url="s", download_url="http://x/9.mp4")
    with pytest.raises(ConnectionError):
        mgr.download(asset, _Boom(), max_retries=0,
                     retry_backoff_seconds=0)


# -- coverage verdicts ---------------------------------------------------------------

def test_coverage_verdict_matrix():
    from lib.footage_hub.hub import coverage_verdict

    assert coverage_verdict(found=False) == "MISSING"
    assert coverage_verdict(found=True, slot_match=False) == "WRONG"
    assert coverage_verdict(found=True, rights_ok=False) == "WEAK"
    assert coverage_verdict(found=True, media_ok=False) == "WEAK"
    assert coverage_verdict(found=True) == "PASS"
