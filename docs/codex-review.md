# Automatic Codex review

Repository: Eduardohrs/frequencia-ufmg.

Use native Codex GitHub review, not a paid API workflow or scheduled poller. Settings: https://chatgpt.com/settings/code-review . Enable repository automatic review for **all PRs/authors** and set its review trigger to **every new push** (or the equivalent option displayed in the current UI). Do not change settings for other repositories. Merge remains manual.

Root AGENTS.md contains the repository review rules. It deliberately distinguishes review findings from CI and production validation. These rules do not transfer this chat's private history, credentials or local skills to the cloud reviewer.

## Activation record

Pending authenticated settings access as of 2026-11-13. Preparing/merging this documentation alone does not enable native automatic reviews. After saving settings, verify persistence by reopening the repository settings, then verify a real PR opening and subsequent push each receive a review of the corresponding head. Record PR/review URLs and SHAs here before declaring end-to-end activation verified.

Native reviews use the account's code-review entitlement and limits; this setup introduces no API key or separate paid workflow. A review can still be unavailable when account limits or integration access prevent it.

Official reference: https://learn.chatgpt.com/docs/third-party/github
