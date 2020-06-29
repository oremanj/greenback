import collections
import gc
import re
import types
import sys
import warnings

import anyio
import pytest  # type: ignore
import sniffio  # type: ignore
import trio
import trio.testing

import greenback
from .._impl import ensure_portal, bestow_portal, await_


async def noop():
    pass


with warnings.catch_warnings():
    # anyio hasn't been updated for the deprecations in Trio 0.15.0 yet
    warnings.simplefilter("ignore")
    anyio.run(noop, backend="trio")


async def test_simple(library):
    ticks = 0

    async def one_task(*, have_portal=False):
        if not have_portal:
            with pytest.raises(
                RuntimeError, match="you must 'await greenback.ensure_portal"
            ):
                await_(anyio.sleep(0))
            await ensure_portal()
            await ensure_portal()
        for _ in range(100):
            nonlocal ticks
            await_(anyio.sleep(0))
            await anyio.sleep(0)
            ticks += 1

    async with anyio.create_task_group() as tg:
        await tg.spawn(one_task)
        await ensure_portal()
        await_(tg.spawn(one_task))
        await_(one_task(have_portal=True))
        await one_task(have_portal=True)

    assert ticks == 400


async def test_complex(library):
    server = await anyio.create_tcp_server()

    async def serve_echo_client(conn):  # pragma: no cover
        await ensure_portal()
        for chunk in greenback.async_iter(conn.receive_chunks(1024)):
            await_(conn.send_all(chunk))

    async def serve_echo():  # pragma: no cover
        await ensure_portal()
        with greenback.async_context(anyio.create_task_group()) as tg:
            for conn in greenback.async_iter(server.accept_connections()):
                await_(tg.spawn(serve_echo_client, conn))

    async with anyio.create_task_group() as tg:
        await tg.spawn(serve_echo)
        await ensure_portal()
        conn = await_(anyio.connect_tcp("127.0.0.1", server.port))
        await_(conn.send_all(b"hello"))
        assert b"hello" == await_(conn.receive_some(1024))
        await_(tg.cancel_scope.cancel())


async def test_bestow(library):
    task = None
    task_started = anyio.create_event()
    portal_installed = anyio.create_event()

    async def task_fn():
        nonlocal task
        task = greenback._impl.current_task()
        await task_started.set()
        await portal_installed.wait()
        await_(anyio.sleep(0))

    async with anyio.create_task_group() as tg:
        await tg.spawn(task_fn)
        await task_started.wait()
        greenback.bestow_portal(task)
        greenback.bestow_portal(task)
        await portal_installed.set()

    with pytest.raises(RuntimeError):
        await_(anyio.sleep(0))


def test_misuse():
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
            await tg.spawn(ensure_portal)

    del tg
    for _ in range(4):
        gc.collect()

    assert not greenback._impl.task_portal


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
