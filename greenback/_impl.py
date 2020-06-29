import collections
import greenlet  # type: ignore
import outcome
import sniffio  # type: ignore
import sys
import types
import weakref
from functools import partial
from typing import (
    Any,
    Awaitable,
    Callable,
    Coroutine,
    Generator,
    MutableMapping,
    Optional,
    TypeVar,
    Union,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    import trio
    import asyncio

T = TypeVar("T")

# Maps each task (trio.lowlevel.Task or asyncio.Task) that has called
# ensure_portal() to the greenlet running its coroutine shim. Note
# that this will be the same greenlet for every task unless greenlets
# are being used for purposes other than greenback in this program.
# We use a mapping by task rather than a contextvar because we don't
# want the portal to be inherited by child tasks.
task_portal: MutableMapping[object, greenlet.greenlet] = weakref.WeakKeyDictionary()

# The offset of asyncio.Task._coro in the Task object memory layout, if
# asyncio.Task is implemented in C (which it generally is on CPython 3.6+).
# This is determined dynamically when it is first needed.
aio_task_coro_c_offset: Optional[int] = None


async def greenback_shim(orig_coro: Coroutine[Any, Any, Any]) -> Any:
    """When a task has called ensure_portal(), its coroutine object is a coroutine
    for this function. This function then invokes each step of the task's original
    coroutine in a context that allows suspending via greenlet.
    """
    # This wrapper ensures that the top-level task coroutine is actually a coroutine,
    # not a generator. Some Trio introspection tools care about the difference, as
    # does anyio.
    return await _greenback_shim(orig_coro)  # type: ignore


@types.coroutine
def _greenback_shim(orig_coro: Coroutine[Any, Any, Any]) -> Generator[Any, Any, Any]:
    # The greenlet in which each send() or throw() call will occur.
    child_greenlet: Optional[greenlet.greenlet] = None

    # The next thing we plan to yield to the event loop. (The first yield
    # goes to ensure_portal() rather than to the event loop, so we use a
    # string that is unlikely to be a valid event loop trap.)
    next_yield: Any = "ready"

    # The next thing we plan to send to the original coroutine. This is an
    # outcome representing the value or error that the event loop resumed
    # us with.
    next_send: outcome.Outcome[Any]
    while True:
        try:
            # Normally we send to orig_coro whatever the event loop sent us
            next_send = outcome.Value((yield next_yield))
        except BaseException as ex:
            # If the event loop resumed us with an error, we forward that error
            next_send = outcome.Error(ex)
        try:
            if not child_greenlet:
                # Start a new send() or throw() call on the original coroutine.
                child_greenlet = greenlet.greenlet(next_send.send)
                next_yield = child_greenlet.switch(orig_coro)
            else:
                # Resume the previous send() or throw() call, which is currently
                # at a simulated yield point in a greenback.await_() call.
                next_yield = child_greenlet.switch(next_send)
            if child_greenlet.dead:
                # The send() or throw() call completed so we need to
                # create a new greenlet for the next one.
                child_greenlet = None
        except StopIteration as ex:
            # The underlying coroutine completed, so we forward its return value.
            return ex.value
        # If the underlying coroutine terminated with an exception, it will
        # propagate out of greenback_shim, which is what we want.


def current_task() -> Union["trio.lowlevel.Task", "asyncio.Task[Any]"]:
    library = sniffio.current_async_library()
    if library == "trio":
        try:
            from trio.lowlevel import current_task
        except ImportError:  # pragma: no cover
            if not TYPE_CHECKING:
                from trio.hazmat import current_task

        return current_task()
    elif library == "asyncio":
        import asyncio

        if sys.version_info >= (3, 7):
            task = asyncio.current_task()
        else:
            task = asyncio.Task.current_task()
        if task is None:  # pragma: no cover
            # typeshed says this is possible, but I haven't been able to induce it
            raise RuntimeError("No asyncio task is running")
        return task
    else:
        raise RuntimeError(f"greenback does not support {library}")


def get_aio_task_coro(task: "asyncio.Task[Any]") -> Coroutine[Any, Any, Any]:
    try:
        # Public API in 3.8+
        return task.get_coro()  # type: ignore  # (defined as returning Any)
    except AttributeError:
        return task._coro  # type: ignore  # (not in typeshed)


def set_aio_task_coro(
    task: "asyncio.Task[Any]", new_coro: Coroutine[Any, Any, Any]
) -> None:
    try:
        task._coro = new_coro  # type: ignore
        return
    except AttributeError as ex:
        if sys.implementation.name != "cpython":  # pragma: no cover
            raise
        if "is not writable" not in str(ex):  # pragma: no cover
            raise

    # If using the C accelerator on CPython, the setter isn't
    # even present and we need to use ctypes to change the
    # coroutine field.

    global aio_task_coro_c_offset
    import ctypes

    old_coro = get_aio_task_coro(task)

    if aio_task_coro_c_offset is None:
        # Deduce the offset by scanning the task object representation
        # for id(task._coro)
        size = task.__sizeof__()
        arraytype = ctypes.c_size_t * (size // ctypes.sizeof(ctypes.c_size_t))
        for idx, value in enumerate(arraytype.from_address(id(task))):
            if value == id(old_coro):
                aio_task_coro_c_offset = idx * ctypes.sizeof(ctypes.c_size_t)
                break
        else:  # pragma: no cover
            raise RuntimeError("Couldn't determine C offset of asyncio.Task._coro")

    # (Explanation copied from trio._core._multierror, applies equally well here.)
    # How to handle refcounting? I don't want to use ctypes.py_object because
    # I don't understand or trust it, and I don't want to use
    # ctypes.pythonapi.Py_{Inc,Dec}Ref because we might clash with user code
    # that also tries to use them but with different types. So private _ctypes
    # APIs it is!
    import _ctypes  # type: ignore

    coro_field = ctypes.c_size_t.from_address(id(task) + aio_task_coro_c_offset)
    assert coro_field.value == id(old_coro)
    _ctypes.Py_INCREF(new_coro)
    coro_field.value = id(new_coro)
    _ctypes.Py_DECREF(old_coro)


def bestow_portal(task: Union["trio.lowlevel.Task", "asyncio.Task[Any]"]) -> None:
    """Ensure that the given async *task* is able to use :func:`greenback.await_`.

    This works like calling :func:`ensure_portal` from within *task*.
    If you pass the currently running task, then the portal will not
    become usable until after the task yields control to the event loop.

    If your program uses greenlets for non-`greenback` purposes, then you must
    call :func:`bestow_portal` from the same greenlet that the *task* will run in.
    (This is rare; generally the entire async event loop runs in one greenlet,
    so the distinction doesn't matter.)
    """

    if task in task_portal:
        # This task already has a greenback shim; nothing to do.
        return

    # Create the shim coroutine
    if type(task).__module__.startswith("trio."):
        try:
            from trio.lowlevel import Task
        except ImportError:  # pragma: no cover
            if not TYPE_CHECKING:
                from trio.hazmat import Task

        assert isinstance(task, Task)
        shim_coro = greenback_shim(task.coro)
        commit: Callable[[], None] = partial(setattr, task, "coro", shim_coro)
    else:
        import asyncio

        assert isinstance(task, asyncio.Task)
        shim_coro = greenback_shim(get_aio_task_coro(task))
        commit = partial(set_aio_task_coro, task, shim_coro)

    # Step it once so it's ready to get resumed by the event loop
    first_yield = shim_coro.send(None)
    assert first_yield == "ready"

    # Update so the event loop will resume shim_coro rather than the
    # original task coroutine
    commit()

    # Make sure calls to greenback.await_() in this task know where to find us
    task_portal[task] = greenlet.getcurrent()


async def ensure_portal() -> None:
    """Ensure that the current async task is able to use :func:`greenback.await_`.

    If the current task has called :func:`ensure_portal` previously, calling
    it again is a no-op. Otherwise, :func:`ensure_portal` interposes a
    "coroutine shim" provided by `greenback` in between the event
    loop and the coroutine being used to run the task. For example,
    when running under Trio, `trio.lowlevel.Task.coro` is replaced with
    a wrapper around the coroutine it previously referred to. (The
    same thing happens under asyncio, but asyncio doesn't expose the
    coroutine field publicly, so some additional trickery is required
    in that case.)

    After installation of the coroutine shim, each task step passes
    through `greenback` on its way into and out of your code. At
    some performance cost, this effectively provides a portal that
    allows later calls to :func:`greenback.await_` in the same task to
    access an async environment, even if the function that calls
    :func:`await_` is a synchronous function.

    This function is a cancellation point and a schedule point (a checkpoint,
    in Trio terms) even if the calling task already had a portal set up.
    """

    this_task = current_task()
    if this_task not in task_portal:
        bestow_portal(this_task)

    # Execute a checkpoint so that we're now running inside the shim coroutine.
    # This is necessary in case the caller immediately invokes greenback.await_()
    # without any further checkpoints.
    library = sniffio.current_async_library()
    await sys.modules[library].sleep(0)  # type: ignore


async def adapt_awaitable(aw: Awaitable[T]) -> T:
    return await aw


def await_(aw: Awaitable[T]) -> T:
    """Run an async function or await an awaitable from a synchronous function,
    using the portal set up for the current async task by :func:`ensure_portal`.

    ``greenback.await_(foo())`` is equivalent to ``await foo()``, except that
    the `greenback` version can be written in a synchronous function while
    the native version cannot.
    """
    try:
        task = current_task()
        try:
            gr = task_portal[task]
        except KeyError:
            raise RuntimeError(
                "you must 'await greenback.ensure_portal()' in this task first"
            ) from None
    except BaseException:
        if isinstance(aw, collections.abc.Coroutine):
            # Suppress the "coroutine was never awaited" warning
            aw.close()
        raise

    # If this is a non-coroutine awaitable, turn it into a coroutine
    if isinstance(aw, collections.abc.Coroutine):
        coro: Coroutine[Any, Any, T] = aw
        trim_tb_frames = 2
    else:
        coro = adapt_awaitable(aw)
        trim_tb_frames = 3

    # Step through the coroutine until it's exhausted, sending each trap
    # into the portal for the event loop to process.
    next_send: outcome.Outcome[Any] = outcome.Value(None)
    while True:
        try:
            # next_yield is a Future (under asyncio) or a checkpoint
            # or WaitTaskRescheduled marker (under Trio)
            next_yield: Any = next_send.send(coro)  # type: ignore
        except StopIteration as ex:
            return ex.value  # type: ignore
        except BaseException as ex:
            # Trim internal frames for a nicer traceback.
            # ex.__traceback__ covers the next_send.send(coro) line above;
            # its tb_next is in Value.send() or Error.send();
            # and tb_next of that covers the outermost frame in the user's
            # coroutine, which is what interests us.
            tb = ex.__traceback__
            assert tb is not None
            for _ in range(trim_tb_frames):
                if tb.tb_next is None:
                    # If we get here, there were fewer traceback frames
                    # than we expected, meaning we probably didn't
                    # even make it to the user's code. Don't do any
                    # trimming.
                    raise
                tb = tb.tb_next
            exception_from_greenbacked_function = ex.with_traceback(tb)
            # This line shows up in tracebacks, so give the variable a good name
            raise exception_from_greenbacked_function

        # next_send is an outcome.Outcome representing the value or error
        # with which the event loop wants to resume the task
        next_send = gr.switch(next_yield)
