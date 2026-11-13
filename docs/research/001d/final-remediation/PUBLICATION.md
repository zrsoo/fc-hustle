# Publication verification

The remediation and its evidence were committed on `main` as `72b4cb7`.
The staged whitespace check found two trailing spaces in the verbatim intermediate
unittest output, on subtest headings in `python-after-first-repair.txt`.

Those captured bytes and their evidence hash are preserved. `.gitattributes`
disables whitespace lint only for that exact transcript. Source files retain the
repository's whitespace checks. The full publication diff is checked again before
push. No functional test, source-integrity assertion, live operation, or historical
evidence was changed by this publication adjustment.

The final implementation checks remain the 23 passing commands in
`offline-delivery/checks.json`: 467 Python tests, 15 Node contract scripts and the
independent validators. The supplemental publication record does not change any
previously sealed report, manifest, capture, checkpoint, receipt or test output.
