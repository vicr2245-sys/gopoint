"""
Turns a natural-language route request ("30km hilly bike loop from Frogner
park, avoid busy roads") into a structured RouteRequest the rest of the app
can act on.

This is a one-shot structured-extraction call — not an agentic loop. We ask
Claude to return ONLY JSON matching a schema, then validate/parse it.
"""
import json
import os
from typing import Optional

import anthropic

from models.route_request import Activity, ElevationPreference, RouteRequest

SYSTEM_PROMPT = """You extract structured routing parameters from a user's natural language request for a cycling, running, walking, or hiking route.

Respond with ONLY a JSON object, no preamble, no markdown fences. The JSON must have exactly these fields:

{
  "activity": one of ["cycling-road", "cycling-mountain", "cycling-regular", "foot-running", "foot-walking", "foot-hiking"],
  "start_location": string (place name, address, or landmark as mentioned by the user; if none given, use "current_location"),
  "end_location": string or null (null if it's a loop / out-and-back back to start),
  "is_loop": boolean,
  "target_distance_km": number or null,
  "elevation_preference": one of ["flat", "hilly", "no_preference"],
  "target_elevation_gain_m": number or null (a SPECIFIC numeric elevation/climbing target in meters, if the user gave one),
  "avoid_main_roads": boolean,
  "avoid_highways": boolean,
  "avoid_ferries": boolean,
  "surface_preference": string or null (e.g. "paved", "unpaved", "gravel", "trail", null if unspecified)
}

Rules:
- If the user says "run" -> foot-running. "Walk"/"stroll" -> foot-walking. "Hike" -> foot-hiking.
- If the user says "bike"/"cycle" without specifics -> cycling-regular. Mentions of "road bike"/"racing" -> cycling-road. "Mountain bike"/"MTB"/"trail" -> cycling-mountain.
- Default avoid_highways to true always (nobody wants to run/cycle on a highway).
- Default avoid_ferries to true always (avoid routing over water/ferries unless explicitly requested).
- Default avoid_main_roads to true only if the user hints at wanting quiet/scenic/safe streets.
- If no distance is mentioned, target_distance_km is null.
- If the user gives only a distance and activity, treat it as a loop with end_location null.
- If the user does not mention a start location, use "current_location"; do not invent a city or landmark.
- If the user mentions a destination different from the start, is_loop is false and end_location is set.
- If the user asks for a route "from", "starting at", or "near" a place but gives no destination, is_loop is true and end_location is null.
- target_elevation_gain_m: only set this when the user gives an actual NUMBER (e.g. "aim for 500m of elevation", "at least 300m of climbing", "around 800ft of gain" -> convert feet to meters). If they only say "hilly" or "flat" with no number, leave this null and rely on elevation_preference instead. When target_elevation_gain_m is set, also set elevation_preference to "hilly" (a numeric climbing target implies they want a hilly route, not a flat one).
- This target is inherently approximate: real terrain often can't hit an exact climbing figure near a given start point. Extract the number faithfully regardless — the routing layer handles the "how close can we actually get" part, not you.
- surface_preference: if the user requests "unpaved", "off-road", "dirt", "gravel", "avoid pavement", or "no paved roads", set surface_preference to "unpaved" (or "gravel"/"trail" if specified). NEVER set surface_preference to "paved" when the user asks for unpaved or asks to avoid paved roads.
"""


class PromptParsingError(Exception):
    pass


import re

