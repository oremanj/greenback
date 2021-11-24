import asyncio
import time
import trio
import greenback
from functools import partial
from greenback import await_

checkpoint = trio.lowlevel.checkpoint
ITERS = 100000

async def busy():
    for _ in range(ITERS):
        await checkpoint()

def sync_busy():
    for _ in range(ITERS):
        await_(checkpoint())

async def each_busy():
    def step():
        await_(checkpoint())

    async def astep():
        step()

    for _ in range(ITERS):
        await greenback.with_portal_run(astep)

async def each_sync_busy():
    def step():
        await_(checkpoint())

    for _ in range(ITERS):
        await greenback.with_portal_run_sync(step)

async def each_pass():
    def step():
        pass

    async def astep():
        step()

    for _ in range(ITERS):
        await greenback.with_portal_run(astep)

async def each_sync_pass():
    def step():
        pass

    for _ in range(ITERS):
        await greenback.with_portal_run_sync(step)

async def adapt_sync(fn):
    fn()

async def timeit(label, afn, *args):
    vals = []
    for idx in range(5):
        t0 = time.monotonic()
        await afn(*args)
        t1 = time.monotonic()
        vals.append((t1 - t0) * (1e6 / ITERS))
    print(f"{label}: {sum(vals)/len(vals):.1f} {vals!r}")

async def main():
    # Baseline: checkpoint with no greenback involved.
    await timeit("checkpoints", busy)

    # Greenback portal installed, but calling checkpoint normally.
    await timeit("checkpoints in one portal", greenback.with_portal_run, busy)

    # Greenback portal installed, calling checkpoint through await_ each time.
    await timeit("await_(checkpoint)s in one portal", greenback.with_portal_run, adapt_sync, sync_busy)

    # Greenback portal installed, calling checkpoint many times in a single await_.
    await timeit("checkpoints in one (portal + await_)", greenback.with_portal_run, adapt_sync, lambda: await_(busy()))

    # Simpler portal from with_portal_run_sync(), calling checkpoint through await_.
    await timeit("await_(checkpoint)s in one sync portal", greenback.with_portal_run_sync, sync_busy)

    # Create one with_portal_run() portal per checkpoint, and await_ the checkpoint.
    await timeit("[async portal + await_ + checkpoint]s", each_busy)

    # Create one with_portal_run_sync() portal per checkpoint, and await_ the checkpoint.
    await timeit("[sync portal + await_ + checkpoint]s", each_sync_busy)

    # Create one with_portal_run() portal per checkpoint, and await_ the checkpoint.
    await timeit("async portal creations", each_pass)

    # Create one with_portal_run_sync() portal per checkpoint, and await_ the checkpoint.
    await timeit("sync portal creations", each_sync_pass)

print("--- Trio ---")
trio.run(main)

print("--- asyncio ---")
checkpoint = partial(asyncio.sleep, 0)
asyncio.run(main())
