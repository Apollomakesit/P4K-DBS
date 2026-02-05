#!/usr/bin/env python3
"""Test contract pattern variations for test #11"""

import re

text11 = "Contract Mihai(137922)[email protected](137592). ('137922' [], '137592' [Bravado Harger 69, ])"

# Try different contract patterns
patterns = [
    (
        "Complex alternation",
        r"Contract\s*(?:(\[[^\]]+\]|[^\s(]+@[^\s(]+)\((\d+)\)|(.+?)\((\d+)\))\s+(?:(\[[^\]]+\]|[^\s(]+@[^\s(]+)\((\d+)\)|(.+?)\((\d+)\))(?:\.|$)",
    ),
    (
        "Simple two parts",
        r"Contract\s+(.+?)\((\d+)\)\s*(\[[^\]]+\]|[^\s(]+@[^\s(]+)\((\d+)\)",
    ),
    (
        "Name OR email for both",
        r"Contract\s+(?:(.+?)|(\[[^\]]+\]|[^\s(]+@[^\s(]+))\((\d+)\)\s+(?:(.+?)|(\[[^\]]+\]|[^\s(]+@[^\s(]+))\((\d+)\)",
    ),
    ("Greedy approach", r"Contract\s+(.+)\((\d+)\)(.+?)\((\d+)\)"),
]

for name, pattern in patterns:
    match = re.search(pattern, text11, re.IGNORECASE)
    if match:
        groups = match.groups()
        print(f"✅ {name}")
        print(f"   Groups: {groups}")
        # Show which groups have values
        non_none = [(i, g) for i, g in enumerate(groups) if g]
        print(f"   Non-None: {non_none}")
    else:
        print(f"❌ {name}")
