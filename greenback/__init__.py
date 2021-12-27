"""Top-level package for greenback."""

from ._version import __version__
from ._impl import (
    ensure_portal,
    bestow_portal,
    has_portal,
    with_portal_run,
    with_portal_run_sync,
    with_portal_run_tree,
    await_,
)
from ._util import autoawait, decorate_as_sync, async_context, async_iter
