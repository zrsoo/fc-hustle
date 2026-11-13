# FC workspace instructions

## Behavioral verification and evidence integrity

- Never assert hashes or byte identity of source code, test files, instructions,
  configuration, or other mutable implementation files in tests, audit validators,
  or CI. Test behavior and contracts instead, including negative cases.
- Historical source hashes are descriptive provenance only and must not be
  enforced against the current tree. Preserve integrity checks for captured EA
  responses, transaction evidence, immutable experiment logs, and sealed historical
  evidence. Runtime hashes used for identity or correlation remain valid.

## Authorized browser/session recovery

- The user authorizes ordinary recovery in the existing official EA FC Web App
  in Microsoft Edge: bring Edge forward, select the correct Web App tab, refresh
  when needed, click through normal login/continue screens using Edge's saved
  sign-in details, and reattach the appropriate reviewed local extension.
  This includes repeated normal login/continue clicks when EA's flow requires
  them. Do not ask for this authorization again during FC work.
- Use normal browser autofill and UI controls. Never reveal, read out, extract,
  decrypt, copy, export, log, or persist saved credential values, cookies,
  authentication headers, tokens, or session identifiers.
- Leave CAPTCHA, two-factor authentication, security challenges, and missing
  credentials to the user. Do not bypass them or change security policy.
- Verify the intended Edge window/tab and foreground before mouse or keyboard
  input. Use available desktop controls or verified Windows UI automation. A
  worker must check its own desktop/tool access; another session's successful
  clicks do not prove this worker can control Edge. If control fails, report the
  concrete failure and exact minimal manual action rather than claiming recovery.
- Check the required localhost service, start it when absent, attach the correct
  extension, and distinguish attachment from persona validation, authentication,
  and EA market-service success. Verify recovery with only the read-only checks
  allowed by the current objective; respect request pacing and experiment budgets.
- Recovery does not authorize replaying completed windows, resetting consumed
  budgets, duplicating ambiguous commands, expanding an objective's allowed
  account operations, or modifying sealed historical evidence.
- When resuming an existing task after instructions change, explicitly reread
  this file before browser recovery; do not assume session startup instructions
  have refreshed. Preserve the existing objective/task/session and checkpoints.
