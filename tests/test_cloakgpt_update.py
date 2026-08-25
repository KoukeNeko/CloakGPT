import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cloakgpt_update


class CloakGPTUpdateTests(unittest.TestCase):
    @patch("cloakgpt_update.certifi.where", return_value="bundled-ca.pem")
    def test_default_ca_bundle_comes_from_certifi(self, where) -> None:
        with patch.dict(os.environ, {}, clear=True):
            bundle = cloakgpt_update._ca_bundle()

        self.assertEqual(bundle, "bundled-ca.pem")
        where.assert_called_once_with()

    def test_ssl_cert_file_overrides_bundled_ca(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "enterprise-ca.pem"
            bundle.write_text("certificate", encoding="ascii")

            with patch.dict(os.environ, {"SSL_CERT_FILE": str(bundle)}, clear=True):
                selected = cloakgpt_update._ca_bundle()

        self.assertEqual(selected, str(bundle))

    def test_url_opener_uses_verified_tls_context(self) -> None:
        request = Mock()
        context = Mock()
        response = Mock()
        with (
            patch("cloakgpt_update._request", return_value=request),
            patch("cloakgpt_update._tls_context", return_value=context),
            patch("cloakgpt_update.urlopen", return_value=response) as open_url,
        ):
            result = cloakgpt_update._open_url("https://example.test", timeout=30)

        self.assertIs(result, response)
        open_url.assert_called_once_with(request, timeout=30, context=context)

    def test_selects_newest_published_prerelease_when_api_order_is_wrong(self) -> None:
        releases = [
            {
                "tag_name": "v0.1.0-pre.9",
                "prerelease": True,
                "draft": False,
                "published_at": "2026-08-25T06:37:26Z",
            },
            {
                "tag_name": "v0.1.0-pre.8",
                "prerelease": True,
                "draft": False,
                "published_at": "2026-08-25T05:56:31Z",
            },
            {
                "tag_name": "v0.1.0-pre.10",
                "prerelease": True,
                "draft": False,
                "published_at": "2026-08-25T07:12:39Z",
            },
            {
                "tag_name": "draft",
                "prerelease": True,
                "draft": True,
                "published_at": "2026-08-25T08:00:00Z",
            },
            {
                "tag_name": "v0.2.0",
                "prerelease": False,
                "draft": False,
                "published_at": "2026-08-25T09:00:00Z",
            },
        ]
        with patch("cloakgpt_update._read_json", return_value=releases) as read:
            release = cloakgpt_update._release_for(
                channel="prerelease",
                version=None,
            )

        self.assertEqual(release["tag_name"], "v0.1.0-pre.10")
        read.assert_called_once_with(f"{cloakgpt_update.API_ROOT}?per_page=100")

    def test_exact_version_uses_tag_endpoint(self) -> None:
        release = {"tag_name": "v1.2.3", "draft": False}
        with patch("cloakgpt_update._read_json", return_value=release) as read:
            result = cloakgpt_update._release_for(channel=None, version="1.2.3")

        self.assertIs(result, release)
        read.assert_called_once_with(f"{cloakgpt_update.API_ROOT}/tags/v1.2.3")

    def test_check_reports_available_without_downloading(self) -> None:
        release = {"tag_name": "v0.1.0-pre.5", "draft": False}
        with (
            patch.object(cloakgpt_update.sys, "frozen", True, create=True),
            patch.object(cloakgpt_update, "ASSET_NAME", "cloakgpt-test"),
            patch.object(cloakgpt_update, "VERSION", "v0.1.0-pre.4"),
            patch.object(cloakgpt_update, "CHANNEL", "prerelease"),
            patch("cloakgpt_update._release_for", return_value=release),
            patch("cloakgpt_update._stage_release") as stage,
        ):
            result = cloakgpt_update.update_cloakgpt(check=True)

        self.assertEqual(result["status"], "update_available")
        self.assertEqual(result["target"], "v0.1.0-pre.5")
        stage.assert_not_called()

    def test_source_checkout_refuses_self_update(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "packaged releases"):
            cloakgpt_update.update_cloakgpt()

    def test_stages_and_verifies_both_digests(self) -> None:
        payload = b"verified executable"
        digest = hashlib.sha256(payload).hexdigest()
        release = {
            "tag_name": "v1.0.0",
            "assets": [
                {
                    "name": "cloakgpt-test",
                    "browser_download_url": "https://example.test/executable",
                    "digest": f"sha256:{digest}",
                },
                {
                    "name": "cloakgpt-test.sha256",
                    "browser_download_url": "https://example.test/checksum",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "cloakgpt"
            target.write_bytes(b"current")

            def download(_url, destination):
                destination.write_bytes(payload)

            with (
                patch.object(cloakgpt_update, "ASSET_NAME", "cloakgpt-test"),
                patch("cloakgpt_update._download_file", side_effect=download),
                patch("cloakgpt_update._download_text", return_value=f"{digest}  file"),
            ):
                staged = cloakgpt_update._stage_release(release, target)

            self.assertEqual(staged.read_bytes(), payload)

    def test_checksum_mismatch_removes_staged_file(self) -> None:
        release = {
            "tag_name": "v1.0.0",
            "assets": [
                {"name": "cloakgpt-test", "browser_download_url": "asset"},
                {
                    "name": "cloakgpt-test.sha256",
                    "browser_download_url": "checksum",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "cloakgpt"
            target.write_bytes(b"current")

            def download(_url, destination):
                destination.write_bytes(b"bad")

            with (
                patch.object(cloakgpt_update, "ASSET_NAME", "cloakgpt-test"),
                patch("cloakgpt_update._download_file", side_effect=download),
                patch("cloakgpt_update._download_text", return_value="0" * 64),
            ):
                with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                    cloakgpt_update._stage_release(release, target)

            self.assertEqual(list(Path(temporary).iterdir()), [target])

    def test_posix_replacement_keeps_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "cloakgpt"
            staged = Path(temporary) / "staged"
            target.write_bytes(b"old")
            staged.write_bytes(b"new")
            completed = subprocess.CompletedProcess(
                [str(target), "--version"],
                0,
                "cloakgpt v1.0.0",
                "",
            )
            with patch("cloakgpt_update.subprocess.run", return_value=completed):
                cloakgpt_update._replace_posix(staged, target, "v1.0.0")

            self.assertEqual(target.read_bytes(), b"new")
            self.assertEqual(list(Path(temporary).iterdir()), [target])

    def test_posix_replacement_rolls_back_failed_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "cloakgpt"
            staged = Path(temporary) / "staged"
            target.write_bytes(b"old")
            staged.write_bytes(b"new")
            failed = subprocess.CompletedProcess(
                [str(target), "--version"],
                1,
                "",
                "failed",
            )
            with patch("cloakgpt_update.subprocess.run", return_value=failed):
                with self.assertRaisesRegex(RuntimeError, "final version check"):
                    cloakgpt_update._replace_posix(staged, target, "v1.0.0")

            self.assertEqual(target.read_bytes(), b"old")
            self.assertEqual(list(Path(temporary).iterdir()), [target])

    def test_windows_replacement_helper_has_no_console(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "cloakgpt.exe"
            staged = Path(temporary) / "staged.exe"
            target.write_bytes(b"old")
            staged.write_bytes(b"new")
            with (
                patch.object(cloakgpt_update.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, create=True),
                patch.object(cloakgpt_update.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
                patch("cloakgpt_update.subprocess.Popen") as popen,
            ):
                cloakgpt_update._schedule_windows_replace(staged, target, "v1.0.0")

            command = popen.call_args.args[0]
            self.assertIn("-WindowStyle", command)
            self.assertIn("Hidden", command)
            self.assertEqual(
                popen.call_args.kwargs["creationflags"],
                0x08000200,
            )
            helper = next(Path(temporary).glob("*.ps1"))
            self.assertIn("Move-Item", helper.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
