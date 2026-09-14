"""Automated tests for the install.sh language selection (de/en).

Covers (see task t_289d9151):
  - --help (plain = bilingual, with --lang = that language only)
  - invalid arguments and invalid --lang values
  - --lang without a value
  - non-TTY runs: never block, English default + --lang hint
  - --lang de / --lang en full installs (isolated fake HOME, stubbed tools)
  - interactive picker via pty: Enter = German, 2 = English,
    invalid choice re-prompts, EOF aborts cleanly before installing
  - waybar config.d / manual-include / style append paths in both languages
  - systemd unit installation (stubbed systemctl)
  - idempotent double install

The tests never touch the real user HOME and never invoke real pip:
PATH is prefixed with stub binaries inside a temp sandbox.
"""

import os
import pty
import select
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(REPO, "install.sh")

PYTHON3_STUB = """#!/usr/bin/env bash
# test stub: accepts everything, never touches the real site-packages
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then exit 0; fi
exit 0
"""

SYSTEMCTL_STUB = """#!/usr/bin/env bash
# test stub: pretend a working systemd --user session
[ "$1" = "--user" ] && exit 0
exit 1
"""

WAYBAR_STUB = """#!/usr/bin/env bash
exit 0
"""


def write_stub(directory, name, body):
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write(body)
    os.chmod(path, 0o755)
    return path


