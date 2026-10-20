# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import sys

if sys.argv[1:2] == ["scenario"]:
    # python -m atalaia_controller scenario validate|check|compile scenario.yaml: the scenario
    # compiler (atalaia_controller.scenarios), which needs no settings file.
    from .scenarios.cli import main as scenario_main

    sys.exit(scenario_main(sys.argv[2:]))

from .main import main  # noqa: E402

sys.exit(main())
