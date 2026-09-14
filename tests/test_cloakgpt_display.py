import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cloakgpt_display


class HasGraphicalDisplayTests(unittest.TestCase):
    def test_linux_needs_x11_or_wayland(self) -> None:
        self.assertFalse(cloakgpt_display.has_graphical_display({}, "Linux"))
        self.assertTrue(
            cloakgpt_display.has_graphical_display({"DISPLAY": ":0"}, "Linux")
        )
        self.assertTrue(
            cloakgpt_display.has_graphical_display(
                {"WAYLAND_DISPLAY": "wayland-0"},
                "Linux",
            )
        )

    def test_other_platforms_always_have_a_desktop(self) -> None:
        self.assertTrue(cloakgpt_display.has_graphical_display({}, "Darwin"))
        self.assertTrue(cloakgpt_display.has_graphical_display({}, "Windows"))


class SelectBackendTests(unittest.TestCase):
    def _select(self, requested, binaries, paths):
        return cloakgpt_display.select_backend(
            requested,
            which=lambda name: f"/usr/bin/{name}" if name in binaries else None,
            exists=lambda path: path in paths,
        )

    TIGERVNC_BINARIES = {"Xtigervnc", "websockify"}
    TIGERVNC_PATHS = {cloakgpt_display.NOVNC_WEB_DIR / "vnc.html"}
    KASMVNC_PATHS = {cloakgpt_display.KASMVNC_WEB_DIR}

    def test_auto_prefers_tigervnc(self) -> None:
        backend = self._select(
            "auto",
            self.TIGERVNC_BINARIES | {"Xvnc"},
            self.TIGERVNC_PATHS | self.KASMVNC_PATHS,
        )

        self.assertEqual(backend, "tigervnc")

    def test_auto_falls_back_to_kasmvnc(self) -> None:
        self.assertEqual(self._select("auto", {"Xvnc"}, self.KASMVNC_PATHS), "kasmvnc")

    def test_tigervnc_xvnc_alternative_is_not_kasmvnc(self) -> None:
        with self.assertRaises(cloakgpt_display.RemoteDisplayError) as error:
            self._select("kasmvnc", {"Xvnc", "Xtigervnc"}, set())

        self.assertIn("kasmvnc is not installed", str(error.exception))

    def test_tigervnc_needs_novnc_web_client(self) -> None:
        with self.assertRaises(cloakgpt_display.RemoteDisplayError):
            self._select("tigervnc", self.TIGERVNC_BINARIES, set())

    def test_missing_backends_explain_installation(self) -> None:
        with self.assertRaises(cloakgpt_display.RemoteDisplayError) as error:
            self._select("auto", set(), set())

        self.assertIn(
            "sudo apt install tigervnc-standalone-server novnc websockify",
            str(error.exception),
        )


class DisplayAllocationTests(unittest.TestCase):
    def test_free_display_skips_sockets_and_locks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            socket_dir = Path(temp) / ".X11-unix"
            socket_dir.mkdir()
            (socket_dir / "X100").touch()
            (Path(temp) / ".X101-lock").touch()

            display = cloakgpt_display.free_display(socket_dir, Path(temp))

        self.assertEqual(display, 102)

    def test_free_port_skips_busy_and_excluded_ports(self) -> None:
        port = cloakgpt_display.free_port(
            6100,
            is_free=lambda candidate: candidate != 6100,
            exclude=(6101,),
        )

        self.assertEqual(port, 6102)

    def test_free_port_reports_exhaustion(self) -> None:
        with self.assertRaises(cloakgpt_display.RemoteDisplayError):
            cloakgpt_display.free_port(6100, is_free=lambda _candidate: False)


