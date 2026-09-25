"""The exact prompt and tool both models get. Change PROMPT_VERSION whenever anything here changes."""

PROMPT_VERSION = "kere-tanks-v2"

SHEET_TEXT = {
    "plan_25k": "the 1:25,000 greyscale city plan \"Bangalore and Vicinity\" (built-up areas are shaded grey)",
    "front_250k": "a 1:250,000 colour topographic sheet, enlarged 2x (water is drawn in blue)",
}

PROMPT = """This image is a {w}x{h}-pixel tile cut from a scanned US Army Map Service map of Bangalore, India, compiled in 1954: {sheet}.

Find every water body (tank or lake) drawn on this tile. Water bodies are shown as solid dark fills, as hatched areas (parallel diagonal lines), or both.

For each water body, report:
- x, y: one point clearly INSIDE the water body, in this image's pixel coordinates (origin at the top-left corner, x to the right, y downwards; the image is {w} pixels wide and {h} pixels tall).
- bbox: a tight box around the water body as [x_min, y_min, x_max, y_max] in the same pixel coordinates.
- name_as_printed: the name exactly as printed on this tile next to the water body, including any accents. Use null if no name is printed for it on this tile. Do not supply names from memory or outside knowledge.
- style: "solid", "hatched" or "mixed".
- partial: true if the tile edge cuts the water body off.

Report each water body once. Do not report rivers or streams drawn as lines, roads, parks, racecourses, cemeteries, quarries or buildings. If there are no water bodies, report an empty list.

Call the report_tanks tool exactly once with your answer."""

TOOL = {
    "name": "report_tanks",
    "description": "Report every water body (tank or lake) drawn on the map tile.",
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
                    "required": ["x", "y", "bbox", "name_as_printed", "style", "partial"],
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "bbox": {"type": "array", "items": {"type": "number"}, "description": "[x_min, y_min, x_max, y_max]"},
                        "name_as_printed": {"type": ["string", "null"]},
                        "style": {"type": "string", "enum": ["solid", "hatched", "mixed"]},
                        "partial": {"type": "boolean"},
                    },
                },
            },
        },
    },
}


def build_prompt(key):
    return PROMPT.format(w=key["width"], h=key["height"], sheet=SHEET_TEXT[key["sheet"]])
