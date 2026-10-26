# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Pi controller and the phone controller give the same version.

    cd controller && python -m unittest discover -s tests

Both answer /healthz and /whoami with their version: the Pi its
``__version__``, the phone the app's (app/lib/version.dart, kept equal to
pubspec.yaml by app/test/version_test.dart). The phone's once said 0.2.0
where the Pi said 0.3.0.
"""
import re
import unittest

import atalaia_controller

from support import REPO


class VersionTests(unittest.TestCase):
    def test_the_phone_controller_gives_the_pi_controllers_version(self) -> None:
        dart = (REPO / "app" / "lib" / "version.dart").read_text(encoding="utf-8")
        m = re.search(r"^const appVersion = '([^']+)';", dart, re.MULTILINE)
        self.assertIsNotNone(m, "no appVersion in app/lib/version.dart")
        self.assertEqual(m.group(1), atalaia_controller.__version__)


if __name__ == "__main__":
    unittest.main()
