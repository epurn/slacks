"""Root pytest configuration: pin the suite to the ``test`` environment.

``Settings`` refuses to construct while the auth secret is still the placeholder
published in this repository, in every environment except ``test`` (FTY-448).
``app.main`` builds its module-level ASGI app at import time, so the opt-in has
to be in place *before* the first application import — earlier than
``tests/conftest.py``, which imports ``app.main`` itself. The rootdir conftest is
loaded first, which makes this the only spot that is reliably early enough.

The value is forced rather than defaulted so the suite runs the same way whatever
``SLACKS_ENVIRONMENT`` a developer happens to have exported. Tests that exercise
other environments build their own ``Settings`` from an explicit env map and are
unaffected by this process-level value.
"""

from __future__ import annotations

import os

os.environ["SLACKS_ENVIRONMENT"] = "test"
