import re
import secrets

# No 0/O/1/I so codes survive being read aloud or typed from a screenshot
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_RE = re.compile(rf"^[A-Z]{{3}}-[{ALPHABET}]{{3}}$")


def make_code(destination: str) -> str:
    letters = re.sub(r"[^A-Za-z]", "", destination).upper()
    prefix = (letters + "XXX")[:3]
    return f"{prefix}-{''.join(secrets.choice(ALPHABET) for _ in range(3))}"
