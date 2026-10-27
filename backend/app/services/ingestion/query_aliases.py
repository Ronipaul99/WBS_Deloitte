"""Bounded lexical expansion from explicit, document-scoped glossary aliases."""

import re


def expand_alias_terms(terms, heading_paths):
    aliases = {}
    ambiguous = set()
    for path in heading_paths:
        if "GLOSSARY" not in (label.upper() for label in path):
            continue
        for label in path:
            match = re.fullmatch(r"(.{3,120}?)\s+or\s+([A-Z][A-Z0-9]{1,11})", label)
            if match:
                alias = match[2].lower()
                words = tuple(re.findall(r"[^\W_]+", match[1].lower()))
                if alias in aliases and aliases[alias] != words:
                    ambiguous.add(alias)
                else:
                    aliases[alias] = words
    result = list(terms)
    original = set(terms)
    for alias, words in sorted(aliases.items()):
        if alias not in ambiguous and (alias in original or set(words) <= original):
            result.extend([alias, *words])
    return tuple(dict.fromkeys(result))[:64]
