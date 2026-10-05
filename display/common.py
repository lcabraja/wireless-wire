"""Safe short labels shared by status collection and rendering."""
import unicodedata


def clean(value):
    return "".join(c for c in str(value) if not unicodedata.category(c).startswith("C"))[:80]
