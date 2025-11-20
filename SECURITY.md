# Security Policy

## Supported Versions

We actively support the following versions of aiogzip with security updates:

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| 0.4.x   | :x:                |
| < 0.4   | :x:                |

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

Like all compression libraries, aiogzip can be vulnerable to decompression bombs (ZIP bombs). When processing untrusted gzip files:

- Set reasonable limits on decompressed output size
- Monitor memory usage
- Consider implementing timeouts for decompression operations

Example defensive code:

```python
import asyncio
from aiogzip import AsyncGzipFile

MAX_DECOMPRESSED_SIZE = 100 * 1024 * 1024  # 100 MB

async def safe_decompress(filename):
    total_size = 0
    async with AsyncGzipFile(filename, "rb") as f:
        while True:
            chunk = await f.read(8192)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > MAX_DECOMPRESSED_SIZE:
                raise ValueError("Decompressed size exceeds limit")
```

## Contact

For general security questions or concerns, please contact:

- Email: geoff@keksi.ai
- GitHub: https://github.com/geoff-davis/aiogzip/issues

Thank you for helping keep aiogzip and its users safe!
