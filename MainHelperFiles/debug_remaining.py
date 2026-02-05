#!/usr/bin/env python3
"""Debug remaining test failures"""

import re

# Test #7
text7 = (
    "Jucatorul sasuke (192)(209261) a depozitat suma de 131.000.000$ (taxa 1.310.000$)."
)
pattern7_flexible = r"Jucatorul\s+(.+?)\((\d+)\)\s+a\s+depozitat\s+suma\s+de\s+([\d.,]+)\s*(?:\(de\))?\s*\$\s*\(taxa\s+([\d.,]+)\$\)"

# Test #11
text11 = "Contract Mihai(137922)[email protected](137592). ('137922' [], '137592' [Bravado Harger 69, ])"
pattern11_contract = r"Contract\s*(?:(\[[^\]]+\]|[^\s(]+@[^\s(]+)\((\d+)\)|(.+?)\((\d+)\))\s+(?:(\[[^\]]+\]|[^\s(]+@[^\s(]+)\((\d+)\)|(.+?)\((\d+)\))(?:\.|$)"

print("TEST #7: sasuke (192) deposit")
print(f"Text: {text7}")
match7 = re.search(pattern7_flexible, text7, re.IGNORECASE)
if match7:
    print(f"✅ Flexible deposit pattern matches: {match7.groups()}")
else:
    print("❌ Flexible deposit pattern does NOT match")

    # Debug step by step
    if re.search(r"Jucatorul\s+", text7):
        print("   ✅ 'Jucatorul ' matches")
    if re.search(r"(.+?)\(\d+\)", text7):
        m = re.search(r"(.+?)\(\d+\)", text7)
        print(f"   ✅ '.+?\\(\\d+\\)' matches: '{m.group(1)}'")
    if re.search(r"a\s+depozitat", text7, re.IGNORECASE):
        print("   ✅ 'a depozitat' matches")

print("\n" + "=" * 80 + "\n")
print("TEST #11: Contract with email")
print(f"Text: {text11}")
match11 = re.search(pattern11_contract, text11, re.IGNORECASE)
if match11:
    print(f"✅ Contract email pattern matches: {match11.groups()}")
else:
    print("❌ Contract email pattern does NOT match")

    # Test simpler contract patterns
    patterns_to_try = [
        ("Simple contract start", r"Contract\s+.+?\((\d+)\)"),
        ("Contract with email bracket", r"Contract\s+.+?\]\((\d+)\)"),
        ("Contract with email OR name", r"Contract\s+(\[[^\]]+\]|.+?)\((\d+)\)"),
    ]

    for name, pat in patterns_to_try:
        m = re.search(pat, text11, re.IGNORECASE)
        if m:
            print(f"   ✅ {name}: {m.groups()}")
        else:
            print(f"   ❌ {name}")
