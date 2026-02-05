#!/usr/bin/env python3
"""Debug pattern matching with brackets"""

import re

test_text = "Jucatorul[email protected](137592) a depozitat suma de 61.000.000$ (taxa 610.000$)."

# Try different patterns
patterns = [
    (
        "Original with brackets",
        r"Jucatorul\s*(\[?[^\s()\[\]]+@[^\s()\[\]]+\]?)\((\d+)\)\s+a\s+depozitat",
    ),
    ("Simple bracket email", r"Jucatorul(\[[^\]]+\])\((\d+)\)\s+a\s+depozitat"),
    (
        "Bracket email OR normal email",
        r"Jucatorul(\[[^\]]+\]|[^\s(]+@[^\s(]+)\((\d+)\)\s+a\s+depozitat",
    ),
    ("Bracket email with groups", r"Jucatorul(\[\w+@\w+\])\((\d+)\)\s+a\s+depozitat"),
    (
        "Full deposit pattern simple",
        r"Jucatorul(\[[^\]]+\])\((\d+)\)\s+a\s+depozitat\s+suma\s+de\s+([\d.,]+)\$\s*\(taxa\s+([\d.,]+)\$\)",
    ),
]

for name, pattern in patterns:
    match = re.search(pattern, test_text, re.IGNORECASE)
    if match:
        print(
            f"✅ {name}: {match.group(1)}"
            + (f" (groups: {match.groups()})" if len(match.groups()) > 1 else "")
        )
    else:
        print(f"❌ {name}")
