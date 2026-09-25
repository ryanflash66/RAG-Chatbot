"""Document classification: incident taxonomy derived from a Document's relative path.

The path is split into lowercase alphanumeric tokens (the file extension is
dropped). A keyword matches a token exactly; keywords of four or more characters
also match as a token prefix, so "encrypt" matches "encryption" while "ot" never
matches "other" or "notes". Multi-word keywords match consecutive tokens.
When several incident labels match, the most specific keyword wins (more
words, then more characters); ties go to the earlier label in INCIDENT_KEYWORDS.
Content, the absolute path and the repository location never affect the result.
"""

import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Dict, List, Sequence, Tuple

_PREFIX_MIN_LEN = 4

INCIDENT_KEYWORDS: Dict[str, List[str]] = {
    "ransomware": ["ransomware", "encrypt", "crypto"],
    "phishing": ["phishing", "credential", "spearphish", "spoof"],
    "data_breach": ["breach", "exfil", "pii", "leak"],
    "malware": ["malware", "trojan", "worm", "virus", "backdoor", "c2", "command and control"],
    "insider_threat": ["insider", "privilege abuse", "usb", "data theft"],
    "credential_dumping": ["dcsync", "credential dump", "ad attack", "kerberoast", "pass the hash", "mimikatz", "ntds"],
    "supply_chain": ["supply chain", "dependency", "package", "ci cd", "zero day"],
    "ddos": ["ddos", "network attack", "brute force", "botnet", "cryptojack"],
    "iot_ot": ["iot", "ot", "scada", "hvac", "ics"],
}

IR_KEYWORDS: List[str] = [
    "incident",
    "response",
    "playbook",
    "mitre",
    "nist",
    "threat",
    "ransomware",
    "phishing",
    "malware",
    "forensic",
    "siem",
    "edr",
]

ASSET_INVENTORY_KEYWORD = "asset inventory"


@dataclass(frozen=True)
class DocClassification:
    incident_type: str
    doc_domain: str
    asset_scope: str
    tags: str

    def as_metadata(self) -> Dict[str, str]:
        return {
            "incident_type": self.incident_type,
            "doc_domain": self.doc_domain,
            "asset_scope": self.asset_scope,
            "tags": self.tags,
        }


def _tokens(relative_path: PurePath) -> Tuple[str, ...]:
    stem = relative_path.with_suffix("") if relative_path.suffix else relative_path
    return tuple(re.findall(r"[a-z0-9]+", stem.as_posix().lower()))


def _token_matches(keyword_token: str, token: str) -> bool:
    if len(keyword_token) >= _PREFIX_MIN_LEN:
        return token.startswith(keyword_token)
    return token == keyword_token


def _matches(keyword: str, tokens: Sequence[str]) -> bool:
    parts = keyword.split()
    for start in range(len(tokens) - len(parts) + 1):
        window = tokens[start:start + len(parts)]
        # Every token but the last must match exactly; the last may be a prefix.
        if all(a == b for a, b in zip(parts[:-1], window[:-1])) and _token_matches(parts[-1], window[-1]):
            return True
    return False


def _any(keywords: Sequence[str], tokens: Sequence[str]) -> bool:
    return any(_matches(keyword, tokens) for keyword in keywords)


def _best_match(keywords: Sequence[str], tokens: Sequence[str]) -> Tuple[int, int]:
    """Specificity of the longest matching keyword as (words, chars); (0, 0) if none."""
    return max(
        ((len(k.split()), len(k)) for k in keywords if _matches(k, tokens)),
        default=(0, 0),
    )


def classify(relative_path: "str | PurePath") -> DocClassification:
    """Classify a Document by its path relative to the data directory."""
    tokens = _tokens(PurePath(relative_path))

    if _matches(ASSET_INVENTORY_KEYWORD, tokens):
        return DocClassification(
            incident_type="general",
            doc_domain="asset_inventory",
            asset_scope="org_inventory",
            tags="asset,inventory",
        )

    scores = {label: _best_match(keywords, tokens) for label, keywords in INCIDENT_KEYWORDS.items()}
    matched = [label for label, score in scores.items() if score > (0, 0)]
    # Most specific keyword wins; max() keeps the first label (dict order) on ties.
    incident_type = max(matched, key=scores.__getitem__) if matched else "unknown"
    doc_domain = "ir" if _any(IR_KEYWORDS, tokens) else "general"
    tags = matched + (["ir"] if doc_domain == "ir" else [])

    return DocClassification(
        incident_type=incident_type,
        doc_domain=doc_domain,
        asset_scope="unknown",
        tags=",".join(tags) if tags else "none",
    )
