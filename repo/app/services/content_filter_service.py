import logging
import re

from app.extensions import db
from app.models.content import ContentFilter

logger = logging.getLogger(__name__)


def filter_content(text: str) -> dict:
    """
    Run text through all active content filters.

    Returns:
        {"passed": True, "violations": []}
        OR {"passed": False, "violations": [{"pattern": str, "filter_type": str, "match": str, "position": int}]}
    """
    if not text:
        return {"passed": True, "violations": []}

    active_filters = ContentFilter.query.filter_by(is_active=True).all()
    violations = []

    for f in active_filters:
        if f.filter_type == "keyword":
            index = text.lower().find(f.pattern.lower())
            if index != -1:
                violations.append(
                    {
                        "pattern": f.pattern,
                        "filter_type": "keyword",
                        "match": text[index : index + len(f.pattern)],
                        "position": index,
                    }
                )
        elif f.filter_type == "regex":
            try:
                match = re.search(f.pattern, text, re.IGNORECASE)
                if match:
                    violations.append(
                        {
                            "pattern": f.pattern,
                            "filter_type": "regex",
                            "match": match.group(),
                            "position": match.start(),
                        }
                    )
            except re.error as e:
                logger.warning("Invalid regex pattern '%s': %s", f.pattern, e)

    return {"passed": len(violations) == 0, "violations": violations}