def fallback_parse_prompt(prompt: str) -> RouteRequest:
    """
    Fast local rule-based fallback parser used when the Anthropic API is
    unavailable (e.g. no API key configured, key out of credits, network
    down, or 404 model not found on account tier). Ensures route planning
    always works seamlessly regardless of API key status.
    """
    p_lower = prompt.lower()

    if "run" in p_lower or "jog" in p_lower:
        activity = Activity.RUNNING
    elif "hike" in p_lower or "trek" in p_lower:
        activity = Activity.HIKING
    elif "walk" in p_lower or "stroll" in p_lower:
        activity = Activity.WALKING
    elif "road bike" in p_lower or "racing" in p_lower:
        activity = Activity.CYCLING_ROAD
    elif "mountain bike" in p_lower or "mtb" in p_lower:
        activity = Activity.CYCLING_MOUNTAIN
    elif "bike" in p_lower or "cycle" in p_lower or "ride" in p_lower:
        activity = Activity.CYCLING_REGULAR
    else:
        activity = Activity.CYCLING_REGULAR

    target_dist = None
    dist_match = re.search(r'(\d+(?:\.\d+)?)\s*(km|k|kilometers?|miles?|mi)\b', p_lower)
    if dist_match:
        val = float(dist_match.group(1))
        unit = dist_match.group(2)
        if unit in ("mile", "miles", "mi"):
            val *= 1.60934
        target_dist = round(val, 1)

    elevation_pref = ElevationPreference.NO_PREFERENCE
    if "hilly" in p_lower or "climbing" in p_lower or "steep" in p_lower:
        elevation_pref = ElevationPreference.HILLY
    elif "flat" in p_lower:
        elevation_pref = ElevationPreference.FLAT

    target_elev = None
    elev_match = re.search(r'(\d+)\s*(m|meters?|ft|feet)\s*(?:of)?\s*(?:climbing|elevation|gain)', p_lower)
    if elev_match:
        val = float(elev_match.group(1))
        unit = elev_match.group(2)
        if unit in ("ft", "feet"):
            val *= 0.3048
        target_elev = round(val, 1)
        elevation_pref = ElevationPreference.HILLY

    surface_pref = None
    if any(w in p_lower for w in ["unpaved", "offroad", "off-road", "avoid paved", "no paved", "non-paved", "not paved"]):
        surface_pref = "unpaved"
    elif "gravel" in p_lower:
        surface_pref = "gravel"
    elif "dirt" in p_lower or "trail" in p_lower:
        surface_pref = "trail"
    elif re.search(r'\b(?:paved|asphalt|tarmac)\b', p_lower):
        surface_pref = "paved"

    avoid_main = "quiet" in p_lower or "avoid busy" in p_lower or "safe" in p_lower
    avoid_highways = True

    start_loc = "current_location"
    end_loc = None
    is_loop = True

    from_to = re.search(r'\b(?:from|starting at|start at)\s+([^,.]+?)\s+to\s+([^,.]+)', prompt, re.IGNORECASE)
    if from_to:
        start_loc = from_to.group(1).strip()
        end_loc = from_to.group(2).strip()
        is_loop = False
    else:
        # Check prepositions first (in, near, around, from, at, by, starting at, outside, through)
        matches = list(re.finditer(r'\b(?:from|starting at|start at|in|near|around|at|by|through|outside)\s+([\w\s\-\.]+)', prompt, re.IGNORECASE))
        if matches:
            best_match = matches[0]
            for m in matches:
                kw = m.group(0).lower()
                if kw.startswith("from") or kw.startswith("starting") or kw.startswith("start"):
                    best_match = m
                    break
            raw_loc = best_match.group(1).strip()
            cleaned = re.split(r'[.,;]|\b(?:stick|avoid|fairly|with|trail|ride|run|bike|cycling|hike|walk|loop|route|road|flat|hilly|gravel|paved|asphalt)\b', raw_loc, flags=re.IGNORECASE)[0].strip()
            cleaned = re.sub(r'(\d+(?:\.\d+)?)\s*(?:km|k|kilometers?|miles?|mi)\b', '', cleaned, flags=re.IGNORECASE).strip()
            if cleaned and cleaned.lower() not in ("a", "the", "an", "around", "in", "near"):
                start_loc = cleaned

        # Fallback: if start_loc is still "current_location", strip keywords and distance/activity to extract place name
        if start_loc == "current_location":
            tokens = re.sub(r'(\d+(?:\.\d+)?)\s*(?:km|k|kilometers?|miles?|mi)\b', '', prompt, flags=re.IGNORECASE)
            tokens = re.sub(r'\b(?:a|the|an|ride|run|walk|hike|bike|loop|route|road|cycling|hilly|flat|paved|gravel|trail|around|in|near|at|from|by|outside|through|avoid|quiet|busy|steep)\b', '', tokens, flags=re.IGNORECASE)
            cleaned = tokens.strip(" .,;:-")
            if cleaned and len(cleaned) >= 3 and not cleaned.replace('.', '').replace('-', '').isdigit():
                start_loc = cleaned

    return RouteRequest(
        activity=activity,
        start_location=start_loc,
        end_location=end_loc,
        is_loop=is_loop,
        target_distance_km=target_dist,
        elevation_preference=elevation_pref,
        target_elevation_gain_m=target_elev,
        avoid_main_roads=avoid_main,
        avoid_highways=avoid_highways,
        avoid_ferries=True,
        surface_preference=surface_pref,
        raw_prompt=prompt,
    )