class InstallerLangTest(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.mkdtemp(prefix="omarchy-lang-test-")
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.home = os.path.join(self.sandbox, "home")
        os.makedirs(self.home)
        self.stubbin = os.path.join(self.sandbox, "stubbin")
        os.makedirs(self.stubbin)
        write_stub(self.stubbin, "python3", PYTHON3_STUB)

    # -- helpers -----------------------------------------------------------

    def env(self):
        e = dict(os.environ)
        e["HOME"] = self.home
        # only stubs + base system tools; no real pip/waybar/systemctl lookups
        e["PATH"] = self.stubbin + os.pathsep + "/usr/bin:/bin"
        return e

    def run_install(self, args=(), stdin=subprocess.DEVNULL, timeout=60):
        return subprocess.run(
            ["bash", INSTALL] + list(args),
            stdin=stdin, capture_output=True, text=True,
            env=self.env(), timeout=timeout,
        )

    def run_pty(self, feed=b"", args=(), close_immediately=False, timeout=30):
        """Run install.sh with stdin/stdout/stderr on a pty (real TTY)."""
        master, slave = pty.openpty()
        proc = subprocess.Popen(
            ["bash", INSTALL] + list(args),
            stdin=slave, stdout=slave, stderr=slave,
            env=self.env(), close_fds=True,
        )
        os.close(slave)
        if close_immediately:
            os.close(master)
            master = None
        elif feed:
            os.write(master, feed)
        out = b""
        deadline = time.time() + timeout
        while master is not None and time.time() < deadline:
            r, _, _ = select.select([master], [], [], 0.2)
            if r:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
            if proc.poll() is not None:
                while True:  # drain remaining output
                    r2, _, _ = select.select([master], [], [], 0.2)
                    if not r2:
                        break
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    out += chunk
                break
        if master is not None:
            os.close(master)
        try:
            rc = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            rc = "TIMEOUT"
        return rc, out.decode("utf-8", "replace")

    def wrappers_exist(self):
        return all(
            os.path.isfile(os.path.join(self.home, ".local", "bin", n))
            for n in ("omarchy-mercedes", "omarchy-mercedes-waybar")
        )

    # -- help --------------------------------------------------------------

    def test_help_plain_is_bilingual_without_prompt(self):
        r = self.run_install(["--help"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Verwendung:", r.stdout)
        self.assertIn("Usage:", r.stdout)
        self.assertIn("--lang de|en", r.stdout)
        # must not block on the interactive picker
        self.assertNotIn("Sprache waehlen", r.stdout + r.stderr)

    def test_help_lang_de_is_german_only(self):
        r = self.run_install(["--lang", "de", "--help"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("Verwendung:", r.stdout)
        self.assertNotIn("Usage:", r.stdout)

    def test_help_lang_en_is_english_only(self):
        r = self.run_install(["--lang", "en", "--help"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("Usage:", r.stdout)
        self.assertNotIn("Verwendung:", r.stdout)

    def test_help_honors_lang_equals_form(self):
        r = self.run_install(["--lang=en", "--help"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("Usage:", r.stdout)
        self.assertNotIn("Verwendung:", r.stdout)

    # -- invalid input -----------------------------------------------------

    def test_invalid_language_fails_before_installing(self):
        r = self.run_install(["--lang", "fr"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("Unknown language: fr", r.stderr)
        self.assertIn("allowed: de, en", r.stderr)
        self.assertIn("--help", r.stderr)
        self.assertFalse(self.wrappers_exist())

    def test_invalid_argument_fails_with_hint(self):
        r = self.run_install(["--foo"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("Unknown argument: --foo", r.stderr)
        self.assertIn("--help", r.stderr)
        self.assertFalse(self.wrappers_exist())

    def test_lang_without_value_fails(self):
        r = self.run_install(["--lang"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("--lang requires a value", r.stderr)

    # -- non-TTY -----------------------------------------------------------

    def test_non_tty_defaults_to_english_and_never_blocks(self):
        r = self.run_install([])  # stdin = /dev/null, pipes: no TTY
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Next steps:", r.stdout)
        self.assertIn("installing python package (user) ...", r.stdout)
        self.assertNotIn("Naechste Schritte", r.stdout)
        # hint about --lang must point to the German option
        self.assertIn("--lang de", r.stderr)
        self.assertTrue(self.wrappers_exist())

    def test_non_tty_lang_de_full_run(self):
        r = self.run_install(["--lang", "de"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Naechste Schritte:", r.stdout)
        self.assertIn("installiere python-paket (benutzer) ...", r.stdout)
        self.assertIn("systemctl --user start omarchy-mercedes", r.stdout)
        self.assertIn("waybar neu starten (modul 'custom/mercedes')", r.stdout)
        self.assertNotIn("Next steps:", r.stdout)
        self.assertTrue(self.wrappers_exist())

    def test_non_tty_lang_en_full_run(self):
        r = self.run_install(["--lang", "en"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Next steps:", r.stdout)
        self.assertIn("restart waybar (module 'custom/mercedes')", r.stdout)
        self.assertNotIn("Naechste Schritte", r.stdout)
        self.assertTrue(self.wrappers_exist())

    def test_non_tty_without_waybar_warns_in_english(self):
        r = self.run_install(["--lang", "en"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("waybar not found (ok on other hosts)", r.stderr)

    def test_data_dir_permissions(self):
        r = self.run_install(["--lang", "en"])
        self.assertEqual(r.returncode, 0)
        data = os.path.join(self.home, ".local", "share", "omarchy-mercedes")
        self.assertTrue(os.path.isdir(data))
        self.assertEqual(os.stat(data).st_mode & 0o777, 0o700)

    # -- interactive picker (pty) ------------------------------------------

    def test_picker_enter_defaults_to_german(self):
        rc, out = self.run_pty(feed=b"\n")
        self.assertEqual(rc, 0, out)
        self.assertIn("Sprache waehlen", out)
        self.assertIn("Naechste Schritte:", out)
        self.assertNotIn("Next steps:", out)
        self.assertTrue(self.wrappers_exist())

    def test_picker_2_selects_english(self):
        rc, out = self.run_pty(feed=b"2\n")
        self.assertEqual(rc, 0, out)
        self.assertIn("Next steps:", out)
        self.assertNotIn("Naechste Schritte", out)
        self.assertTrue(self.wrappers_exist())

    def test_picker_word_input_accepted(self):
        rc, out = self.run_pty(feed=b"english\n")
        self.assertEqual(rc, 0, out)
        self.assertIn("Next steps:", out)

    def test_picker_invalid_choice_reprompts_then_installs(self):
        rc, out = self.run_pty(feed=b"xyz\n7\n1\n")
        self.assertEqual(rc, 0, out)
        # invalid feedback shown (bilingual, ASCII-safe) ...
        self.assertIn("invalid choice", out)
        # ... and the prompt really appeared again (3 attempts)
        self.assertGreaterEqual(out.count("English  [1]"), 2)
        self.assertIn("Naechste Schritte:", out)
        self.assertTrue(self.wrappers_exist())

    def test_picker_eof_aborts_cleanly_before_installing(self):
        # real Ctrl-D (EOT) on the pty -> read returns EOF
        rc, out = self.run_pty(feed=b"\x04")
        self.assertEqual(rc, 1, out)
        self.assertIn("EOF", out)
        self.assertIn("abgebrochen", out)
        self.assertIn("aborted", out)
        # nothing was installed
        self.assertFalse(self.wrappers_exist())
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local", "state")))

    # -- waybar integration paths ------------------------------------------

    def test_waybar_configd_snippet_german(self):
        write_stub(self.stubbin, "waybar", WAYBAR_STUB)
        wb = os.path.join(self.home, ".config", "waybar")
        # installer requires an existing waybar config before touching anything
        os.makedirs(os.path.join(wb, "config.d"))
        os.makedirs(os.path.join(wb, "style.d"))
        with open(os.path.join(wb, "config.jsonc"), "w") as f:
            f.write('{ "height": 30 }\n')
        r = self.run_install(["--lang", "de"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("installiere waybar-config-snippet (config.d) ...", r.stdout)
        self.assertTrue(os.path.isfile(os.path.join(wb, "config.d", "mercedes.jsonc")))
        self.assertTrue(os.path.isfile(os.path.join(wb, "style.d", "mercedes.css")))

    def test_waybar_manual_include_english_with_backup(self):
        write_stub(self.stubbin, "waybar", WAYBAR_STUB)
        wb = os.path.join(self.home, ".config", "waybar")
        os.makedirs(wb)
        sentinel = '{ "height": 30 }'
        with open(os.path.join(wb, "config.jsonc"), "w") as f:
            f.write(sentinel + "\n")
        with open(os.path.join(wb, "style.css"), "w") as f:
            f.write("/* original */\n")
        r = self.run_install(["--lang", "en"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("automatic include not possible", r.stderr)
        self.assertIn("mercedes.jsonc manually", r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(wb, "mercedes.jsonc")))
        # original config preserved, styles appended, backups created
        with open(os.path.join(wb, "config.jsonc")) as f:
            self.assertTrue(f.read().startswith(sentinel))
        with open(os.path.join(wb, "style.css")) as f:
            css = f.read()
        self.assertIn("/* original */", css)
        self.assertIn("omarchy-mercedes (appended by installer)", css)
        backups = os.path.join(self.home, ".local", "state", "omarchy-mercedes", "backup")
        backed = {n for _, _, files in os.walk(backups) for n in files} if os.path.isdir(backups) else set()
        self.assertIn("config.jsonc", backed)
        self.assertIn("style.css", backed)

    def test_waybar_missing_config_warns(self):
        write_stub(self.stubbin, "waybar", WAYBAR_STUB)
        r = self.run_install(["--lang", "en"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("no waybar config found", r.stderr)

    # -- systemd unit ------------------------------------------------------

    def test_systemd_user_unit_installed_with_home_expanded(self):
        write_stub(self.stubbin, "systemctl", SYSTEMCTL_STUB)
        r = self.run_install(["--lang", "en"])
        self.assertEqual(r.returncode, 0, r.stderr)
        unit = os.path.join(self.home, ".config", "systemd", "user", "omarchy-mercedes.service")
        self.assertTrue(os.path.isfile(unit))
        with open(unit) as f:
            content = f.read()
        self.assertNotIn("%h", content)
        self.assertIn(self.home, content)

    # -- idempotency -------------------------------------------------------

    def test_double_install_is_idempotent(self):
        r1 = self.run_install(["--lang", "en"])
        r2 = self.run_install(["--lang", "de"])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertTrue(self.wrappers_exist())


if __name__ == "__main__":
    unittest.main()
