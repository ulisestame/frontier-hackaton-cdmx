"""Across runs, people already published keep their pseudonyms in entities.json.

Uses the small sample corpus (data/ is gitignored; the tests skip without it).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anon.core import pipeline as P
from anon.parse import load_corpus

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample" / "input"
pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="sample corpus not present")


def test_a_person_who_gives_a_new_email_keeps_the_published_one(tmp_path):
    eng, ids, *_, ents1, _ = P.anonymize_corpus(load_corpus(SAMPLE), tmp_path)
    P.save_state(tmp_path, eng, ids)
    grown = load_corpus(SAMPLE)
    said = next(m for m in grown.chats if m.get("_user") and not m.get("_is_bot") and "@" in m.get("text", ""))
    grown.chats.append({**said, "id": "new-mail-1", "ts": "1785779999.000100", "attachments": [],
                        "text": "Ah, y mi correo nuevo es 2manuela.castano@hotmail.com"})
    eng2, _, chats2, *_, ents2, _ = P.anonymize_corpus(grown, tmp_path)
    before = {e["entity_id"]: e for e in ents1}
    after = {e["entity_id"]: e for e in ents2}
    owner = next(k for k, e in after.items() if "new-mail-1" in e.get("records", []))
    pid = next(p for p, eid in ids.items() if eid == owner)
    # precondition: the new pseudonym e-mail (it keeps the leading digit) sorts first, so a plain
    # alphabetical choice would switch to it
    assert min(eng2.persons[pid].rendered["email"]) != before[owner]["pseudonyms"]["email"]
    assert after[owner]["pseudonyms"] == before[owner]["pseudonyms"]
    assert "2manuela.castano@hotmail.com" not in json.dumps(chats2, ensure_ascii=False)
