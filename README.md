# ShellHacks
FIU ShellHacks 2026 

The tool

A lightweight web-vuln scanner for AI-generated ("vibe-coded") apps. It scans a codebase, finds the security flaws LLMs typically ship, explains the impact, shows how an attacker would use each one, and hands back a copy-ready fix. Built to make security cheap and accessible for people who can't afford an enterprise tool or a security team.

Sponsor fit — Microsoft

Delivered as a GitHub PR check that comments findings inline. Microsoft owns GitHub and Copilot, so "we make Copilot's output safe to ship" is a native fit. Use Azure OpenAI as the LLM brain to check their AI box (swap to Gemini if we target Google instead).

Social-good angle

The people shipping vibe-coded apps are students, solo founders, and nonprofits with no security budget. They're the ones who leak user data without knowing it. We protect the users of software built by people who can't afford Snyk. Lightweight = cheap to run, easy to deploy, and it lowers the cost of security while promoting secure practices.

How it works
Scan the target repo (paste a GitHub URL for the core; fake/real PR comment for the demo).
Detect code weaknesses with Semgrep, plus a dependency scan for known-vulnerable libraries.
Classify each finding against the right framework:
Code weaknesses → CWE + OWASP Top 10 (e.g. CWE-89 SQL Injection, OWASP A03)
Vulnerable dependencies → CVE + CVSS score (via pip-audit / npm audit)
Map to MITRE ATT&CK — show what an attacker would actually do with each flaw (e.g. T1190 Exploit Public-Facing Application). This replaces "threat actor" attribution, which we can't credibly claim.
Visualize the attack path — a narrated diagram of the chain (exposed endpoint → injection → data dump). This is a visualization, not real exploitation.
Explain impact in plain English for a non-security dev.
Fix — the exact corrected code as a copy-ready block, with a one-line how-to. No auto-commit.
Output

A clean report per scan: threat map (findings + ATT&CK), how each issue affects the app, and how to fix it. One lightweight summary view for the demo, not a heavy dashboard.

Build priority
Core (must work): scan → find → classify (CWE/OWASP) → explain impact → copy-ready fix.
Wow layer (bolt on after core works): dependency CVE scan, MITRE ATT&CK mapping, visual attack-path walkthrough.

Don't let the wow layer put the core at risk. A polished scan-and-fix beats a half-broken threat map.

Demo

Push a deliberately vulnerable sample app → watch it get flagged, mapped, and fixed live. Ship a broken sample repo so the demo never depends on the wifi.
