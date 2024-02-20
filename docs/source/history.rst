Release history
===============

.. currentmodule:: greenback

.. towncrier release notes start

greenback 1.2.1 (2024-02-20)
----------------------------

Bugfixes
~~~~~~~~

- greenback now uses deferred evaluation for its type hints. This resolves an
  incompatibility with less-than-bleeding-edge versions of `outcome` that was
  inadvertently introduced in the 1.2.0 release. (`#30 <https://github.com/oremanj/greenback/issues/30>`__)


greenback 1.2.0 (2024-02-07)
----------------------------

With this release, greenback now requires at least Python 3.8.

Features
~~~~~~~~

- greenback's internals have been reorganized to improve the performance of
  executing ordinary checkpoints (``await`` statements, approximately) in
  a task that has a greenback portal active. On the author's laptop with
  CPython 3.12, the overhead is only about one microsecond compared to the
  performance without greenback involved, versus four microseconds before
  this change. For comparison, the non-greenback cost of executing a
  checkpoint is 12-13 microseconds. (`#26 <https://github.com/oremanj/greenback/issues/26>`__)

Bugfixes
~~~~~~~~

- greenback now properly handles cases where a task spawns another greenlet
  (not managed by greenback) that in turn calls :func:`greenback.await_`.
  This improves interoperability with other greenback-like systems that do not
  use the greenback library, such as SQLAlchemy's async ORM support. (`#22 <https://github.com/oremanj/greenback/issues/22>`__)
- :func:`greenback.has_portal` now returns False if run in a task that has called
  :func:`greenback.bestow_portal` on itself but has not yet made the portal
  usable by executing a checkpoint. This reflects the fact that
  :func:`greenback.await_` in such a task will fail. The exception message for
  such an :func:`~greenback.await_` failure has also been updated to more
  precisely describe the problem, rather than the previous generic "you must
  create a portal first". (`#26 <https://github.com/oremanj/greenback/issues/26>`__)


greenback 1.1.2 (2023-12-28)
----------------------------

Bugfixes
~~~~~~~~

- Public exports now use ``from ._submod import X as X`` syntax so that type checkers will know
  they're public exports. (`#23 <https://github.com/oremanj/greenback/pull/23>`__)


greenback 1.1.1 (2023-03-01)
----------------------------

Bugfixes
~~~~~~~~

- :func:`greenback.has_portal` now returns False, instead of raising an error, if it is
  called within an asyncio program in a context where no task is running (such as a file
  descriptor readability callback). (`#16 <https://github.com/oremanj/greenback/issues/16>`__)
- Fixed a bug that could result in inadvertent sharing of context variables. Specifically,
  when one task that already had a greenback portal set up called
  :func:`greenback.bestow_portal` on a different task, the second task could wind up
  sharing the first task's `contextvars` context. (`#17 <https://github.com/oremanj/greenback/issues/17>`__)


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
