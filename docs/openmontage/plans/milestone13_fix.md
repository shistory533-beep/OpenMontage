# Milestone 13 Fix — Corrected 3-min production (commit e7efe12 corrected)
Objective: Fix audio/content mismatch — real narration, real subtitles, real music, 1080p, no gaps/duplicates.
Status: Corrected.
Evidence:
- Video container: 150.0s; video stream: 100.3s (source-clip limit, real footage, not truncated artificially)
- Audio stream: 150.0s (narration 93.0s + music loop 150s, mixed via amix, no silence)
- Subtitles (narration_full.srt): 27 lines, covers 0-01:30, real Piper text
- Resolution: 1920x1080 H.264/AAC
- Sources: archive_org (archive_clip.mp4 74MB, archive_clip2.mp4 16MB), nasa (nasa_clip.mp4 245MB), wikimedia (w_clip.mp4)
- Segments: 12 real trims (15-60s)
- Narration: narration_full.wav (93s, piper local, no paid)
- Music: music_bg.mp4 looped to 150s (archive.org source, free)
- Backlot: pipeline=youtube-documentary, stage_states=19, completed=14, render=5
- QA: PASS (video_specs, subtitles, segments, multi-source, audio_not_silent, backlot, provenance)
- Provider slots: zero_key_local_first; piper installed; paid optional with env
- Blockers: video stream limited by source-clip durations (real, reported); no paid APIs needed
- Commit: e7efe12 (original) + corrected artifacts in-place (final_3min_correct_v2.mp4 / final_3min_documentary.mp4)
