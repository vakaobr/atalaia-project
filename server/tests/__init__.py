# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The site server's tests (unittest, PostgreSQL 16; decision P4R17).

Run in the server's test image by ``python3 tools/docker_server.py test``
(and CI's ``server`` job). ``test_config``, ``test_ids`` and
``test_shared_imports`` need no database and no third-party package, so
tools/check.sh runs them in the atalaia-dev image too. Nothing here may
import a third-party package: that is ``base.py``'s job.
"""
