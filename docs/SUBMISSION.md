# Submission: README Lie Detector

- Repo: https://github.com/Velu2k03/readme-lie-detector
- Live report (Vercel): https://readme-lie-detector-report.vercel.app/
- Demo video (unlisted YouTube): PENDING, needs upload from Velu's browser. Local file: `docs/video/readme-lie-detector-demo-v4.mp4` (1920x1080, 2:09, Casper 1.2x voice, stakes-first hook)

## Paragraph

README Lie Detector reads a web app's README, picks out the sentences a browser can test, and checks each one in a real Chrome window with Kane CLI. Every claim gets a verdict (verified, false claim, stale doc, inconclusive or not verifiable) and screenshot evidence in one static report. It is built for developers who write the README first and want it kept honest, and for AI coding agents that are told the README is the spec. The agent is Claude Code: a Stop hook runs the cheap `rld gate`, and when a claim is false it blocks Claude Code from finishing and tells it which README line failed and what Kane saw, so the agent changes the code instead of the README. Kane CLI is the part that does the real checking: it drives the browser from a plain-language objective, records the steps and screenshots, and returns the value it observed, which a second check compares to the value the README expected. The demo app, Hati, has eight claims and all eight verify.

## Dogfood, stated plainly

- GitHub Pages report: 3 claims verified, exit 0 (commit c45f4a5).
- Earlier Vercel run: 4 of 5 verified, the fifth was a label casing artifact in the README, since fixed.
- Final Vercel run: 3 verified, 2 not run because the 3-run credit cap was reached (exit 3). Not a failure of a claim, and not a green gate.