class CommandTests(unittest.TestCase):
    def test_tigervnc_listens_on_loopback_only(self) -> None:
        server, proxy = cloakgpt_display.tigervnc_commands(100, 6100, 5999, (1280, 800))

        self.assertEqual(
            server,
            [
                "Xtigervnc", ":100",
                "-rfbport", "5999",
                "-interface", "127.0.0.1",
                "-SecurityTypes", "None",
                "-AlwaysShared",
                "-geometry", "1280x800",
                "-depth", "24",
                "-nolisten", "tcp",
            ],
        )
        self.assertEqual(
            proxy,
            [
                "websockify",
                "--web", "/usr/share/novnc",
                "127.0.0.1:6100",
                "127.0.0.1:5999",
            ],
        )

    def test_kasmvnc_serves_only_its_web_viewer(self) -> None:
        (server,) = cloakgpt_display.kasmvnc_commands(101, 6101, (1280, 800))

        self.assertEqual(
            server,
            [
                "Xvnc", ":101",
                "-websocketPort", "6101",
                "-rfbport", "-1",
                "-interface", "127.0.0.1",
                "-SecurityTypes", "None",
                "-DisableBasicAuth",
                "-AlwaysShared",
                "-geometry", "1280x800",
                "-depth", "24",
                "-httpd", "/usr/share/kasmvnc/www",
            ],
        )

    def test_viewer_urls(self) -> None:
        self.assertEqual(
            cloakgpt_display.viewer_url("tigervnc", 6100),
            "http://127.0.0.1:6100/vnc.html?autoconnect=1&resize=remote",
        )
        self.assertEqual(
            cloakgpt_display.viewer_url("kasmvnc", 6100),
            "http://127.0.0.1:6100/",
        )

    def test_display_env_keeps_environment_and_drops_wayland(self) -> None:
        env = cloakgpt_display.display_env(
            100,
            {"HOME": "/root", "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"},
        )

        self.assertEqual(env, {"HOME": "/root", "DISPLAY": ":100"})

    def test_packaged_build_restores_the_callers_library_path(self) -> None:
        env = cloakgpt_display.display_env(
            100,
            {
                "LD_LIBRARY_PATH": "/tmp/_MEIabc:/opt/lib",
                "LD_LIBRARY_PATH_ORIG": "/opt/lib",
            },
            frozen=True,
        )

        self.assertEqual(env, {"LD_LIBRARY_PATH": "/opt/lib", "DISPLAY": ":100"})

    def test_packaged_build_drops_library_path_it_added(self) -> None:
        env = cloakgpt_display.system_env(
            {"HOME": "/root", "LD_LIBRARY_PATH": "/tmp/_MEIabc"},
            frozen=True,
        )

        self.assertEqual(env, {"HOME": "/root"})

    def test_source_run_keeps_library_path(self) -> None:
        environ = {"LD_LIBRARY_PATH": "/opt/lib", "LD_LIBRARY_PATH_ORIG": "/x"}

        self.assertEqual(cloakgpt_display.system_env(environ, frozen=False), environ)

    def test_browser_args_fill_the_virtual_screen(self) -> None:
        display = cloakgpt_display.RemoteDisplay(
            backend="tigervnc",
            display=100,
            port=6100,
            viewer_url="http://127.0.0.1:6100/",
            env={},
            geometry=(1280, 800),
        )

        self.assertEqual(
            display.browser_args,
            ["--window-position=0,0", "--window-size=1280,800"],
        )


