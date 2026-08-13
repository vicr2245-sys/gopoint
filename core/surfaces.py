"""
Shared surface metadata used by ORS parsing, route scoring, sidebar charts,
and map overlays. Keep labels/colors here so the UI and provider never drift.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SurfaceStyle:
    key: str
    label: str
    color: str
    keywords: tuple[str, ...]


SURFACE_STYLES: dict[str, SurfaceStyle] = {
    "unknown": SurfaceStyle("unknown", "Unknown", "#64748b", ("unknown",)),
    "paved": SurfaceStyle("paved", "Paved", "#2563eb", ("paved", "road", "street")),
    "unpaved": SurfaceStyle("unpaved", "Unpaved", "#92400e", ("unpaved", "offroad", "off-road")),
    "asphalt": SurfaceStyle("asphalt", "Asphalt", "#1d4ed8", ("asphalt", "tarmac", "road")),
    "concrete": SurfaceStyle("concrete", "Concrete", "#64748b", ("concrete",)),
    "cobblestone": SurfaceStyle("cobblestone", "Cobblestone", "#7c3aed", ("cobblestone", "cobbles")),
    "metal": SurfaceStyle("metal", "Metal", "#475569", ("metal",)),
    "wood": SurfaceStyle("wood", "Wood", "#b45309", ("wood", "boardwalk")),
    "compacted_gravel": SurfaceStyle(
        "compacted_gravel",
        "Compacted Gravel",
        "#ca8a04",
        ("compacted", "gravel", "hardpack"),
    ),
    "fine_gravel": SurfaceStyle("fine_gravel", "Fine Gravel", "#d97706", ("fine gravel", "gravel")),
    "gravel": SurfaceStyle("gravel", "Gravel", "#a16207", ("gravel",)),
    "dirt": SurfaceStyle("dirt", "Dirt", "#854d0e", ("dirt", "trail")),
    "ground": SurfaceStyle("ground", "Ground", "#65a30d", ("ground", "natural", "trail")),
    "ice": SurfaceStyle("ice", "Ice", "#38bdf8", ("ice", "snow")),
    "paving_stones": SurfaceStyle("paving_stones", "Paving Stones", "#6d28d9", ("paving", "stones")),
    "sand": SurfaceStyle("sand", "Sand", "#eab308", ("sand",)),
    "woodchips": SurfaceStyle("woodchips", "Woodchips", "#a16207", ("woodchips", "mulch")),
    "grass": SurfaceStyle("grass", "Grass", "#16a34a", ("grass",)),
    "grass_paver": SurfaceStyle("grass_paver", "Grass Paver", "#15803d", ("grass paver", "grasscrete")),
    "other": SurfaceStyle("other", "Other", "#64748b", ("other",)),
}

ORS_SURFACE_CODE_TO_KEY: dict[int, str] = {
    0: "unknown",
    1: "paved",
    2: "unpaved",
    3: "asphalt",
    4: "concrete",
    5: "cobblestone",
    6: "metal",
    7: "wood",
    8: "compacted_gravel",
    9: "fine_gravel",
    10: "gravel",
    11: "dirt",
    12: "ground",
    13: "ice",
    14: "paving_stones",
    15: "sand",
    16: "woodchips",
    17: "grass",
    18: "grass_paver",
}


def surface_label_for_ors_code(value) -> str:
    try:
        code = int(value)
    except (TypeError, ValueError):
        return SURFACE_STYLES["other"].label

    key = ORS_SURFACE_CODE_TO_KEY.get(code, "other")
    return SURFACE_STYLES[key].label


def surface_color(label: str) -> str:
    return _style_for_label(label).color


def surface_styles_for_ui() -> dict[str, str]:
    return {
        style.label: style.color
        for style in SURFACE_STYLES.values()
    }


def surface_preference_bonus(composition: dict[str, float], preference: str) -> float:
    preference_lower = preference.lower()
    matching_percent = 0.0

    for label, percent in composition.items():
        style = _style_for_label(label)
        if any(keyword in preference_lower for keyword in style.keywords):
            matching_percent += percent

    return (matching_percent / 100.0) * 3.0


def _style_for_label(label: str) -> SurfaceStyle:
    for style in SURFACE_STYLES.values():
        if style.label == label:
            return style
    return SURFACE_STYLES["other"]
