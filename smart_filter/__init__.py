"""Smart-Filter - a lightweight two-stage search-query filter.

Stage 1 applies local rule-based + fuzzy matching; Stage 2 uses a semantic
decision provider (Jev or Gemini) for classification. Provider failures fail
closed to an ERROR result.
"""

from .config import Settings
from .gemini_classifier import GeminiClassifier, GeminiError, build_payload as build_gemini_payload
from .jev_classifier import (
    ALLOW_LABEL,
    JevClassifier,
    JevError,
    JevRetryableError,
    JevVerdict,
    build_payload as build_jev_payload,
)
from .matcher import KeywordMatcher, QueryClassification
from .pipeline import ClassificationResult, SmartFilter, Status
from .providers import (
    PROVIDERS,
    SemanticError,
    SemanticVerdict,
    normalize_provider,
)

# Backwards-compatible aliases (pre-rename names).
SanityChecker = KeywordMatcher
SanityFilter = SmartFilter

__all__ = [
    "KeywordMatcher",
    "QueryClassification",
    "SanityChecker",
    "Settings",
    "SmartFilter",
    "SanityFilter",
    "ClassificationResult",
    "Status",
    "JevClassifier",
    "JevError",
    "JevRetryableError",
    "JevVerdict",
    "GeminiClassifier",
    "GeminiError",
    "SemanticError",
    "SemanticVerdict",
    "PROVIDERS",
    "normalize_provider",
    "ALLOW_LABEL",
    "build_jev_payload",
    "build_gemini_payload",
]
