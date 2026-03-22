# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in spektr, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, use [GitHub's private security advisory feature](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) to report it.

## Scope

Security issues we care about:

- **Log injection**: Malicious data in log messages that could exploit log consumers
- **Sensitive data exposure**: Accidental logging of secrets, tokens, or credentials
- **Denial of service**: Inputs that cause excessive memory usage or CPU consumption
- **Code execution**: Any path that allows arbitrary code execution through spektr's API