import logging
logging.getLogger("httpx").setLevel(logging.WARNING)


def _clean_location_string(loc_str: str) -> str:
    """
    Clean location strings extracted from natural language prompts.
    Strips leading articles/prepositions ("the", "a", "an", "in", "near", "around")
    and trailing modifier words ("area", "region", "district", "municipality",
    "only", "on", "just", "preferring", "with", "stick to").
    """
    if not loc_str or loc_str == "current_location":
        return loc_str

    loc = loc_str.strip()

    # Cut off trailing clause starting with condition keywords
    loc = re.split(
        r'\b(?:only|on|just|prefer|preferring|with|stick|avoid|fairly|trail|ride|run|bike|cycling|hike|walk|loop|route|road|flat|hilly|gravel|paved|asphalt)\b',
        loc,
        flags=re.IGNORECASE,
    )[0].strip()

    # Strip trailing area noise words
    loc = re.sub(
        r'\b(?:area|region|district|municipality|city|vicinity|neighborhood|neighbourhood)\b',
        '',
        loc,
        flags=re.IGNORECASE,
    ).strip()

    # Strip leading articles & prepositions
    loc = re.sub(
        r'^(?:the|a|an|in|near|around|at|from|starting at|start at|by|outside|through)\s+',
        '',
        loc,
        flags=re.IGNORECASE,
    ).strip()

    loc = re.sub(
        r'\b(?:the|area|region|city|town|village|of)\b',
        '',
        loc,
        flags=re.IGNORECASE,
    ).strip()

    return loc or loc_str


def parse_prompt(prompt: str, api_key: Optional[str] = None) -> RouteRequest:
    """
    Parse a natural language route request into a RouteRequest.
    Tries Anthropic API first; if unavailable or failing, falls back to the
    local rule-based parser so route planning always succeeds.
    """
    req = None
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if key:
        try:
            client = anthropic.Anthropic(api_key=key)
            models_to_try = [
                "claude-3-5-sonnet-20240620",
                "claude-3-haiku-20240307",
                "claude-3-opus-20240229",
            ]
            response = None
            for model_name in models_to_try:
                try:
                    response = client.messages.create(
                        model=model_name,
                        max_tokens=500,
                        system=SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    break
                except Exception:
                    continue

            if response is not None:
                text = "".join(block.text for block in response.content if block.type == "text").strip()
                text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                data = json.loads(text)
                req = RouteRequest(
                    activity=Activity(data["activity"]),
                    start_location=data["start_location"],
                    end_location=data.get("end_location"),
                    is_loop=bool(data["is_loop"]),
                    target_distance_km=data.get("target_distance_km"),
                    elevation_preference=ElevationPreference(data["elevation_preference"]),
                    target_elevation_gain_m=data.get("target_elevation_gain_m"),
                    avoid_main_roads=bool(data["avoid_main_roads"]),
                    avoid_highways=bool(data["avoid_highways"]),
                    avoid_ferries=bool(data.get("avoid_ferries", True)),
                    surface_preference=data.get("surface_preference"),
                    raw_prompt=prompt,
                )
        except Exception:
            pass

    if req is None:
        req = fallback_parse_prompt(prompt)

    if req.start_location:
        req.start_location = _clean_location_string(req.start_location)
    if req.end_location:
        req.end_location = _clean_location_string(req.end_location)

    return req


if __name__ == "__main__":
    # Quick manual test: python -m core.prompt_parser
    examples = [
        "I want a 25km road bike loop from Frogner park, fairly flat, avoid busy streets",
        "Give me a hilly 10k running route starting from Grunerlokka",
        "Mountain bike trail ride, around 15km, from Sognsvann",
    ]
    for ex in examples:
        try:
            req = parse_prompt(ex)
            print(f"\nPrompt: {ex}\n -> {req}")
        except PromptParsingError as e:
            print(f"\nPrompt: {ex}\n -> FAILED: {e}")
