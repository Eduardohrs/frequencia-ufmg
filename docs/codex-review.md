# Automatic Codex review

Repository: Eduardohrs/frequencia-ufmg.

Use native Codex GitHub review, not a paid API workflow or scheduled poller. Settings: https://chatgpt.com/settings/code-review . Enable repository automatic review for **all PRs/authors** and set its review trigger to **every new push** (or the equivalent option displayed in the current UI). Do not change settings for other repositories. Merge remains manual.

Root AGENTS.md contains the repository review rules. It deliberately distinguishes review findings from CI and production validation. These rules do not transfer this chat's private history, credentials or local skills to the cloud reviewer.

## Activation record

On 2026-11-13 the authenticated repository settings accepted and persisted the trigger **A cada push** (every push); reopening the page confirmed it. Selecting all PR authors failed with HTTP 400: Reviewing all PRs is not available on this plan. Repository review remains enabled but follows personal preferences; personal automatic review is currently off. Enabling that preference requires user confirmation because other repositories also follow it. Therefore automatic review is NOT yet end-to-end enabled. Do not claim activation from this documentation or the saved trigger alone. After authorization, verify a subsequent PR push receives a review of its exact head and record the evidence.

Native reviews use the account's code-review entitlement and limits; this setup introduces no API key or separate paid workflow. A review can still be unavailable when account limits or integration access prevent it.

Official reference: https://learn.chatgpt.com/docs/third-party/github

