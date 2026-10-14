"""Rule-based query classifier with fuzzy matching for misspellings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Set, Union


@dataclass
class QueryClassification:
    """Result of query classification."""

    is_safe: bool
    is_blocked: bool
    matched_keywords: List[str]
    reason: Optional[str] = None


class KeywordMatcher:
    """Simple rule-based classifier that flags queries containing blocked keywords."""

    def __init__(self, blocked_keywords: Optional[Union[List[str], Set[str]]] = None):
        if blocked_keywords is None:
            blocked_keywords = ["hack", "exploit", "malware", "phish", "spam"]
        self._blocked_keywords: Set[str] = {
            kw.lower().strip() for kw in blocked_keywords if kw.strip()
        }
        self._false_positives: Set[str] = {
            "back", "pack", "sack", "rack", "lack",
            "hock", "bock", "hoax",
            "apply", "applets",
        }

    @property
    def blocked_keywords(self) -> Set[str]:
        return self._blocked_keywords.copy()

    def add_blocked_keyword(self, keyword: str) -> None:
        if keyword.strip():
            self._blocked_keywords.add(keyword.lower().strip())

    def remove_blocked_keyword(self, keyword: str) -> None:
        self._blocked_keywords.discard(keyword.lower().strip())

    def set_blocked_keywords(self, blocked_keywords: Union[List[str], Set[str]]) -> None:
        self._blocked_keywords = {
            kw.lower().strip() for kw in blocked_keywords if kw.strip()
        }

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"\s+", " ", text)
        return text

    @staticmethod
    def _collapse_repeated_chars(s: str) -> str:
        if len(s) < 3:
            return s
        result = []
        count = 1
        for i, ch in enumerate(s):
            if i > 0 and ch == s[i - 1]:
                count += 1
                if count <= 2:
                    result.append(ch)
            else:
                count = 1
                result.append(ch)
        return "".join(result)

    @staticmethod
    def _levenshtein_distance(a: str, b: str) -> int:
        if len(a) < len(b):
            return KeywordMatcher._levenshtein_distance(b, a)
        if len(b) == 0:
            return len(a)
        previous_row = range(len(b) + 1)
        for i, c1 in enumerate(a):
            current_row = [i + 1]
            for j, c2 in enumerate(b):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        return previous_row[-1]

    @staticmethod
    def _is_transposition(a: str, b: str) -> bool:
        if len(a) != len(b) or len(a) < 2:
            return False
        diff = []
        for i, (c1, c2) in enumerate(zip(a, b)):
            if c1 != c2:
                diff.append(i)
        if len(diff) != 2 or diff[1] != diff[0] + 1:
            return False
        i = diff[0]
        return a[i] == b[i + 1] and a[i + 1] == b[i]

    def _is_fuzzy_match(self, word: str, blocked: str) -> bool:
        if word == blocked:
            return True

        word_norm = self._collapse_repeated_chars(word)
        blocked_norm = self._collapse_repeated_chars(blocked)

        if word_norm == blocked_norm:
            return True

        if word_norm in self._false_positives and len(word_norm) == len(blocked_norm):
            return False

        len_diff = abs(len(word_norm) - len(blocked_norm))
        if len_diff > 2:
            return False

        if len(word_norm) == len(blocked_norm) and self._is_transposition(word_norm, blocked_norm):
            return True

        dist = self._levenshtein_distance(word_norm, blocked_norm)
        if dist > 1:
            return False

        if dist == 1:
            if len(word_norm) != len(blocked_norm):
                return True
            if word_norm[0] != blocked_norm[0] or word_norm[-1] != blocked_norm[-1]:
                return False
            matches = sum(1 for c1, c2 in zip(word_norm, blocked_norm) if c1 == c2)
            if matches >= len(blocked_norm) - 1:
                return True
            return False
        return True

    def classify(self, query: str) -> QueryClassification:
        if not query or not query.strip():
            return QueryClassification(
                is_safe=True,
                is_blocked=False,
                matched_keywords=[],
                reason="Empty query",
            )

        normalized_query = self._normalize_text(query)
        matched = []

        for keyword in self._blocked_keywords:
            blocked_norm = self._normalize_text(keyword)

            if blocked_norm in normalized_query:
                if keyword not in matched:
                    matched.append(keyword)
                continue

            tokens = normalized_query.split()
            for token in tokens:
                token_n = self._collapse_repeated_chars(token)
                if token_n in self._false_positives:
                    continue
                if self._is_fuzzy_match(token, blocked_norm):
                    if keyword not in matched:
                        matched.append(keyword)
                    break

            if keyword not in matched:
                no_space = normalized_query.replace(" ", "")
                if self._is_fuzzy_match(no_space, blocked_norm):
                    matched.append(keyword)
                    continue

        is_blocked = len(matched) > 0
        is_safe = not is_blocked

        reason = None
        if is_blocked:
            reason = f"Query contains blocked keyword(s): {', '.join(sorted(set(matched)))}"

        return QueryClassification(
            is_safe=is_safe,
            is_blocked=is_blocked,
            matched_keywords=sorted(set(matched)),
            reason=reason,
        )

    def is_safe(self, query: str) -> bool:
        return self.classify(query).is_safe

    def is_blocked(self, query: str) -> bool:
        return self.classify(query).is_blocked
