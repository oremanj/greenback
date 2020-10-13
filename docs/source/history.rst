Release history
===============

.. currentmodule:: greenback

.. towncrier release notes start

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
