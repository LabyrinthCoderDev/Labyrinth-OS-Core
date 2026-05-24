# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest | ✓ |
| Older | Case by case |

---

## Reporting a Vulnerability

**Do not file public GitHub issues for security vulnerabilities.**

Contact: [@LabyrinthCoder on X](https://x.com/LabyrinthCoder)

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Your suggested fix (if any)

You will receive a response within 72 hours.

---

## Security Model

This system is a constitutional enforcement substrate.
Its security properties are documented in `KNOWN_GAPS.md`.

Key security properties:
- Gate decisions are cryptographically logged (tamper-evident WORM ledger)
- Execution requires gate passage — no bypass path exists in the code
- Z3-proven threshold constants cannot be weakened at runtime
- All proposals are archived before evaluation

Known limitations are documented honestly in `KNOWN_GAPS.md`.

---

*@LabyrinthCoder — sole authority*
