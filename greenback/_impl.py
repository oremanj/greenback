import collections
import greenlet  # type: ignore
import outcome
import sniffio
import sys
import types
import weakref
from functools import partial
from typing import (
    Any,
    Awaitable,
    Callable,
    Coroutine,
    Dict,
    Generator,
    MutableSet,
    Optional,
    TypeVar,
    Union,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    import trio
    import asyncio

try:
    import contextvars
except ImportError:  # pragma: no cover
    # 'no cover' rationale: Trio pulls in the contextvars backport,
    # and it's not worth adding more CI runs in environments that
    # specifically exclude Trio.
    if not TYPE_CHECKING:
        contextvars = None

T = TypeVar("T")

# Set of tasks (trio.lowlevel.Task or asyncio.Task) that have a "greenback
# portal" installed, via any of the *_portal() functions. When running,
# these tasks can send event loop traps to greenlet.getcurrent().parent
# in order to yield them to the event loop.
task_has_portal: MutableSet[object] = weakref.WeakSet()

# The offset of asyncio.Task._coro in the Task object memory layout, if
# asyncio.Task is implemented in C (which it generally is on CPython 3.6+).
# This is determined dynamically when it is first needed.
aio_task_coro_c_offset: Optional[int] = None

# If True, we need to configure greenlet to preserve our
# contextvars context when we switch greenlets. (Older versions
# of greenlet are context-naive and do what we want by default.
# greenlet v0.4.17 tried to be context-aware but isn't configurable
# to get the behavior we want; we forbid it in our setup.py dependencies.)
# See https://github.com/python-greenlet/greenlet/issues/196 for details.
greenlet_needs_context_fixup: bool = (
    contextvars is not None and getattr(greenlet, "GREENLET_USE_CONTEXT_VARS", False)
)


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
    # In theory this could be written as a simpler function that uses
    # _greenback_shim_sync():
    #
    #     next_yield = "ready"
    #     while True:
    #         try:
    #             target = partial(orig_coro.send, (yield next_yield))
    #         except BaseException as ex:
    #             target = partial(orig_coro.throw, ex)
    #         try:
    #             next_yield = yield from _greenback_shim_sync(target)
    #         except StopIteration as ex:
    #             return ex.value
    #
    # In practice, this doesn't work that well: _greenback_shim_sync()
    # has a hard time raising StopIteration, because it's a generator,
    # and unrolling it into a non-generator iterable makes it slower.
    # So we'll accept a bit of code duplication.
    parent_greenlet = greenlet.getcurrent()

    # The greenlet in which each send() or throw() call will occur.
    child_greenlet: Optional[greenlet.greenlet] = None

    # The contextvars.Context that we have most recently seen as active
    # for this task and propagated to child_greenlet
    curr_ctx: Optional[contextvars.Context] = None

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
                switch_arg: Any = orig_coro
            else:
                # Resume the previous send() or throw() call, which is currently
                # at a simulated yield point in a greenback.await_() call.
                switch_arg = next_send

            if (
                greenlet_needs_context_fixup
                and parent_greenlet.gr_context is not curr_ctx
                and child_greenlet.gr_context is curr_ctx
            ):
                # Make sure the child greenlet's contextvars context
                # is the same as our own, even if our own context
                # changes (such as via trio.Task.context assignment),
                # unless the child greenlet appears to have changed
                # its context privately through a call to Context.run().
                #
                # Note 'parent_greenlet.gr_context' here is just a
                # portable way of getting the current contextvars
                # context, which is not exposed by the contextvars
                # module directly (copy_context() returns a copy, not
                # a new reference to the original).  Upon initial
                # creation of child_greenlet, curr_ctx and
                # child_greenlet.gr_context will both be None, so this
                # condition works for that case too.
                child_greenlet.gr_context = curr_ctx = parent_greenlet.gr_context

            next_yield = child_greenlet.switch(switch_arg)
            if child_greenlet.dead:
                # The send() or throw() call completed so we need to
                # create a new greenlet for the next one.
                child_greenlet = curr_ctx = None
        except StopIteration as ex:
            # The underlying coroutine completed, so we forward its return value.
            return ex.value
        # If the underlying coroutine terminated with an exception, it will
        # propagate out of greenback_shim, which is what we want.


@types.coroutine
def _greenback_shim_sync(target: Callable[[], Any]) -> Generator[Any, Any, Any]:
    """Run target(), forwarding the event loop traps and responses necessary
    to implement any await_() calls that it makes.

    This is only a little bit faster than using greenback_shim() plus a
    sync-to-async wrapper -- maybe 2us faster for the entire call,
    so it only matters when you're scoping the portal to a very small
    range. We ship it anyway because it's easier to understand than
    the async-compatible _greenback_shim(), and helps with understanding
    the latter.
    """

    parent_greenlet = greenlet.getcurrent()
    curr_ctx = None

    # The greenlet in which we run target().
    child_greenlet = greenlet.greenlet(target)

    # The next thing we plan to yield to the event loop.
    next_yield: Any

    # The next thing we plan to send via greenlet.switch(). This is an
    # outcome representing the value or error that the event loop resumed
    # us with. Initially None for the very first zero-argument switch().
    next_send: Optional[outcome.Outcome[Any]] = None

    while True:
        if (
            greenlet_needs_context_fixup
            and parent_greenlet.gr_context is not curr_ctx
            and child_greenlet.gr_context is curr_ctx
        ):
            # Make sure the child greenlet's contextvars context
            # is the same as our own, even if our own context
            # changes (such as via trio.Task.context assignment),
            # unless the child greenlet appears to have changed
            # its context privately through a call to Context.run().
            #
            # Note 'parent_greenlet.gr_context' here is just a
            # portable way of getting the current contextvars
            # context, which is not exposed by the contextvars
            # module directly (copy_context() returns a copy, not
            # a new reference to the original).  Upon initial
            # creation of child_greenlet, curr_ctx and
            # child_greenlet.gr_context will both be None, so this
            # condition works for that case too.
            child_greenlet.gr_context = curr_ctx = parent_greenlet.gr_context

        if next_send is None:
            next_yield = child_greenlet.switch()
        else:
            next_yield = child_greenlet.switch(next_send)
        if child_greenlet.dead:
            # target() returned, so next_yield is its return value, not an
            # event loop trap. (If it exits with an exception, that exception
            # will propagate out of switch() and thus out of the loop, which
            # is what we want.)
            return next_yield
        try:
            # Normally we send to orig_coro whatever the event loop sent us
            next_send = outcome.Value((yield next_yield))
        except BaseException as ex:
            # If the event loop resumed us with an error, we forward that error
            next_send = outcome.Error(ex)


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


def _aligned_ptr_offset_in_object(obj: object, referent: object) -> Optional[int]:
    """Return the byte offset in the C representation of *obj* (an
    arbitrary Python object) at which is found a naturally-aligned
    pointer that points to *referent*.  If *search_for*
    can't be found, return None.
    """
    import ctypes

    size = obj.__sizeof__()
    arraytype = ctypes.c_size_t * (size // ctypes.sizeof(ctypes.c_size_t))
    for idx, value in enumerate(arraytype.from_address(id(obj))):
        if value == id(referent):
            return idx * ctypes.sizeof(ctypes.c_size_t)
    return None


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
        aio_task_coro_c_offset = _aligned_ptr_offset_in_object(task, old_coro)
        if aio_task_coro_c_offset is None:  # pragma: no cover
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

    This works like calling :func:`ensure_portal` from within *task*,
    with one exception: if you pass the currently running task, then
    the portal will not become usable until after the task yields
    control to the event loop.
    """

    if task in task_has_portal:
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

    # Enable greenback.await_() in this task, since all of its future steps
    # will run under the greenback shim
    task_has_portal.add(task)


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
    some performance cost, this effectively provides a **portal** that
    allows later calls to :func:`greenback.await_` in the same task to
    access an async environment, even if the function that calls
    :func:`await_` is a synchronous function.

    This function is a cancellation point and a schedule point (a checkpoint,
    in Trio terms) even if the calling task already had a portal set up.
    """

    this_task = current_task()
    if this_task not in task_has_portal:
        bestow_portal(this_task)

    # Execute a checkpoint so that we're now running inside the shim coroutine.
    # This is necessary in case the caller immediately invokes greenback.await_()
    # without any further checkpoints.
    library = sniffio.current_async_library()
    await sys.modules[library].sleep(0)  # type: ignore


def has_portal(
    task: Optional[Union["trio.lowlevel.Task", "asyncio.Task[Any]"]] = None
) -> bool:
    """Return true if the given *task* is currently able to use
    :func:`greenback.await_`, false otherwise. If no *task* is
    specified, query the currently executing task.
    """
    return current_task() in task_has_portal


async def with_portal_run(
    async_fn: Callable[..., Awaitable[T]], *args: Any, **kwds: Any
) -> T:
    """Execute ``await async_fn(*args, **kwds)`` in a context that is able
    to use :func:`greenback.await_`.

    If the current task already has a greenback portal set up via a
    call to one of the other ``greenback.*_portal()`` functions, then
    :func:`with_portal_run` simply calls *async_fn*.  If *async_fn*
    uses :func:`greenback.await_`, the existing portal will take care
    of it.

    Otherwise (if there is no portal already available to the current task),
    :func:`with_portal_run` creates a new portal which lasts only for the
    duration of the call to *async_fn*. If *async_fn* then calls
    :func:`ensure_portal`, an additional portal will **not** be created:
    the task will still have just the portal installed by
    :func:`with_portal_run`, which will be removed when *async_fn* returns.

    This function does *not* add any cancellation point or schedule point
    beyond those that already exist inside *async_fn*.
    """

    this_task = current_task()
    if this_task in task_has_portal:
        return await async_fn(*args, **kwds)
    shim_coro = _greenback_shim(async_fn(*args, **kwds))  # type: ignore
    assert shim_coro.send(None) == "ready"
    task_has_portal.add(this_task)
    try:
        res: T = await shim_coro
        return res
    finally:
        task_has_portal.remove(this_task)


async def with_portal_run_sync(sync_fn: Callable[..., T], *args: Any, **kwds: Any) -> T:
    """Execute ``sync_fn(*args, **kwds)`` in a context that is able
    to use :func:`greenback.await_`.

    If the current task already has a greenback portal set up via a
    call to one of the other ``greenback.*_portal()`` functions, then
    :func:`with_portal_run` simply calls *sync_fn*.  If *sync_fn*
    uses :func:`greenback.await_`, the existing portal will take care
    of it.

    Otherwise (if there is no portal already available to the current task),
    :func:`with_portal_run_sync` creates a new portal which lasts only for the
    duration of the call to *sync_fn*.

    This function does *not* add any cancellation point or schedule point
    beyond those that already exist due to any :func:`await_`\\s inside *sync_fn*.
    """

    this_task = current_task()
    if this_task in task_has_portal:
        return sync_fn(*args, **kwds)
    task_has_portal.add(this_task)
    try:
        res: T = await _greenback_shim_sync(partial(sync_fn, *args, **kwds))
        return res
    finally:
        task_has_portal.remove(this_task)


if TYPE_CHECKING:
    from trio.abc import Instrument
else:
    Instrument = object


class AutoPortalInstrument(Instrument):
    def __init__(self) -> None:
        # {task: nursery depth at which we'll auto-portalize new children}
        # Rationale for tracking the depth: in
        #     async with trio.open_nursery() as outer:
        #         await with_portal_run_tree(something)
        # we only want to portalize the tasks under `something`, not children
        # spawned into `outer`.
        self.tasks: Dict["trio.lowlevel.Task", int] = {}
        self.refs = 0

    def task_spawned(self, task: "trio.lowlevel.Task") -> None:
        if task.parent_nursery is None:  # pragma: no cover
            # We shouldn't see the init task (since this instrument is
            # added only after run() starts up) but don't crash if we do.
            return
        parent = task.parent_nursery.parent_task
        depth = self.tasks.get(parent)
        if depth is None:
            return
        if parent.child_nurseries.index(task.parent_nursery) >= depth:
            bestow_portal(task)
            self.tasks[task] = 0

    def task_exited(self, task: "trio.lowlevel.Task") -> None:
        self.tasks.pop(task, None)


# We can't initialize this at global scope because we don't want to import Trio
# if we're being used in an asyncio program. It will be initialized on the first
# call to with_portal_run_tree().
instrument_holder: "Optional[trio.lowlevel.RunVar[Optional[AutoPortalInstrument]]]"
instrument_holder = None


async def with_portal_run_tree(
    async_fn: Callable[..., Awaitable[T]], *args: Any, **kwds: Any
) -> T:
    """Execute ``await async_fn(*args, **kwds)`` in a context that allows use
    of :func:`greenback.await_` both in *async_fn* itself and in any tasks
    that are spawned into child nurseries of *async_fn*, recursively.

    You can use this to create an entire Trio run (except system
    tasks) that runs with :func:`greenback.await_` available: say
    ``trio.run(with_portal_run_tree, main)``.

    This function does *not* add any cancellation point or schedule point
    beyond those that already exist inside *async_fn*.

    Availability: Trio only.

    .. note:: The automatic "portalization" of child tasks is
       implemented using a Trio `instrument <trio.abc.Instrument>`,
       which has a small performance impact on task spawning for the
       entire Trio run. To minimize this impact, a single instrument
       is used even if you have multiple :func:`with_portal_run_tree`
       calls running simultaneously, and the instrument will be
       removed as soon as all such calls have completed.

    """
    try:
        import trio

        try:
            from trio import lowlevel as trio_lowlevel
        except ImportError:  # pragma: no cover
            if not TYPE_CHECKING:
                from trio import hazmat as trio_hazmat

        this_task = trio_lowlevel.current_task()
    except Exception:
        raise RuntimeError("This function is only supported when running under Trio")

    global instrument_holder
    if instrument_holder is None:
        instrument_holder = trio_lowlevel.RunVar("greenback_instrument", default=None)
    instrument = instrument_holder.get()
    if instrument is None:
        # We're the only with_portal_run_tree() in this Trio run at the moment -->
        # set up the instrument and store it in the RunVar for other calls to find
        instrument = AutoPortalInstrument()
        trio_lowlevel.add_instrument(instrument)
        instrument_holder.set(instrument)
    elif this_task in instrument.tasks:
        # We're already inside another call to with_portal_run_tree(), so nothing
        # more needs to be done
        assert has_portal()
        return await async_fn(*args, **kwds)

    # Store our current nursery depth. This allows the instrument to
    # distinguish new tasks spawned in child nurseries of async_fn()
    # (which should get auto-portalized) from new tasks spawned in
    # nurseries that enclose this call (which shouldn't, even if they
    # have the same parent task).
    instrument.tasks[this_task] = len(this_task.child_nurseries)
    instrument.refs += 1
    try:
        return await with_portal_run(async_fn, *args, **kwds)
    finally:
        del instrument.tasks[this_task]
        instrument.refs -= 1
        if instrument.refs == 0:
            # There are no more with_portal_run_tree() calls executing
            # in this run, so clean up the instrument.
            instrument_holder.set(None)
            trio_lowlevel.remove_instrument(instrument)


async def adapt_awaitable(aw: Awaitable[T]) -> T:
    return await aw


def await_(aw: Awaitable[T]) -> T:
    """Run an async function or await an awaitable from a synchronous function,
    using the portal set up for the current async task by :func:`ensure_portal`,
    :func:`bestow_portal`, :func:`with_portal_run`, or :func:`with_portal_run_sync`.

    ``greenback.await_(foo())`` is equivalent to ``await foo()``, except that
    the `greenback` version can be written in a synchronous function while
    the native version cannot.
    """
    try:
        task = current_task()
        if task not in task_has_portal:
            raise RuntimeError(
                "you must 'await greenback.ensure_portal()' in this task first"
            ) from None
        gr = greenlet.getcurrent().parent
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
