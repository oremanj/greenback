Principle of operation
======================

This section attempts to confer a basic sense of how `greenback` works.

Async/await basics and limitations
----------------------------------

Python's ``async``/``await`` syntax goes to some lengths to look like
normal straight-line Python code: the async version of some logic
looks pretty similar to the threaded or non-concurrent version, just
with extra ``async`` and ``await`` keywords. Under the hood, though,
an async callstack is represented as something very much like a
generator. When some async function in the framework you're using
needs to suspend the current callstack and run other code for a bit,
it effectively ``yield``\s an object that tells the event loop about
its intentions. The exact nature of these "traps" is a private
implementation detail of the particular framework you're using. For
example, asyncio yields `~asyncio.Future`\s, curio yields specially
formatted tuples, and Trio (currently) yields internal objects
representing the two primitive operations
:func:`~trio.lowlevel.cancel_shielded_checkpoint` and
:func:`~trio.lowlevel.wait_task_rescheduled`.  For much more detail on
how ``async``/``await`` work (more approachably explained, too!), see
the excellent writeup by Brett Cannon: `How the heck does async/await
work in Python 3.5?
<https://snarky.ca/how-the-heck-does-async-await-work-in-python-3-5/>`__

Common to both async functions and generators is the limitation that one
can only directly ``yield`` out of the function containing the ``yield``
statement. If you want the yielded value to propagate multiple levels up the
callstack -- all the way to the event loop, in the async case -- you need
cooperation at each level, in the form of an ``await``
(in an async function) or ``yield from`` (in a generator) statement.
This means every point where execution might be suspended is marked
in the source code, which is a useful property. It also means that adding
some I/O (which might block, thus needs to be able to suspend execution)
at the bottom of a long chain of formerly-synchronous functions requires
adding ``async`` and ``await`` keywords at every level of the chain.
That property is sometimes problematic. To be sure, doing that work can
reveal important bugs (read `Unyielding
<https://glyph.twistedmatrix.com/2014/02/unyielding.html>`__ if you don't
believe it); but sometimes it's just an infeasible amount of work to be
doing all at once in the first place, especially if you need to interoperate
with a large project and/or external dependencies that weren't written to
support ``async``/``await``.

"Reentering the event loop" (letting a regular synchronous function
call an async function using the asynchronous context that exists
somewhere further up the callstack) has therefore been a popular
Python feature request, but unfortunately it's somewhat fundamentally
at odds with how generators and async functions are implemented
internally. The CPython interpreter uses a few levels of the C call
stack to implement each level of the running Python call stack, as is
natural.  The Python frame objects and everything they reference are
allocated on the heap, but the C stack is still used to track the
control flow of which functions called which. Since C doesn't have any
support for suspending and resuming a callstack, Python ``yield``
necessarily turns into C ``return``, and the later resumption of the
generator or async function is accomplished by a fresh C-level call to
the frame-evaluation function (using the same frame object as
before). Yielding out of a 10-level callstack requires 10 times as
many levels of C ``return``, and resuming it requires 10 times as many
new nested calls to the frame evaluation function. This strategy
requires the Python interpreter to be aware of each place where
execution of a generator or async function might be suspended, and
performance and comprehensibility both argue against allowing such
suspensions to occur in every operation.

Sounds like we're out of luck, then. Or are we?

Greenlets: a different approach
-------------------------------

Before Python had async/await or ``yield from``, before it even had
context managers or generators with ``send()`` and ``throw()`` methods,
a third-party package called `greenlet <https://greenlet.readthedocs.io/>`__
provided support for a very different way of suspending a callstack.
This one required no interpreter support or special keyword because it worked
at the C level, copying parts of the C stack to and from the heap in order
to implement suspension and resumption. The approach required deep architecture-specific
magic and elicited a number of subtle bugs, but those have generally been worked out
in the years since the first release in 2006, such that the package is now considered
pretty stable.

The ``greenlet`` package has spawned its own fair share of concurrency frameworks
such as ``gevent`` and ``eventlet``. If those meet your needs, you're welcome
to use them and never give async/await another glance. For our purposes, though,
we're interested in using just the greenlet *primitive*: the ability to
suspend a callstack of ordinary synchronous functions that haven't been marked
with any special syntax.

Using greenlets to bridge the async/sync divide
-----------------------------------------------

From the perspective of someone writing an async function, your code
is the only thing running in your thread until you ``yield`` or
``yield from`` or ``await``, at which point you will be suspended
until your top-level caller (such as the async event loop) sees fit to
resume you.  From the perspective of someone writing an async event
loop, the perspective is reversed: each "step" of the async function
(represented by a ``send()`` call on the coroutine object) cedes
control to an async task until the task feels like yielding control
back to the event loop.  Our goal is to allow something other than a
``yield`` statement to make this ``send()`` call return.

