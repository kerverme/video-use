"""Built-in editing presets."""

from __future__ import annotations

ARCHITECTURAL_GUIDANCE = """Create a cinematic architectural presentation from the supplied footage.

Visual direction:
- luxury architectural film
- quiet luxury
- elegant and restrained
- realistic
- slow pacing
- smooth continuity between spaces
- prioritize good camera movement
- preserve material detail
- preserve architectural geometry
- avoid excessive digital effects
- no TikTok-style editing
- no aggressive zooms
- no flashy transitions
- no unnecessary speed ramps
- minimal typography
- subtle room labels only when helpful
- sophisticated atmosphere
- clean opening and closing
- let important shots breathe

Typical duration: 60–90 seconds.
Typical footage: Blender architectural renders."""

ARCHITECTURAL_SPACES = [
    "Exterior", "Entrance", "Living Room", "Counter / Bar", "Staircase",
    "Bedroom 1", "Bedroom 2", "Bathroom", "Sauna", "Male Locker", "Female Locker",
    "Onsen", "Hot Bath", "Cold Plunge", "Stream", "Nature Views",
]

PRESETS = {
    "architectural": {
        "id": "architectural",
        "name": "Architectural Film",
        "description": "Quiet-luxury cinematic walkthrough. Slow pacing, subtle dissolves, minimal typography.",
        "guidance": ARCHITECTURAL_GUIDANCE,
        "target_duration": 75,
        "duration_range": [60, 90],
        "spaces": ARCHITECTURAL_SPACES,
        "render_defaults": {"fps": "source", "grade": "none", "fit": "crop", "aspect": "source"},
        # Craft notes given to the planner in addition to the user's prompt.
        "planner_notes": (
            "Architectural film craft: hold shots 5–12 seconds, and longer for hero spaces. Choose ranges "
            "where the camera move is smooth and continuous; avoid the first and last few frames of "
            "a render if the move eases in or out awkwardly. Sequence spaces as a believable walk "
            "(arrival → public spaces → private spaces → wellness → nature → departure). Use "
            "cuts or 0.8–1.5s dissolves between spaces; never flashy transitions. Open with a "
            "fade from black and close with a fade to black. Labels are short room names "
            "(e.g. 'Living Room'), used sparingly."
        ),
    },
}


def public_presets() -> list[dict]:
    return [{k: v for k, v in p.items() if k != "planner_notes"} for p in PRESETS.values()]
