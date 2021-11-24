.. documentation master file, created by
   sphinx-quickstart on Sat Jan 21 19:11:14 2017.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.


======================================================================
greenback: reenter an asyncio or Trio event loop from synchronous code
======================================================================

Python 3.5 introduced ``async``/``await`` syntax for defining
functions that can run concurrently in a cooperative multitasking
framework such as ``asyncio`` or `Trio
<https://trio.readthedocs.io/>`__. Such frameworks have a number of advantages
over previous approaches to concurrency: they scale better than threads and are
`clearer about control flow <https://glyph.twistedmatrix.com/2014/02/unyielding.html>`__
than the implicit cooperative multitasking provided by ``gevent``. They're also being
actively developed to explore some `exciting new ideas about concurrent programming
<https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/>`__.

Porting an existing codebase to ``async``/``await`` syntax can be
challenging, though, since it's somewhat "viral": only an async
function can call another async function. That means you don't just have
to modify the functions that actually perform I/O; you also need to
(trivially) modify every function that directly or indirectly calls a
function that performs I/O. While the results are generally an improvement
("explicit is better than implicit"), getting there in one big step is not
always feasible, especially if some of these layers are in libraries that
you don't control.

``greenback`` is a small library that attempts to bridge this gap. It
allows you to **call back into async code from a syntactically
synchronous function**, as long as the synchronous function was
originally called from an async task (running in an asyncio or Trio
event loop) that set up a ``greenback`` "portal" as explained
below. This is potentially useful in a number of different situations:

* You can interoperate with some existing libraries that are not
  ``async``/``await`` aware, without pushing their work off into
  another thread.

* You can migrate an existing program to ``async``/``await``
  syntax one layer at a time, instead of all at once.

* You can (cautiously) design async APIs that block in places where
  you can't write ``await``, such as on attribute accesses.

``greenback`` requires Python 3.6 or later and an implementation that
supports the ``greenlet`` library. Either CPython or PyPy should work.
There are no known OS dependencies.

Quickstart
----------

* Call ``await greenback.ensure_portal()`` at least once in each async
  task that will be using ``greenback``. (Additional calls in the same
  task do nothing.) You can think of this as creating a portal that
  will be used by future calls to :func:`greenback.await_` in the same
  task.

* Later, use ``greenback.await_(foo())`` as a replacement for
  ``await foo()`` in places where you can't write ``await``.

* For more details and additional helpers, read the rest of this documentation!

Detailed documentation
----------------------

.. toctree::
   :maxdepth: 2

   principle.rst
   reference.rst
   history.rst

====================
 Indices and tables
====================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
* :ref:`glossary`
