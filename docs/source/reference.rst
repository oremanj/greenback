API reference
=============

Creating a portal
-----------------

.. module:: greenback

In order to use `greenback` in a particular async task, you must first create
a greenback *portal* for that task to use. You may choose between:

* :func:`ensure_portal`: Create a portal to be used by the current task,
  which lasts for the lifetime of that task. Use case: minimally invasive
  code change to allow :func:`greenback.await_` in a particular task.

* :func:`bestow_portal`: Create a portal to be used by some other specified task,
  which lasts for the lifetime of that task. Use case: debugging and introspection
  tools, such as writing a Trio instrument that makes *all* tasks (or all tasks
  in a particular nursery) support :func:`await_` from the start.

* :func:`with_portal_run`: Run an async function (in the current task)
  that might eventually make calls to :func:`await_`, with a portal
  available for at least the duration of that call. Use case: less "magical"
  than :func:`ensure_portal`; keeps the portal (and its perforamnce impact)
  scoped to just the portion of a task that needs it.

* :func:`with_portal_run_sync`: Run a synchronous function (in the
  current task) that might eventually make calls to :func:`await_`,
  with a portal available for at least the duration of that call.
  Use case: same as :func:`with_portal_run`, but the implementation is
  simpler and will be a bit faster (probably only noticeable if the
  function you're running is very short).

.. autofunction:: ensure_portal
.. autofunction:: bestow_portal
.. autofunction:: with_portal_run
.. autofunction:: with_portal_run_sync


Using the portal
----------------

Once you've set up a portal using any of the above functions, you can use it
to run async functions by making calls to :func:`greenback.await_`:

.. autofunction:: await_(awaitable)


Additional utilities
--------------------

`greenback` comes with a few tools (built atop :func:`await_`) which may
be helpful when adapting async code to work with synchronous interfaces.

.. function:: autoawait
   :decorator:

   Decorator for an async function which allows (and requires) it to be called
   from synchronous contexts without ``await``.

   For example, this can be used for magic methods, property setters, and so on.

.. function:: async_context(async_cm)
   :with:

   Wraps an async context manager so it is usable in a synchronous ``with``
   statement. That is, ``with async_context(foo) as bar:`` behaves equivantly
   to ``async with foo as bar:`` as long as a portal has been created
   somewhere up the callstack.

.. function:: async_iter(async_iterable)
   :for:

   Wraps an async iterable so it is usable in a synchronous ``for`` loop, ``yield from``
   statement, or similar synchronous iteration context. That is, ``for elem in
   async_iter(foo):`` behaves equivantly
   to ``async for elem in foo:`` as long as a portal has been created
   somewhere up the callstack.

   If the obtained async iterator implements the full async generator protocol
   (``asend()``, ``athrow()``, and ``aclose()`` methods), then the returned
   synchronous iterator implements the corresponding methods ``send()``,
   ``throw()``, and ``close()``. This allows for better interoperation with
   ``yield from``, for example.
