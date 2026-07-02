# Security Policy

## Supported Versions

Security fixes are released on top of the latest release line:

| Version | Supported          |
| ------- | ------------------ |
| 1.7.x   | :white_check_mark: |
| < 1.7   | :x:                |

## Reporting a Vulnerability

We take the security of aiogzip seriously. If you believe you have found a security vulnerability, please report it to us responsibly.

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via email to:

- **Email**: geoff@keksi.ai
- **Subject**: [SECURITY] aiogzip vulnerability report

### What to Include

Please include the following information in your report:

- Description of the vulnerability
- Steps to reproduce the issue
- Potential impact
- Any suggested fixes (if available)

### Response Timeline

- **Initial Response**: Within 48 hours of receiving your report
- **Status Update**: Within 7 days with an assessment of the report
- **Fix Timeline**: We aim to release security fixes within 30 days for critical issues

### Disclosure Policy

- We request that you give us reasonable time to address the issue before public disclosure
- We will credit you in the security advisory unless you prefer to remain anonymous
- Once a fix is released, we will publish a security advisory on GitHub

## Security Best Practices

When using aiogzip:

1. **Validate Input**: Always validate file paths and data sources before processing
2. **Resource Limits**: Set appropriate limits on file sizes and chunk sizes to prevent resource exhaustion
3. **Error Handling**: Properly handle exceptions to avoid information leakage
4. **Dependencies**: Keep aiogzip and its dependencies up to date

## Known Security Considerations

### Decompression Bombs

Like all compression libraries, aiogzip can be vulnerable to decompression bombs (ZIP bombs). When processing untrusted gzip files, use the built-in `max_decompressed_size` guard — it aborts *during* decompression, before a bomb can expand into memory:

```python
from aiogzip import AsyncGzipFile

MAX_DECOMPRESSED_SIZE = 100 * 1024 * 1024  # 100 MB

async def safe_decompress(filename):
    async with AsyncGzipFile(
        filename, "rb", max_decompressed_size=MAX_DECOMPRESSED_SIZE
    ) as f:
        return await f.read()  # raises OSError once the cap is exceeded
```

The guard applies to every read path (full reads, chunked reads, line iteration) and to both the binary and text classes. Additional hardening options:

- Consider implementing timeouts for decompression operations on untrusted input
- `strict_size=True` (write side) refuses to produce members whose ISIZE field would silently truncate at 4 GiB

## Contact

For general security questions or concerns, please contact:

- Email: geoff@keksi.ai
- GitHub: https://github.com/geoff-davis/aiogzip/issues

Thank you for helping keep aiogzip and its users safe!
