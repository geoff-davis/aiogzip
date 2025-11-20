# Development Notes for Claude Code

This document contains important reminders and best practices for maintaining the aiogzip library.

## Python 3.8 Compatibility Checklist

**IMPORTANT:** This library supports Python 3.8+. Always check for PEP 585 compatibility before committing!

### Type Hints - Python 3.8 Compatibility

Python 3.8 does NOT support PEP 585 (using built-in types for generics). Always use `typing` module imports:

#### ❌ DON'T (Python 3.9+ only)

```python
def function() -> tuple[int, int]:
    pass

def function() -> list[str]:
    pass

def function() -> dict[str, int]:
    pass
```

#### ✅ DO (Python 3.8+ compatible)

```python
from typing import Tuple, List, Dict

def function() -> Tuple[int, int]:
    pass

def function() -> List[str]:
    pass

def function() -> Dict[str, int]:
    pass
```

### Pre-commit Checklist

Before committing code changes, verify:

1. **Type hints compatibility:**

   ```bash
   grep -r "tuple\[" src/
   grep -r "list\[" src/
   grep -r "dict\[" src/
   grep -r "set\[" src/
   ```

   All should return no results! Use `Tuple`, `List`, `Dict`, `Set` from `typing` instead.

2. **Run tests locally:**

   ```bash
   pytest --cov --cov-report=term-missing
   ```

   Ensure all 173+ tests pass with good coverage.

3. **Check imports:**

   ```python
   from typing import Tuple, List, Dict, Set, Optional, Union, Any
   ```

   Make sure these are imported if used.

## Test Coverage Best Practices

- **Current coverage:** 86.74% (173 tests)
- **Target:** Maintain or improve coverage
- Always add tests for new features
- Document edge cases with descriptive test names

### Test Organization

Tests are organized by priority:

- `TestHighPriorityEdgeCases` - Security & data integrity
- `TestMediumPriorityEdgeCases` - Robustness
- `TestLowPriorityEdgeCases` - Defensive validations
- `TestNewlineHandlingBugs` - Specific bug fixes

## Known Issues & Gotchas

### Newline Handling

- CRLF sequences can split across chunk boundaries
- Must track `_trailing_cr` state to prevent `\r\n` → `\n\n`
- Use `_get_line_terminator_pos()` helper for newline-aware searching

### Unicode Handling

- Multibyte characters can split across buffers
- Use `_safe_decode_with_remainder()` to handle incomplete sequences
- Different encodings have different max incomplete byte counts

### Error Handling

- Always wrap zlib errors in OSError with descriptive messages
- Use `from e` for proper exception chaining
- Test both expected (zlib.error) and unexpected (RuntimeError) error paths

## CI/CD Notes

The project uses GitHub Actions which tests against Python 3.8, 3.9, 3.10, 3.11, 3.12, and 3.13.

**Any Python 3.9+ only syntax will fail CI!**

Common causes of CI failures:

- PEP 585 type hints (most common)
- PEP 604 union operator (`X | Y` instead of `Union[X, Y]`)
- Match statements (Python 3.10+)
- Dictionary merge operators (`|` for dicts, Python 3.9+)

## Useful Commands

```bash
# Run tests with coverage
pytest --cov --cov-report=term-missing --cov-report=html

# Check for Python 3.8 incompatibilities
grep -rn "tuple\[" src/
grep -rn "list\[" src/
grep -rn "dict\[" src/

# Run specific test class
pytest tests/test_aiogzip.py::TestNewlineHandlingBugs -v

# Check typing with mypy (if configured)
mypy src/aiogzip.py
```

## Commit Message Format

Use conventional commit style:

```
Fix/Add/Update: Short description

Detailed description of what changed and why.

Fixes: #123
```

Always include:

- 🤖 Generated with [Claude Code](https://claude.com/claude-code)
- Co-Authored-By: Claude <noreply@anthropic.com>

## Version History

- **0.3** - Major refactoring, binary/text separation
- **Current (Unreleased)** - Bug fixes, test improvements, Python 3.8 compatibility

---

**Last Updated:** 2024-11-14
**Maintainer Notes:** Keep this file updated with new gotchas and best practices!
