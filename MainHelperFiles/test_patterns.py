#!/usr/bin/env python3
"""Test script to verify that problematic actions are now properly parsed"""

import asyncio
from datetime import datetime
from scraper import Pro4KingsScraper

# Test action texts from the user
test_actions = [
    (
        "Test #1",
        "Mihai (137922) ia transferat suma de 7.500.000 (de) $ lui[email protected](137592) [IN MANA]",
        "money_transfer",
    ),
    (
        "Test #2",
        "Mihai (137922) ia transferat suma de 3.000.000 (de) $ lui[email protected](137592) [IN MANA]",
        "money_transfer",
    ),
    (
        "Test #3",
        "Mihai (137922) ia transferat suma de 21.000.000 (de) $ lui[email protected](137592) [IN MANA]",
        "money_transfer",
    ),
    (
        "Test #4",
        "Jucatorul[email protected](137592) a depozitat suma de 61.000.000$ (taxa 610.000$).",
        "money_deposit",
    ),
    (
        "Test #5",
        "Jucatorul[email protected](137592) a depozitat suma de 43.000.000$ (taxa 430.000$).",
        "money_deposit",
    ),
    (
        "Test #6",
        "Jucatorul[email protected](137592) a depozitat suma de 21.000.000$ (taxa 210.000$).",
        "money_deposit",
    ),
    (
        "Test #7",
        "Jucatorul sasuke (192)(209261) a depozitat suma de 131.000.000$ (taxa 1.310.000$).",
        "money_deposit",
    ),
    (
        "Test #8",
        "Jucatorul Ioan Glont(56894) a achizitionat Casa Nr. 95 de la jucatorul cu ID 173608 pentru suma de 500.000.000$.",
        "property_bought",
    ),
    (
        "Test #9",
        "Jucatorul (221001) a depozitat suma de 2.781.647$ (taxa 27.816$).",
        "money_deposit",
    ),
    (
        "Test #10",
        "Contract[email protected](137592) Mihai(137922). ('137592' [Bravado Harger 69, ], '137922' [])",
        "vehicle_contract",
    ),
    (
        "Test #11",
        "Contract Mihai(137922)[email protected](137592). ('137922' [], '137592' [Bravado Harger 69, ])",
        "vehicle_contract",
    ),
    (
        "Test #12",
        "Contract (131960) Crissu(168172). ('131960' [Issi Weeny XC, ], '168172' [])",
        "vehicle_contract",
    ),
    (
        "Test #13",
        "Administratorul Tipic(184) ia scos un avertisment jucatorului defuse (199104).",
        "warning_removed",
    ),
    (
        "Test #14",
        "Administratorul Elcheliuta(65) ia scos un avertisment jucatorului 19bada(178277).",
        "warning_removed",
    ),
]


async def test_patterns():
    """Test all patterns"""
    async with Pro4KingsScraper(max_concurrent=1) as scraper:
        results = []

        for test_name, text, expected_type in test_actions:
            parsed = scraper._parse_action_text(text, datetime.now())

            if parsed:
                success = parsed.action_type == expected_type
                status = "✅" if success else "⚠️"
                result = {
                    "test": test_name,
                    "text": text[:60] + "...",
                    "expected": expected_type,
                    "actual": parsed.action_type,
                    "status": status,
                    "success": success,
                }
            else:
                result = {
                    "test": test_name,
                    "text": text[:60] + "...",
                    "expected": expected_type,
                    "actual": "None (not parsed)",
                    "status": "❌",
                    "success": False,
                }

            results.append(result)

        # Print results
        print("\n" + "=" * 120)
        print("PATTERN TEST RESULTS")
        print("=" * 120)

        for result in results:
            print(
                f"{result['status']} {result['test']}: {result['expected']} -> {result['actual']}"
            )
            if not result["success"]:
                print(f"   Input: {result['text']}")

        # Summary
        successful = sum(1 for r in results if r["success"])
        total = len(results)
        print("\n" + "=" * 120)
        print(
            f"SUMMARY: {successful}/{total} patterns recognized successfully ({successful*100//total}%)"
        )
        print("=" * 120 + "\n")

        return successful == total


if __name__ == "__main__":
    success = asyncio.run(test_patterns())
    exit(0 if success else 1)
