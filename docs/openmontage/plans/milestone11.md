# Milestone 11 Plan — Piper + manifest + 60–120s real video
Objective: Real 60-120s H.264/AAC documentary with Piper narration, fixed pipeline_type, multi-source free footage, preserved gates/provenance/backlot.
Reuse: youtube-documentary.yaml (manifest), archive_org + nasa adapters, backlot.state.load_board_state, lib/checkpoint, factory/job_state.
Constraints: No paid APIs; piper must be installed/configured or honestly reported missing; no fake audio/video.
Steps: 1) Install piper (apt/build/check). 2) Wire manifest to project + backlot pipeline detection. 3) Corpus/clip_search with archive_org + nasa. 4) Build 60-120s video (real clips + piper audio/subtitles + ffmpeg mix). 5) QA ffprobe + audio check. 6) Tests. 7) Commit.
Verification: ffprobe duration/resolution/codec + audio stream present; Backlot pipeline_type=youtube-documentary; provenance updated.
