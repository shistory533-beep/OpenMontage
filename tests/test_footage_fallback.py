"""run_footage alternate-candidate fallback (Apollo s2 regression).

2026-10-08: the Apollo smoke halted at the footage stage because the
top-scored Mixkit pick had a bot-gated detail page (301 to /discover/ for
non-browser UAs, no statically scrapable mp4) while verified Wikimedia/ESA/
NASA alternates existed for the same slot. run_footage tried only
scores[0], so one broken download URL stranded the slot.

Contract locked here: scored pass/weak candidates are tried in rank order;
first successful download wins; a gap is reported only when ALL fail.
Strict rights scoring is unchanged — alternates were already verified.
"""

from __future__ import annotations

import pytest

from lib.producer.producer import CriticalStageError, StageContext
from lib.producer.runners import run_footage


def _cand(asset_id, provider="wikimedia"):
    return {"asset_id": asset_id, "id": asset_id, "provider": provider,
            "source_id": asset_id, "kind": "video",
            "source_url": f"https://example.test/{asset_id}",
            "width": 1280, "height": 720, "duration": 10.0,
            "format": "mp4", "license": "CC-BY", "title": asset_id}


def _ctx(tmp_path):
    return StageContext(
        episode_id="ep-fallback-001", stage="footage",
        inputs={"scene_plan": {"scenes": [{
            "id": "slot-s2", "description": "earth moon space",
            "start_seconds": 0.0, "end_seconds": 10.0,
            "script_section_id": "s2"}]}},
        workdir=tmp_path / "ep-fallback-001")


def _patch(monkeypatch, tmp_path, downloads):
    """downloads: {asset_id: Path | Exception}."""
    import lib.editorial.visual_scoring as vs
    import lib.footage_hub.hub as hub
    import lib.footage_hub.registry as registry
    import lib.producer.runners as runners

    class _Found:
        assets = [_cand("top-broken", "mixkit"), _cand("alt-good")]

    monkeypatch.setattr(hub, "search",
                        lambda *a, **k: _Found())
    monkeypatch.setattr(registry, "get_adapter",
                        lambda provider: object())

    class _Scorer:
        def score_requirement(self, req, cands):
            return {"decision": "pass", "scores": [
                {"asset_id": "top-broken", "decision": "pass",
                 "final_score": 0.9, "reason": "top"},
                {"asset_id": "alt-good", "decision": "pass",
                 "final_score": 0.8, "reason": "alternate"}]}

    monkeypatch.setattr(vs, "VisualScorer", lambda: _Scorer())

    class _DL:
        def __init__(self, asset):
            self.asset = dict(asset)

        def to_dict(self):
            return dict(self.asset)

    class _Mgr:
        def __init__(self, vault):
            pass

        def download(self, asset, adapter):
            aid = asset.asset_id if hasattr(asset, "asset_id") else \
                asset.get("asset_id")
            outcome = downloads.get(aid)
            if outcome is None:
                # NormalizedAsset may prefix provider (as the real hub
                # does); match on the bare id suffix like a real lookup.
                bare = aid.split("_", 1)[-1]
                outcome = downloads.get(bare, RuntimeError(
                    f"unexpected asset {aid}"))
            if isinstance(outcome, Exception):
                raise outcome
            rec = _cand(aid)
            rec["local_path"] = str(outcome)
            return _DL(rec), None

    monkeypatch.setattr(hub, "DownloadManager", _Mgr)


def test_footage_falls_back_to_scored_alternate(tmp_path, monkeypatch):
    blob = tmp_path / "alt.mp4"
    blob.write_bytes(b"\x00" * 64)
    _patch(monkeypatch, tmp_path,
           {"top-broken": RuntimeError("Mixkit download failed"),
            "alt-good": blob})
    out = run_footage(_ctx(tmp_path), {"footage_per_provider": 2})
    assets = out["asset_manifest"]["assets"]
    assert len(assets) == 1
    assert assets[0]["id"].endswith("alt-good")
    assert assets[0]["provider"] == "wikimedia"
    assert assets[0]["path"] == str(blob)


def test_footage_gaps_loudly_when_all_candidates_fail(tmp_path,
                                                      monkeypatch):
    _patch(monkeypatch, tmp_path,
           {"top-broken": RuntimeError("Mixkit download failed"),
            "alt-good": RuntimeError("no bytes")})
    with pytest.raises(CriticalStageError) as exc:
        run_footage(_ctx(tmp_path), {"footage_per_provider": 2})
    assert "slot-s2" in str(exc.value)
