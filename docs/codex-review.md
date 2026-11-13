# Automatic Codex review

Repository: Eduardohrs/frequencia-ufmg.

Use native Codex GitHub review, not a paid API workflow or scheduled poller. Settings: https://chatgpt.com/settings/code-review . Enable repository automatic review for **all PRs/authors** and set its review trigger to **every new push** (or the equivalent option displayed in the current UI). Do not change settings for other repositories. Merge remains manual.

Root AGENTS.md contains the repository review rules. It deliberately distinguishes review findings from CI and production validation. These rules do not transfer this chat's private history, credentials or local skills to the cloud reviewer.

## Activation record

On 2026-11-13 the authenticated repository settings accepted and persisted **A cada push** (every push). Personal automatic review was enabled with Eduardo's explicit approval; reopening settings confirmed it remained enabled. Repository review is enabled and follows that preference. Paid-credit overflow remains disabled. Other repositories following the personal preference may also review Eduardo's PRs.

Selecting all PR authors failed with HTTP 400: Reviewing all PRs is not available on this plan. Thus the saved configuration covers the account's eligible PRs, not an entitlement to review every author's PR. Rules are in AGENTS.md; merge this PR to establish them on the default branch. Configuration persistence is verified; a bot review of a subsequent exact head is a separate end-to-end check, not yet confirmed.
Native reviews use the account's code-review entitlement and limits; this setup introduces no API key or separate paid workflow. A review can still be unavailable when account limits or integration access prevent it.

Official reference: https://learn.chatgpt.com/docs/third-party/github
