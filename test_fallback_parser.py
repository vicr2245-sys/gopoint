"""
Unit test for fallback_parse_prompt location extraction.
"""
from core.prompt_parser import fallback_parse_prompt


def test_fallback_locations():
    test_cases = [
        ("A 20km ride in sarpsborg", "sarpsborg"),
        ("20km loop around sarpsborg", "sarpsborg"),
        ("30km bike ride near moss", "moss"),
        ("15km run starting at Fredrikstad", "Fredrikstad"),
        ("20km road bike from Oslo to Drammen", "Oslo", "Drammen"),
        ("Hike around Sognsvann 10km", "Sognsvann"),
        ("20km ride sarpsborg", "sarpsborg"),
    ]

    for item in test_cases:
        prompt = item[0]
        expected_start = item[1]
        expected_end = item[2] if len(item) > 2 else None

        req = fallback_parse_prompt(prompt)
        assert req.start_location.lower() == expected_start.lower(), f"Expected start '{expected_start}', got '{req.start_location}'"
        if expected_end:
            assert req.end_location and req.end_location.lower() == expected_end.lower(), f"Expected end '{expected_end}', got '{req.end_location}'"
