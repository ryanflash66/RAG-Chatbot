"""Tests for Document classification (rag.classify), keyed on relative paths."""

import pytest

from rag.classify import classify


@pytest.mark.parametrize("relative_path,incident_type,doc_domain", [
    ("seed_ransomware_playbook.md", "ransomware", "ir"),
    ("seed_phishing_playbook.md", "phishing", "ir"),
    ("seed_malware_playbook.md", "malware", "ir"),
    ("threat_intel.pdf", "unknown", "ir"),
    ("report.docx", "unknown", "general"),
    ("general_security_summary.md", "unknown", "general"),
    # Substring false positives from the old implementation
    ("K-Maps Lecture Notes page.pdf", "unknown", "general"),
    ("other/notes.md", "unknown", "general"),
    ("hotfix_rollout.md", "unknown", "general"),
    # Word-level matches
    ("OT network segmentation.md", "iot_ot", "general"),
    ("command-and-control beacons.md", "malware", "general"),
    ("pass_the_hash.md", "credential_dumping", "general"),
    ("ci-cd hardening.md", "supply_chain", "general"),
    # Keywords of 4+ chars also match as a prefix
    ("file encryption event.md", "ransomware", "general"),
    ("incidents/2024 q1.md", "unknown", "ir"),
])
def test_incident_type_and_domain(relative_path, incident_type, doc_domain):
    result = classify(relative_path)
    assert result.incident_type == incident_type
    assert result.doc_domain == doc_domain


def test_directory_names_count():
    assert classify("ransomware/overview.md").incident_type == "ransomware"


@pytest.mark.parametrize("relative_path", ["asset_inventory.json", "asset-inventory.md", "cmdb/Asset Inventory 2024.csv"])
def test_asset_inventory(relative_path):
    result = classify(relative_path)
    assert result.doc_domain == "asset_inventory"
    assert result.asset_scope == "org_inventory"
    assert result.incident_type == "general"
    assert result.tags == "asset,inventory"


def test_tags_list_every_match_plus_ir():
    result = classify("ransomware_phishing_playbook.md")
    assert result.incident_type == "ransomware"
    assert result.tags == "ransomware,phishing,ir"


def test_no_match_tags_none():
    assert classify("readme.md").tags == "none"


def test_extension_is_not_a_token():
    # ".ot" would otherwise read as the token "ot"
    assert classify("diagram.ot").incident_type == "unknown"


@pytest.mark.parametrize("relative_path,incident_type", [
    ("credential_dump.md", "credential_dumping"),
    ("pass_the_hash_credential.md", "credential_dumping"),
    ("cryptojacking miners.md", "ddos"),
    ("ransomware_phishing_playbook.md", "ransomware"),
])
def test_most_specific_keyword_wins(relative_path, incident_type):
    assert classify(relative_path).incident_type == incident_type


def test_equal_specificity_goes_to_earlier_label():
    # "worm" (malware) and "hvac" (iot_ot) are both one word of four chars
    assert classify("hvac worm.md").incident_type == "malware"
