#!/usr/bin/env python3
"""Debug test for deposit email pattern"""

import re

def test_pattern(name, pattern, text):
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        print(f"✅ {name}: {match.group()}")
        return True
    else:
        print(f"❌ {name}")
        return False

test_text = "Jucatorul[email protected](137592) a depozitat suma de 61.000.000$ (taxa 610.000$)."

print(f"Test text: {test_text}\n")

# Test individual parts
test_pattern("Jucatorul", r"Jucatorul", test_text)
test_pattern("Email part only", r"[^\s(]+@[^\s(]+", test_text)
test_pattern("Email part with spec", r"([a-z0-9]+)@([a-z0-9.]+)", test_text)

# Test with brackets removed
test_text_no_brackets = test_text.replace("[", "").replace("]", "")
print(f"\nWithout brackets: {test_text_no_brackets}")
test_pattern("Email part (no brackets)", r"[^\s(]+@[^\s(]+", test_text_no_brackets)

# The actual text might have special encoding
print(f"\nCharacter analysis of bracket area:")
bracket_start = test_text.find("[")
bracket_end = test_text.find("]")
print(f"Bracket content bytes: {test_text[bracket_start:bracket_end+1]}"       )
print(f"Repr: {repr(test_text[bracket_start:bracket_end+1])}")

