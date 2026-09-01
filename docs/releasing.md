# Releasing

Maintainer runbook. Publishing happens by pushing a `v*` tag, which builds
every platform, runs the smoke tests, and creates the GitHub release. A tag
containing `-` is published as a prerelease.

## macOS release signing


The two macOS jobs require these GitHub Actions repository secrets:

| Secret | Value |
| --- | --- |
| `MACOS_CERTIFICATE_P12_BASE64` | Base64-encoded Developer ID Application `.p12` |
| `MACOS_CERTIFICATE_PASSWORD` | Password used when exporting the `.p12` |
| `APPLE_API_KEY_P8_BASE64` | Base64-encoded App Store Connect API key |
| `APPLE_API_KEY_ID` | App Store Connect API key ID |
| `APPLE_API_ISSUER_ID` | App Store Connect API issuer ID |

The workflow imports the certificate into a temporary keychain, passes its
SHA-1 identity to PyInstaller so embedded one-file binaries are signed, submits
the signed executable to Apple's notary service, and removes all temporary
signing material before the job ends. Secret values must never be committed to
the repository.

The bundled Playwright Node driver uses V8 JIT compilation. PyInstaller applies
the minimal exceptions in `macos-entitlements.plist` while signing the collected
executables: `com.apple.security.cs.allow-jit` and
`com.apple.security.cs.allow-unsigned-executable-memory`. Each release job
starts the packaged Playwright driver after signing, verifies both entitlements,
and only then submits the macOS executable for notarization.
