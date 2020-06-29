API reference
=============

Core functionality
------------------

.. module:: greenback

In order to use `greenback` in a particular async task, you must first call
:func:`ensure_portal` in that task to install the "greenback shim".

.. autofunction:: ensure_portal

To support debugging and introspection tools, it's also possible to
enable `greenback` in a task from outside that task:

.. autofunction:: bestow_portal

Once the portal has been set up, you can use it with :func:`await_`:

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
   to ``async with foo as bar:`` as long as :func:`ensure_portal` has been called
   somewhere up the callstack.

.. function:: async_iter(async_iterable)
   :for:

   Wraps an async iterable so it is usable in a synchronous ``for`` loop, ``yield from``
   statement, or similar synchronous iteration context. That is, ``for elem in
   async_iter(foo):`` behaves equivantly
   to ``async for elem in foo:`` as long as :func:`ensure_portal` has been called
   somewhere up the callstack.

   If the obtained async iterator implements the full async generator protocol
   (``asend()``, ``athrow()``, and ``aclose()`` methods), then the returned
   synchronous iterator implements the corresponding methods ``send()``,
   ``throw()``, and ``close()``. This allows for better interoperation with
   ``yield from``, for example.
