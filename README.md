# ShellHacks
FIU ShellHacks 2026 

--
Plan

Microsoft — the AI-code security scanner (your main idea)

Semgrep + Gemini/Azure OpenAI triage that catches the vulns LLM-generated code ships with, delivered as a GitHub PR check that comments findings inline with plain-English explanations and one-click fixes. Microsoft owns GitHub and Copilot, so "we make Copilot's output safe to ship" is a native fit, not a stretch, and Azure OpenAI checks their AI box.

Social-good angle: the people shipping vibe-coded apps are students, solo founders, and nonprofits with no security budget and no security team. They're the ones who'll leak user data without knowing. You're protecting the users of software built by people who can't afford Snyk.

Why it wins: empty category, instantly legible problem, and the PR-check demo (push vulnerable code, watch it get flagged and fixed live) is clean.

-
Claude API - Simulate attacks depending on vulnerability analysis.

- integrate Claude to be able to test or scan website for matching flags according to NVD CSS/CVE framework.
- create detailed report with graph, map, images of simulation with a how to fix situation.
- Important to map to threat actors.

Thinking about being a light weight for small companies, decreases price of security while promoting secure health.

