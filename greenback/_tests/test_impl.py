import collections
import gc
import re
import types
import sys
import warnings

import anyio
import greenlet  # type: ignore
import pytest
import sniffio
import trio
import trio.testing

import greenback
from .._impl import ensure_portal, has_portal, await_


async def test_simple(library):
    ticks = 0

    async def one_task(*, have_portal=False):
        if not have_portal:
            assert not has_portal()
            with pytest.raises(
                RuntimeError, match="you must 'await greenback.ensure_portal"
            ):
                await_(anyio.sleep(0))
            await ensure_portal()
            await ensure_portal()
        assert has_portal()
        for _ in range(100):
            nonlocal ticks
            await_(anyio.sleep(0))
            await anyio.sleep(0)
            ticks += 1

    async with anyio.create_task_group() as tg:
        tg.start_soon(one_task)
        await ensure_portal()
        tg.start_soon(one_task)
        await_(one_task(have_portal=True))
        await one_task(have_portal=True)

    assert ticks == 400


async def test_complex(library):
    listener = await anyio.create_tcp_listener(local_host="0.0.0.0")

    async def serve_echo_client(conn):  # pragma: no cover
        async with conn:
            await ensure_portal()
            for chunk in greenback.async_iter(conn):
                await_(conn.send(chunk))

    async def serve_echo():  # pragma: no cover
        await ensure_portal()
        with greenback.async_context(anyio.create_task_group()) as tg:
            await_(listener.serve(serve_echo_client, tg))

    async with listener, anyio.create_task_group() as tg:
        tg.start_soon(serve_echo)
        await ensure_portal()
        port = listener.extra(anyio.abc.SocketAttribute.local_port)
        async with await_(anyio.connect_tcp("127.0.0.1", port)) as conn:
            await_(conn.send(b"hello"))
            assert b"hello" == await_(conn.receive(1024))
        tg.cancel_scope.cancel()


async def test_with_portal_run(library):
    for test in (test_simple, test_complex):
        await greenback.with_portal_run(test, library)
        await greenback.with_portal_run(greenback.with_portal_run, test, library)
        with pytest.raises(RuntimeError, match="greenback.ensure_portal"):
            await_(anyio.sleep(0))
        await greenback.with_portal_run_sync(lambda: await_(test(library)))
        await greenback.with_portal_run_sync(
            lambda: await_(
                greenback.with_portal_run_sync(lambda: await_(test(library)))
            )
        )
        with pytest.raises(RuntimeError, match="greenback.ensure_portal"):
            await_(anyio.sleep(0))


async def test_with_portal_run_tree():
    async def expect_no_portal():
        await trio.sleep(0.5)
        assert not has_portal()

    async def expect_portal():
        assert has_portal()
        await_(trio.sleep(0.5))

    async def example_child(depth):
        assert has_portal()
        await_(trio.sleep(0))
        if depth == 0:
            return
        async with trio.open_nursery() as nursery:
            nursery.start_soon(expect_portal)
            nursery.start_soon(greenback.with_portal_run_tree, example_child, depth - 1)
            nursery.start_soon(example_child, depth - 1)
            await_(greenback.with_portal_run_tree(example_child, depth - 1))
            await trio.sleep(1)

    async with trio.open_nursery() as outer:
        async with trio.open_nursery() as middle:

            @outer.start_soon
            async def check_no_leakage():
                await trio.sleep(0.5)
                outer.start_soon(expect_no_portal)
                middle.start_soon(expect_no_portal)

            assert not has_portal()
            outer.start_soon(expect_no_portal)
            middle.start_soon(expect_no_portal)
            await greenback.with_portal_run_tree(example_child, 3)
            assert not has_portal()
            outer.start_soon(expect_no_portal)
            middle.start_soon(expect_no_portal)
            middle.start_soon(greenback.with_portal_run_tree, example_child, 3)
            await trio.sleep(0.5)
            middle.start_soon(greenback.with_portal_run_tree, example_child, 3)
            await trio.sleep(0.5)
            assert not has_portal()


async def test_bestow(library):
    task = None
    task_started = anyio.Event()
    portal_installed = anyio.Event()

    async def task_fn():
        nonlocal task
        task = greenback._impl.current_task()
        task_started.set()
        await portal_installed.wait()
        await_(anyio.sleep(0))

    async with anyio.create_task_group() as tg:
        tg.start_soon(task_fn)
        await task_started.wait()
        greenback.bestow_portal(task)
        greenback.bestow_portal(task)
        portal_installed.set()

    with pytest.raises(RuntimeError):
        await_(anyio.sleep(0))


