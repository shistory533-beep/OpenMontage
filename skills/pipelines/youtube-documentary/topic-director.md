# Topic Director - YouTube Documentary Pipeline

You turn the user's request into the brief artifact every downstream stage reads:
the documentary question, audience, target duration, and production constraints.

## Runtime selection (MANDATORY — present the constraint, don't silently pick)

Lock `render_runtime = "remotion"`. HyperFrames is NOT a valid runtime on this
pipeline yet — the documentary render stack (CinematicRenderer composition,
ProRes-4444 end-tag overlay, uniform-LUT montage grade) has no HyperFrames
parity, same as documentary-montage.

Per AGENT_GUIDE.md → "Present Both Composition Runtimes (HARD RULE)": do NOT
silently default. Tell the user: "HyperFrames is available on your machine as
an alternative runtime, but youtube-documentary depends on the Remotion
CinematicRenderer stack, so remotion is the only viable choice here — OK to
proceed?" Record a `render_runtime_selection` decision in `decision_log`
listing both runtimes in `options_considered`, with hyperframes
`rejected_because: "CinematicRenderer + end-tag overlay parity deferred on
youtube-documentary"`. Present both runtimes, recommend remotion with the
reason above, and wait for explicit approval before advancing.

## Prerequisites

None — this is the entry stage.

## Process

1. Extract ONE documentary question (the thesis the episode answers).
2. Fix audience, target duration (YouTube long-form default 8–15 min), and tone.
3. Record the narration plan (opt-in lane, default on for this pipeline),
   the music plan (mandatory — silent only with explicit user opt-out), and
   the rights policy (verified-rights default; FootageHub rejects unknown
   rights under it).
4. Write the schema-valid brief artifact.

## Checkpoint boundary

`completed` only with `human_approved=True`. Failure (vague question, missing
duration, no rights policy) writes checkpoint `failed` with a reason and
blocks research — fail closed.
