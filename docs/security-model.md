# Security model

What CloakGPT trusts, what it does not, and where it keeps your data.


CloakGPT is a local user-level CLI, not a sandbox or an authorization service.
It intentionally controls a signed-in ChatGPT browser profile and can send
messages. A user or agent permitted to execute `cloakgpt` under the same
operating-system account is therefore trusted to operate that profile only
within the authority the user granted.

Persistent session IDs select local conversations; they are not ChatGPT
credentials or daemon authentication keys. The daemon uses a separate random
authentication key stored in the CloakGPT data directory. On POSIX systems,
metadata files containing that key are written with mode `0600`. The browser
profile, daemon metadata, session IDs, and conversation URLs should still be
treated as sensitive local data and must not be committed or published.

Official installers download a platform asset and its `.sha256` file from the
project's GitHub Release, then verify the checksum before installation. macOS
release assets are Developer ID signed and notarized. Windows assets are not
currently code-signed, so Windows may display a warning. CloakBrowser is a
separately downloaded external binary governed by its own license and security
boundary; see [Install a release](../README.md#install-a-release) and
[Disclaimer](legal.md).

## User data

Packaged executables store the persistent browser profile and last conversation
URL in the platform's user data directory:

| Platform | Default data directory |
| --- | --- |
| Linux | `$XDG_DATA_HOME/CloakGPT`, or `~/.local/share/CloakGPT` |
| macOS | `~/Library/Application Support/CloakGPT` |
| Windows | `%LOCALAPPDATA%\CloakGPT` |

Set `CLOAKGPT_DATA_DIR` to override this location. Source checkouts retain the
original behavior and store data in the repository unless the environment
variable is set.
