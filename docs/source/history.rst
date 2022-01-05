Release history
===============

.. currentmodule:: greenback

.. towncrier release notes start

greenback 1.1.0 (2022-01-05)
----------------------------

Features
~~~~~~~~

- Added `@greenback.decorate_as_sync() <greenback.decorate_as_sync>`, which wraps
  a synchronous function decorator such as :func:`functools.lru_cache` so that it
  can be used to decorate an async function. (`#14 <https://github.com/oremanj/greenback/issues/14>`__)


Bugfixes
~~~~~~~~

- :func:`greenback.has_portal` now returns False instead of raising an
  error if called outside async context. (`#12 <https://github.com/oremanj/greenback/issues/12>`__)
- :func:`greenback.has_portal` now properly respects its *task* argument;
  previously it erroneously would always inspect the current task. (`#13 <https://github.com/oremanj/greenback/issues/13>`__)


greenback 1.0.0 (2021-11-23)
----------------------------

Features
~~~~~~~~

- New function :func:`greenback.with_portal_run_tree` is like
  :func:`greenback.with_portal_run` for an entire Trio task subtree: it
  will enable :func:`greenback.await_` not only in the given async
  function but also in any child tasks spawned inside that
  function. This feature relies on the Trio instrumentation API and is
  thus unavailable on asyncio. (`#9 <https://github.com/oremanj/greenback/issues/9>`__)
- New function :func:`greenback.has_portal` determines whether the current
  task, or another specified task, has a greenback portal set up already. (`#9 <https://github.com/oremanj/greenback/issues/9>`__)


Bugfixes
~~~~~~~~

- Add support for newer (1.0+) versions of greenlet, which expose a ``gr_context``
  attribute directly, allowing us to remove the hacks that were added to support
  0.4.17. greenlet 0.4.17 is no longer supported, but earlier (contextvar-naive)
  versions should still work. (`#8 <https://github.com/oremanj/greenback/issues/8>`__)
- We no longer assume that :func:`greenback.bestow_portal` is invoked from the
  "main" greenlet of the event loop. This was not a safe assumption: any task
  running with access to a greenback portal runs in a separate greenlet, and
  it is quite plausible that such a task might want to :func:`~greenback.bestow_portal`
  on another task. (`#9 <https://github.com/oremanj/greenback/issues/9>`__)


greenback 0.3.0 (2020-10-13)
----------------------------

Features
~~~~~~~~

- Add :func:`greenback.with_portal_run` and :func:`greenback.with_portal_run_sync`,
  which let you scope the greenback portal (and its performance impact) to
  a single function call rather than an entire task.
  :func:`greenback.with_portal_run_sync` provides somewhat reduced
  portal setup/teardown overhead in cases where the entire function you
  want to provide the portal to is syntactically synchronous. (`#6 <https://github.com/oremanj/greenback/issues/6>`__)


Bugfixes
~~~~~~~~

- Work around a regression introduced by greenlet 0.4.17's attempt at adding
  contextvars support. (`#5 <https://github.com/oremanj/greenback/issues/5>`__)


Documentation improvements
~~~~~~~~~~~~~~~~~~~~~~~~~~

- Add a more detailed discussion of the :ref:`performance impacts <performance>`
  of using `greenback`.


greenback 0.2.0 (2020-06-29)
----------------------------

Features
~~~~~~~~

- Added :func:`greenback.bestow_portal`, which enables greenback for a task from outside
  of that task. (`#1 <https://github.com/oremanj/greenback/issues/1>`__)

- Added support for newer versions of Trio with a `trio.lowlevel` module rather than
  ``trio.hazmat``. Older versions of Trio remain supported.


greenback 0.1.0 (2020-05-02)
----------------------------

Initial release.
