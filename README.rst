greenback: reenter an asyncio or Trio event loop from synchronous code
======================================================================

.. image:: https://img.shields.io/pypi/v/greenback.svg
   :target: https://pypi.org/project/greenback
   :alt: Latest PyPI version

.. image:: https://img.shields.io/badge/docs-read%20now-blue.svg
   :target: https://greenback.readthedocs.io/en/latest/?badge=latest
   :alt: Documentation status

.. image:: https://travis-ci.org/oremanj/greenback.svg?branch=master
   :target: https://travis-ci.org/oremanj/greenback
   :alt: Automated test status

.. image:: https://codecov.io/gh/oremanj/greenback/branch/master/graph/badge.svg
   :target: https://codecov.io/gh/oremanj/greenback
   :alt: Test coverage

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
   :target: https://github.com/ambv/black
   :alt: Code style: black

.. image:: http://www.mypy-lang.org/static/mypy_badge.svg
   :target: http://www.mypy-lang.org/
   :alt: Checked with mypy


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

* Call ``await greenback.ensure_portal()`` at least once in each task that will be
  using ``greenback``. (Additional calls in the same task do nothing.) You can think
  of this as creating a portal that will be used by future calls to
  ``greenback.await_()`` in the same task.

* Later, use ``greenback.await_(foo())`` as a replacement for
  ``await foo()`` in places where you can't write ``await``.

* For more details and additional helper methods, see the
  `documentation <https://greenback.readthedocs.io>`__.

Example
-------

Suppose you start with this async-unaware program::

    import subprocess

    def main():
        print_fact(10)

    def print_fact(n, mult=1):
        """Print the value of *n* factorial times *mult*."""
        if n <= 1:
            print_value(mult)
        else:
            print_fact(n - 1, mult * n)

    def print_value(n):
        """Print the value *n* in an unreasonably convoluted way."""
        assert isinstance(n, int)
        subprocess.run(f"echo {n}", shell=True)

    if __name__ == "__main__":
        main()

Using ``greenback``, you can change it to run in a Trio event loop by
changing only the top and bottom layers, with no change to ``print_fact()``. ::

    import trio
    import greenback

    async def main():
        await greenback.ensure_portal()
        print_fact(10)

    def print_fact(n, mult=1):
        """Print the value of *n* factorial times *mult*."""
        if n <= 1:
            print_value(mult)
        else:
            print_fact(n - 1, mult * n)

    def print_value(n):
        """Print the value *n* in an unreasonably convoluted way."""
        assert isinstance(n, int)
        greenback.await_(trio.run_process(f"echo {n}", shell=True))

    if __name__ == "__main__":
        trio.run(main)

FAQ
---

**Why is it called "greenback"?** It uses the `greenlet
<https://greenlet.readthedocs.io/en/latest/>`__ library to get you
*back* to an enclosing async context. Also, maybe it saves you `money
<https://www.dictionary.com/browse/greenback>`__ (engineering time) or
something.

**How does it work?** After you run ``await greenback.ensure_portal()``
in a certain task, each step of that task will run inside a greenlet.
(This is achieved by interposing a "shim" coroutine in between the event
loop and the coroutine for your task; see the source code for details.)
Calls to ``greenback.await_()`` are then able to switch from that greenlet
back to the parent greenlet, which can easily perform the necessary
``await`` since it has direct access to the async environment. The
per-task-step greenlet is then resumed with the value or exception
produced by the ``await``.

**Should I trust this in production?** Maybe; try it and see. The
technique is in some ways an awful hack, and has some performance
implications (any task in which you call ``await
greenback.ensure_portal()`` will run somewhat slower), but we're in
good company: SQLAlchemy's async ORM support is implemented in much
the same way.  ``greenback`` itself is a fairly small amount of
pure-Python code on top of ``greenlet``.  (There is one reasonably
safe ctypes hack that is necessary to work around a knob that's not
exposed by the asyncio acceleration extension module on CPython.)
``greenlet`` is a C module full of arcane platform-specific hacks, but
it's been around for a very long time and popular production-quality
concurrency systems such as ``gevent`` rely heavily on it.

**What won't work?** A few things:

* Greenlet switching works by moving parts of the C stack to different
  memory addresses, relying on the assumption that Python objects are
  fully heap-allocated and don't contain any pointers into the C
  stack. Poorly-behaved C extension modules might violate this
  assumption and are likely to crash if used with ``greenback``.
  Such extension modules are buggy and could be made to crash without
  ``greenback`` too, but perhaps only under an obscure or unlikely
  series of operations.

* Calling ``greenback.await_()`` inside a finalizer (``__del__``
  method), signal handler, or weakref callback is unsupported. It
  might work most of the time, or even all the time, but the
  environment in which such methods run is weird enough that the
  author isn't prepared to make any guarantees.  (Not that you have
  any guarantees about the rest of it, just some better theoretical
  grounding.)


License
-------

``greenback`` is licensed under your choice of the MIT or Apache 2.0 license.
See `LICENSE <https://github.com/oremanj/greenback/blob/master/LICENSE>`__
for details.
