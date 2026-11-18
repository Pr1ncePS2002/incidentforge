# Fail fast on incomplete or placeholder TLS certificate settings

Miniflux can serve HTTPS directly from a certificate and private key on disk, set with `CERT_FILE` and `KEY_FILE`. The HTTP server only turns TLS on when **both** values are non-empty. If an operator sets only one of them, leaves one blank, or ships a deployment template where a value is still a placeholder like `changethis`, Miniflux starts anyway. In the half-configured case it quietly serves plain HTTP. In the placeholder case it fails later, when it tries to load a file that doesn't exist. Either way the problem shows up far from its cause.

Make the configuration check reject these settings, so the service refuses to start.

## Requirements

1. `Validate() error` on the parsed configuration options (package `internal/config`, method on `*configOptions`) must return an error when `CERT_FILE` or `KEY_FILE` is set to a non-blank value but the other one is missing, empty or whitespace only. Setting either one makes the pair required.
2. If at least one of the two is set, `Validate()` must also reject a value in either setting that is still a template placeholder. Compare case-insensitively after trimming surrounding whitespace. At minimum, treat these as placeholders: `changethis`, `changeme`, `todo`, `tbd`, `fixme`, `placeholder`, `xxx`, and any value wrapped in angle brackets such as `<fill-me>`. A real path that only contains one of these words (for example `/etc/todo/cert.pem`) is not a placeholder.
3. Collect every problem in the pair into **one** error, and name each offending key (`CERT_FILE` and/or `KEY_FILE`) in its message. If only one key is bad, the message must name only that key and must not mention the other one.
4. If neither `CERT_FILE` nor `KEY_FILE` is set (the shipped default), nothing changes. When both are set to real values, validation passes. The checks `Validate()` already performs keep working.
5. The existing test suite still passes.

---

The repository is checked out at `/app`. Run the test suite with `run_tests` (it accepts the usual test runner arguments).