async def test_contextvars(library):
    if sys.version_info < (3, 7) and library != "trio":
        pytest.skip("contextvars not supported on this version")

    import contextvars

    cv = contextvars.ContextVar("cv")

    async def inner():
        assert cv.get() == 20
        await anyio.sleep(0)
        cv.set(30)

    def middle():
        assert cv.get() == 10
        cv.set(20)
        await_(inner())
        assert cv.get() == 30
        if sys.version_info >= (3, 7) and getattr(
            greenlet, "GREENLET_USE_CONTEXT_VARS", False
        ):
            # greenlet is not aware of the backported contextvars,
            # so can't support Context.run() correctly before 3.7.
            # greenlet that isn't contextvars-aware hangs if the
            # inner greenlet uses Context.run() -- not our fault.
            cv.set(50)
            nctx = contextvars.copy_context()
            nctx.run(cv.set, 20)
            nctx.run(await_, inner())
            assert nctx[cv] == 30
            assert cv.get() == 50
        cv.set(40)

    cv.set(10)
    await greenback.ensure_portal()
    assert cv.get() == 10
    middle()
    assert cv.get() == 40
    await anyio.sleep(0)
    assert cv.get() == 40


def test_misuse():
    with pytest.raises(RuntimeError, match="only supported.*running under Trio"):
        anyio.run(greenback.with_portal_run_tree, anyio.sleep, 1, backend="asyncio")

    with pytest.raises(sniffio.AsyncLibraryNotFoundError):
        greenback.await_(42)

    @trio.run
    async def wrong_library():
        sniffio.current_async_library_cvar.set("tokio")
        with pytest.raises(RuntimeError, match="greenback does not support tokio"):
            greenback.await_(trio.sleep(1))

    @trio.run
    async def not_awaitable():
        await greenback.ensure_portal()
        with pytest.raises(TypeError, match="int can't be used in 'await' expression"):
            greenback.await_(42)


@pytest.mark.skipif(sys.implementation.name != "cpython", reason="CPython only")
def test_find_ptr_in_object():
    from greenback._impl import _aligned_ptr_offset_in_object

    class A:
        pass

    assert _aligned_ptr_offset_in_object(A(), A) == object().__sizeof__() / 2
    assert _aligned_ptr_offset_in_object(A(), "nope") is None


@types.coroutine
def async_yield(value):
    return (yield value)


async def test_resume_task_with_error(library):
    try:
        await async_yield(42)
        pytest.fail("yielding 42 didn't raise")  # pragma: no cover
    except Exception as ex:
        ty, msg = type(ex), str(ex)

    await ensure_portal()
    with pytest.raises(ty, match=re.escape(msg)):
        await async_yield(42)
    with pytest.raises(ty, match=re.escape(msg)):
        await_(async_yield(42))


async def test_exit_task_with_error():
    async def failing_task():
        await ensure_portal()
        await async_yield(42)

    with pytest.raises(TypeError):
        async with trio.open_nursery() as nursery:
            nursery.start_soon(failing_task)


async def test_portal_map_does_not_leak(library):
    async with anyio.create_task_group() as tg:
        for _ in range(1000):
            tg.start_soon(ensure_portal)

    del tg
    for _ in range(4):
        gc.collect()

    assert not greenback._impl.task_has_portal


async def test_awaitable(library):
    class SillyAwaitable:
        def __init__(self, fail=False):
            self._fail = fail

        def __await__(self):
            yield from anyio.sleep(0).__await__()
            if self._fail:
                raise ValueError("nope")
            return "it works!"

    await ensure_portal()
    assert "it works!" == (await SillyAwaitable()) == await_(SillyAwaitable())

    # Make sure an awaitable that fails doesn't leave _impl.adapt_awaitable in the tb
    with pytest.raises(ValueError, match="nope") as info:
        await_(SillyAwaitable(fail=True))
    assert [ent.name for ent in info.traceback] == [
        "test_awaitable",
        "await_",
        "__await__",
    ]


async def test_checkpoints():
    async def nothing():
        pass

    with trio.testing.assert_checkpoints():
        await ensure_portal()
    with trio.testing.assert_checkpoints():
        await_(trio.sleep(0))
    with trio.testing.assert_checkpoints():
        await_(trio.sleep(0))
    with trio.testing.assert_no_checkpoints():
        await_(nothing())


async def test_recursive_error(library):
    async def countdown(n):
        if n == 0:
            raise ValueError("Blastoff!")
        elif n % 2 == 0:
            return await countdown(n - 1)
        else:
            return await_(countdown(n - 1))

    await ensure_portal()
    with pytest.raises(ValueError, match="Blastoff!") as info:
        await countdown(10)

    # Test traceback cleaning too
    frames = collections.Counter()
    values = set()
    for ent in info.traceback:
        frames.update([ent.name])
        if ent.name == "countdown":
            values.add(ent.locals["n"])
    assert frames.most_common() == [
        ("countdown", 11),
        ("await_", 5),
        ("test_recursive_error", 1),
    ]
    assert values == set(range(11))


async def test_uncleanable_traceback(library):
    class ICantBelieveItsNotCoro(collections.abc.Coroutine):
        def __await__(self):
            yield from ()  # pragma: no cover

        def send(self):
            raise StopIteration  # pragma: no cover

        def throw(self, *exc):
            pass  # pragma: no cover

        def close(self):
            pass  # pragma: no cover

    await ensure_portal()
    with pytest.raises(TypeError) as info:
        await_(ICantBelieveItsNotCoro())
    # One frame for the call here, one frame where await_ calls send(),
    # one where outcome.send() discovers it can't call our send()
    assert len(info.traceback) == 3
