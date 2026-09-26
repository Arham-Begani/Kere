"""The prompt and tool for city map reads. eval/prompt.py is frozen for the Bengaluru scoring
(CLAUDE.md) and is never touched; city reads get their own prompt with their own version string
(build-2 rule 5). The only schema addition vs eval/prompt.py is nearest_place_as_printed, since
1:250,000 sheets rarely name tanks directly (build-2 rule 4)."""

PROMPT_VERSION = "kere-city-v1"

PROMPT = """This image is a {w}x{h}-pixel tile cut from a scanned US Army Map Service 1:250,000 map of the {city} area, India (sheet "{sheet_title}", {sheet}, {series}), compiled in {compiled_year}.

Find every water body (tank, lake or reservoir) drawn on this tile. Water bodies are drawn in blue ink, as a solid fill, as blue hatching, or both.

For each water body, report:
- x, y: one point clearly INSIDE the water body, in this image's pixel coordinates (origin at the top-left corner, x to the right, y downwards; the image is {w} pixels wide and {h} pixels tall).
- bbox: a tight box around the water body as [x_min, y_min, x_max, y_max] in the same pixel coordinates.
- name_as_printed: the name exactly as printed on this tile next to the water body, including any accents. These 1:250,000 sheets rarely print a tank's own name -- use null if none is printed for it on this tile. Never supply a name from memory or outside knowledge.
- nearest_place_as_printed: the name of the nearest populated place or locality label printed on this tile near this water body, if any is visible, exactly as printed. Use null if no place name is visible nearby.
- style: "solid", "hatched" or "mixed".
- partial: true if the tile edge cuts the water body off.

Report each water body once. Do not report rivers, canals or streams drawn as lines, the sea, roads, or built-up area shading. If there are no water bodies, report an empty list.

Call the report_tanks tool exactly once with your answer."""

TOOL = {
    "name": "report_tanks",
    "description": "Report every water body (tank, lake or reservoir) drawn on the map tile.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["image_width", "image_height", "tanks"],
        "properties": {
            "image_width": {"type": "integer", "description": "Width of the image as you see it, in pixels"},
            "image_height": {"type": "integer", "description": "Height of the image as you see it, in pixels"},
            "tanks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["x", "y", "bbox", "name_as_printed", "nearest_place_as_printed", "style", "partial"],
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "bbox": {"type": "array", "items": {"type": "number"}, "description": "[x_min, y_min, x_max, y_max]"},
                        "name_as_printed": {"type": ["string", "null"]},
                        "nearest_place_as_printed": {"type": ["string", "null"]},
                        "style": {"type": "string", "enum": ["solid", "hatched", "mixed"]},
                        "partial": {"type": "boolean"},
                    },
                },
            },
        },
    },
}


def build_prompt(city_cfg, key):
    compiled_year = "1954"
    note = city_cfg.get("compiled_note", "")
    if "Compiled in 1955" in note:
        compiled_year = "1955"
    return PROMPT.format(w=key["width"], h=key["height"], city=city_cfg["name"],
                          sheet_title=city_cfg.get("sheet_title", city_cfg["name"]),
                          sheet=city_cfg["sheet"], series="AMS Series U502", compiled_year=compiled_year)
