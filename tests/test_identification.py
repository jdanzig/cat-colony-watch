"""Small assert-based checks for the fixed matching decision rule."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.identification import _clearly_different_coat, decide_match


def comparison(candidate, markings=(), contradictions=(), different=False):
    return {
        "candidate": candidate,
        "features": {
            "coat_color": "different" if different else "same",
            "pattern": "same",
            "face_markings": "unclear",
        },
        "matching_specific_markings": list(markings),
        "contradictions": list(contradictions),
    }


assert decide_match([])["suggestion"] == "new"
assert decide_match([comparison("cat-a", ("white nose blaze", "left sock boundary"))]) == {
    "suggestion": "strong",
    "candidate_id": "cat-a",
    "reason": "white nose blaze; left sock boundary",
}
assert decide_match(
    [comparison("cat-a", ("white nose blaze", "left sock boundary"), different=True)]
)["suggestion"] == "new"
assert decide_match(
    [
        comparison("cat-a", ("white nose blaze", "left sock boundary")),
        comparison("cat-b", ("chest patch", "torn ear")),
    ]
)["suggestion"] == "weak"
assert decide_match([comparison("cat-a", ("white nose blaze",))])["suggestion"] == "weak"
eye_only = comparison("cat-a", ("white nose blaze", "left sock boundary"), ("eye color",))
eye_only["features"]["eye_color"] = "different"
assert decide_match([eye_only])["suggestion"] == "weak"
assert not _clearly_different_coat("white", "cream")
assert not _clearly_different_coat("black", "gray")
assert _clearly_different_coat("black", "orange")

print("matching decision checks passed")