class ProcessLifecycleTests(unittest.TestCase):
    def _process(self, returncode=None) -> Mock:
        process = Mock()
        process.poll.return_value = returncode
        process.returncode = returncode
        return process

    def test_wait_until_ready_needs_socket_and_viewer_port(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            socket_dir = Path(temp)
            accepts = Mock(side_effect=[False, True])
            sleeps = []

            def sleep(seconds):
                sleeps.append(seconds)
                (socket_dir / "X100").touch()

            cloakgpt_display.wait_until_ready(
                [("Xtigervnc", self._process(), None)],
                100,
                6100,
                socket_dir=socket_dir,
                accepts=accepts,
                sleep=sleep,
            )

        self.assertEqual(len(sleeps), 2)
        self.assertEqual(accepts.call_count, 2)

    def test_wait_until_ready_reports_early_exit_with_log(self) -> None:
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
            log.write("Fatal server error: could not open default font\n")
            with self.assertRaises(cloakgpt_display.RemoteDisplayError) as error:
                cloakgpt_display.wait_until_ready(
                    [("Xtigervnc", self._process(1), log)],
                    100,
                    6100,
                    socket_dir=Path("/nonexistent"),
                    sleep=lambda _seconds: None,
                )

        self.assertIn("Xtigervnc exited with code 1", str(error.exception))
        self.assertIn("could not open default font", str(error.exception))

    def test_wait_until_ready_times_out(self) -> None:
        times = iter([0.0, 5.0, 11.0])

        with self.assertRaises(cloakgpt_display.RemoteDisplayError) as error:
            cloakgpt_display.wait_until_ready(
                [("Xtigervnc", self._process(), None)],
                100,
                6100,
                socket_dir=Path("/nonexistent"),
                clock=lambda: next(times),
                sleep=lambda _seconds: None,
            )

        self.assertIn("did not become ready within 10 seconds", str(error.exception))

    def test_stop_processes_in_reverse_and_kills_stragglers(self) -> None:
        order = []
        server = self._process()
        server.terminate.side_effect = lambda: order.append("server")
        proxy = self._process()
        proxy.terminate.side_effect = lambda: order.append("proxy")
        proxy.wait.side_effect = [subprocess.TimeoutExpired("websockify", 5), 0]
        exited = self._process(0)

        cloakgpt_display.stop_processes(
            [("Xtigervnc", server, None), ("websockify", proxy, None), ("x", exited, None)]
        )

        self.assertEqual(order, ["proxy", "server"])
        proxy.kill.assert_called_once_with()
        server.kill.assert_not_called()
        exited.terminate.assert_not_called()

    @patch("cloakgpt_display.platform.system", return_value="Darwin")
    def test_remote_display_requires_linux(self, _system) -> None:
        with self.assertRaises(cloakgpt_display.RemoteDisplayError) as error:
            with cloakgpt_display.open_remote_display():
                pass

        self.assertIn("only available on Linux", str(error.exception))

    @patch("cloakgpt_display.wait_until_ready")
    @patch("cloakgpt_display.subprocess.Popen")
    @patch("cloakgpt_display.port_is_free", return_value=True)
    @patch("cloakgpt_display.free_display", return_value=100)
    @patch("cloakgpt_display.select_backend", return_value="tigervnc")
    @patch("cloakgpt_display.platform.system", return_value="Linux")
    def test_open_remote_display_stops_processes_after_the_block(
        self,
        _system,
        _select_backend,
        _free_display,
        _port_is_free,
        popen,
        wait_until_ready,
    ) -> None:
        processes = [self._process(), self._process()]
        popen.side_effect = processes

        with patch.dict("os.environ", {"HOME": "/root"}, clear=True):
            with cloakgpt_display.open_remote_display(port=6200) as display:
                self.assertEqual(display.env, {"HOME": "/root", "DISPLAY": ":100"})
                self.assertEqual(display.port, 6200)
                for process in processes:
                    process.terminate.assert_not_called()

        self.assertEqual([call.args[0][0] for call in popen.call_args_list], ["Xtigervnc", "websockify"])
        self.assertEqual(popen.call_args_list[1].args[0][-2], "127.0.0.1:6200")
        self.assertEqual(popen.call_args.kwargs["env"], {"HOME": "/root"})
        wait_until_ready.assert_called_once()
        for process in processes:
            process.terminate.assert_called_once_with()

    @patch("cloakgpt_display.port_is_free", return_value=False)
    @patch("cloakgpt_display.free_display", return_value=100)
    @patch("cloakgpt_display.select_backend", return_value="kasmvnc")
    @patch("cloakgpt_display.platform.system", return_value="Linux")
    def test_open_remote_display_rejects_busy_requested_port(self, *_mocks) -> None:
        with self.assertRaises(cloakgpt_display.RemoteDisplayError) as error:
            with cloakgpt_display.open_remote_display(port=6100):
                pass

        self.assertIn("port 6100 is already in use", str(error.exception))


class SshTunnelHintTests(unittest.TestCase):
    def test_uses_the_address_the_client_connected_to(self) -> None:
        hint = cloakgpt_display.ssh_tunnel_hint(
            6100,
            {"SSH_CONNECTION": "192.168.50.10 51234 192.168.50.250 22"},
            user="root",
        )

        self.assertEqual(hint, "ssh -N -L 6100:127.0.0.1:6100 root@192.168.50.250")

    def test_adds_non_default_ssh_port(self) -> None:
        hint = cloakgpt_display.ssh_tunnel_hint(
            6101,
            {"SSH_CONNECTION": "10.0.0.2 51234 10.0.0.1 2222"},
            user="kouke",
        )

        self.assertEqual(hint, "ssh -N -L 6101:127.0.0.1:6101 -p 2222 kouke@10.0.0.1")

    def test_placeholder_outside_ssh(self) -> None:
        hint = cloakgpt_display.ssh_tunnel_hint(6100, {}, user="root")

        self.assertEqual(hint, "ssh -N -L 6100:127.0.0.1:6100 root@<this-server>")


if __name__ == "__main__":
    unittest.main()
