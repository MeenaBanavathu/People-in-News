# validators.py

BANNED_WORDS = {
    "taliban", "isis", "al-qaeda", "government", "cabinet",
    "army", "police", "committee", "board", "ministry", "forces"
}

def _contains_banned(text: str) -> bool:
    if not text:
        return True  # treat empty as invalid
    low = text.lower()
    return any(bad in low for bad in BANNED_WORDS)

def is_valid_person_name(name: str) -> bool:
    """
    Valid if:
      - name is non-empty
      - and it does NOT contain any banned words (substring, case-insensitive)
    """
    if not name or not isinstance(name, str):
        return False
    return not _contains_banned(name)

