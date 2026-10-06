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
