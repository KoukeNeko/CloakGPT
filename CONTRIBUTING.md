# Contributing

Running CloakGPT from a source checkout, and the tests and build that every
change has to pass.

## Run from source

Python 3.11 is required; CI builds and tests on that version only. Use a
virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python cloakgpt.py login
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python cloakgpt.py login
```

## Test and build

The tests mock the browser and do not send messages to ChatGPT:

```sh
python -m unittest discover -s tests -v
```

Build the executable for the current operating system and CPU architecture:

```sh
python -m pip install -r requirements.txt -r requirements-build.txt
python -m PyInstaller --clean --noconfirm cloakgpt.spec
```

The result is written to `dist/`. PyInstaller builds for the host platform, so
the GitHub Actions matrix uses a native runner for each supported target.

`.github/workflows/ci.yml` runs tests on Linux, macOS, and Windows for every
push and pull request. `.github/workflows/release.yml` can be run manually to
produce downloadable workflow artifacts. Pushing a version tag builds all six
executables, generates checksum files, and publishes a GitHub release:

```sh
git tag v1.0.0
git push origin v1.0.0
```

Publishing a release, including macOS signing and notarization, is described
in [Releasing](docs/releasing.md).
