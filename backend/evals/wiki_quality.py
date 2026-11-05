"""Advisory style diagnostics, never a semantic quality or golden-set verdict."""
import re


def style_warnings(explanation):
    warnings = []
    if re.search(r"구체물\s*(?:은|는|:)", explanation):
        warnings.append("review_label_in_prose")
    # Narrow heuristic: flag a numeric disclaimer with no matching value in the
    # preceding prose. Sources may contain it: this checks reader-facing context.
    pattern = r"(\d+(?:\.\d+)?\s*(?:초|분|시간))\s*(?:은|는)\s*설명용"
    for match in re.finditer(pattern, explanation):
        value = match.group(1).replace(" ", "")
        if value not in explanation[:match.start()].replace(" ", ""):
            warnings.append("unintroduced_numeric_disclaimer")
            break
    return warnings
