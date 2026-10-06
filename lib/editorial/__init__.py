"""Editorial intelligence for the YouTube documentary factory.

Deterministic, offline, additive. Research -> evidence -> script ->
fact-check -> storyboard -> visual scoring. This package structures and
validates editorial material; it never invents evidence, never rewrites
claims, and never assumes footage exists. Creative judgment stays with
the directing agent; enforcement stays here.
"""

from lib.editorial import (  # noqa: F401
    factcheck,
    research,
    script_agent,
    storyboard,
    visual_scoring,
)