`greenback` achieves this by introducing a "shim" coroutine in
between the async event loop and your task's "real"
coroutine. Whenever the event loop wants to run the next step of your
task, it runs a step of this "shim" coroutine, which creates a
greenlet for running the next step of the underlying "real" coroutine.
This greenlet terminates when the "real" ``send()`` call does
(corresponding to a ``yield`` statement inside your async framework),
but because it's a greenlet, we can also suspend it at a time of our
choosing even in the absence of any ``yield``
statements. :func:`greenback.await_` makes use of that capability by
repeatedly calling ``send()`` on its argument coroutine, using the
greenlet-switching machinery to pass the yielded traps up to the event
loop and get their responses sent back down.

Once you understand the approach, most of the remaining trickery is in
the answer to the question: "how do we install this shim coroutine?"
In Trio you can directly replace `trio.lowlevel.Task.coro` with a
wrapper of your choosing, but in asyncio the ability to modify the
analogous field is not exposed publicly, and on CPython it's not even
exposed to Python at all. It's necessary to use `ctypes` to edit the
coroutine pointer in the C task object, and fix up the reference counts
accordingly. This works well once the details are ironed out. There's
some additional glue to deal with exception propagation, non-coroutine
awaitables, and so forth, but the core of the implementation is not very
much changed from the `gist sketch that originally inspired it
<https://gist.github.com/oremanj/f18ef3e55b9487c2e93eee42232583f2>`__.

What can I do with this, anyway?
--------------------------------

You really can switch greenlets almost anywhere, which means you can
call :func:`greenback.await_` almost anywhere too. For example, you can
perform async operations in magic methods: operator implementations, property
getters and setters, object initializers, you name it. You can use combinators
that were written for synchronous code (`map`, `filter`, `sum`, everything in
`itertools`, and so forth) with asynchronous operations (though they'll still
execute serially within that call -- the only concurrency you obtain is with
other async tasks). You can use libraries that support a synchronous callback,
and actually run async code inside the callback. And when this async code blocks
waiting for something, it will play nice and allow all your other async tasks to run.

You may find `greenback.autoawait` useful in some of these situations: it's
a decorator that turns an async function into a synchronous one. There are also
`greenback.async_context` and `greenback.async_iter` for sync-ifying async
context managers and async iterators, respectively.

If you're feeling reckless, you can even use `greenback` to run
async code in places you might think impossible, such as finalizers
(``__del__`` methods), weakref callbacks, or perhaps even signal
handlers. **This is not recommended** (your async library will not be
happy, to put it mildly, if the signal arrives or GC occurs in the
middle of its delicate task bookkeeping) but it seems that you can
get away with it some reasonable fraction of the time. Don't try these
in production, though!

All of these are fun to play with, but in most situations the
ergonomic benefit is not going to be worth the "spooky action at a
distance" penalty. The real benefits probably come mostly when working
with large established non-async projects. For example, you could
write a pytest plugin that surrounds the entire run in a call to
:func:`trio.run`, with :func:`greenback.await_` used at your leisure
to escape back into a shared async context. Perhaps this could allow
running multiple async tests in parallel in the same thread. At this
point such things are only vague ideas, which may well fail to work
out. The author's hope is that `greenback`  gives you the tool to
pursue whichever ones seem worthwhile to you.


.. _performance:

What's the performance impact?
------------------------------

.. currentmodule:: greenback

Running anything with a greenback portal available incurs some slowdown,
and actually using :func:`await_` incurs some more. The slowdown is not
extreme.

The slowdown due to `greenback` is mostly proportional to the
number of times you yield to the event loop with a portal active, as well
as the number of portal creations and :func:`await_` calls you perform.
You can run the ``microbenchmark.py`` script from the Git repository
to see the numbers on your machine. On a 2020 MacBook Pro (x86), with
CPython 3.9, greenlet 1.1.2, and Trio 0.19.0, I get:

* Baseline: The simplest possible async operation is what Trio calls a
  *checkpoint*: yield to the event loop and ask to immediately be
  rescheduled again.  This takes about **31.5 microseconds** on Trio and
  **28 microseconds** on asyncio.  (asyncio is able to take advantage
  of some C acceleration here.)

* Adding the greenback portal, without making any :func:`await_` calls
  yet, adds about **4 microseconds** per checkpoint.

* Executing each of those checkpoints through a separate
  :func:`await_` adds another **10 microseconds** per :func:`await_` on
  Trio, or **8 microseconds** on asyncio. (Surrounding
  the entire checkpoint loop in a single :func:`await_`, by contrast,
  has negligible impact.)

* Creating a new portal for each of those ``await_(checkpoint())``
  invocations adds another **12 microseconds** or so per portal
  creation. If you don't execute any checkpoints while the portal is
  active, you can create and destroy it in more like **5
  microseconds**.  If you use :func:`with_portal_run_sync`, portal
  creation gets about **3 microseconds** faster.

Keep in mind that these are microbenchmarks: your actual program is
probably not executing checkpoints in a tight loop! The more work
you're doing each time you're scheduled, the less overhead `greenback`
will entail.
