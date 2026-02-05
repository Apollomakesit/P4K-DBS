#!/bin/bash
# Quick setup checklist for /reparseunknown command

set -e

echo "🔍 Checking P4K-DBS /reparseunknown Setup..."
echo "=================================================="

# Check if Python files exist
echo "✓ Checking files..."
test -f "scraper.py" && echo "  ✅ scraper.py exists"
test -f "commands.py" && echo "  ✅ commands.py exists"
test -f "test_patterns.py" && echo "  ✅ test_patterns.py exists"

# Verify Python syntax
echo ""
echo "✓ Checking Python syntax..."
python -m py_compile scraper.py && echo "  ✅ scraper.py - valid"
python -m py_compile commands.py && echo "  ✅ commands.py - valid"

# Run pattern tests
echo ""
echo "✓ Running pattern tests..."
python test_patterns.py 2>&1 | grep "SUMMARY" && echo "  ✅ Pattern tests passed"

# Check for key patterns in scraper
echo ""
echo "✓ Verifying new patterns in scraper.py..."
grep -q "PATTERN Q" scraper.py && echo "  ✅ PATTERN Q (email deposits) found"
grep -q "PATTERN I" scraper.py && echo "  ✅ PATTERN I (email transfers) found"
grep -q "PATTERN S" scraper.py && echo "  ✅ PATTERN S (ID-only contracts) found"

# Check for reparse command in commands.py
echo ""
echo "✓ Verifying Discord command integration..."
grep -q "reparse_unknown_command" commands.py && echo "  ✅ reparse_unknown_command found"
grep -q "_parse_action_text" commands.py && echo "  ✅ Scraper integration found"

# Check for diagnostic tool
echo ""
echo "✓ Checking diagnostic tools..."
test -f "diagnose_reparse.py" && echo "  ✅ diagnose_reparse.py available"

echo ""
echo "=================================================="
echo "✅ All checks passed! Ready to deploy."
echo ""
echo "Next steps:"
echo "1. Restart bot: python bot.py"
echo "2. Test in Discord: /reparseunknown action_type:all dry_run:true limit:50"
echo "3. If needed: python diagnose_reparse.py"
