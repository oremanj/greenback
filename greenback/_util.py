from functools import wraps
from typing import (
    Any,
    AsyncIterable,
    AsyncGenerator,
    AsyncContextManager,
    Iterator,
    Awaitable,
    Callable,
    Generic,
    Optional,
    TypeVar,
    cast,
)
from ._impl import await_

T = TypeVar("T")


def autoawait(fn: Callable[..., Awaitable[T]]) -> Callable[..., T]:
    """Decorator for an async function which allows (and requires) it to be called
    from synchronous contexts without ``await``.

    For example, this can be used for magic methods, property setters, and so on.
    """

    @wraps(fn)
    def wrapper(*args: Any, **kw: Any) -> T:
        return await_(fn(*args, **kw))

    return wrapper


class async_context(Generic[T]):
    """Wraps an async context manager so it is usable in a synchronous
    ``with`` statement."""

    __slots__ = ("_cm", "_aexit")

    def __init__(self, cm: AsyncContextManager[T]):
        self._cm = cm

    def __enter__(self) -> T:
        try:
            self._aexit = type(self._cm).__aexit__
        except AttributeError:
            raise AttributeError(
                f"type object {type(self._cm).__name__!r} has no attribute '__aexit__'"
            ) from None
        aenter = type(self._cm).__aenter__
        return await_(aenter(self._cm))

    def __exit__(self, *exc: Any) -> Optional[bool]:
        return await_(self._aexit(self._cm, *exc))


class async_iter(Generic[T]):
    """Wraps an async iterator so it is usable in a synchronous
    ``for`` loop, ``yield from`` statement, or other context that expects
    a synchronous iterator."""

    __slots__ = ("_it",)

    def __init__(self, iterable: AsyncIterable[T]):
        try:
            aiter = type(iterable).__aiter__
        except AttributeError:
            raise TypeError(
                "'async_iter' requires an object with __aiter__ method, got "
                + type(iterable).__name__
            ) from None
        self._it = aiter(iterable)
        try:
            type(self._it).__anext__
        except AttributeError:
            raise TypeError(
                "'async_iter' received an object from __aiter__ that does not "
                "implement __anext__: " + type(self._it).__name__
            ) from None
        if all(hasattr(self._it, meth) for meth in ("asend", "athrow", "aclose")):
            self.__class__ = async_generator

    def __iter__(self) -> Iterator[T]:
        return self

    def __next__(self) -> T:
        try:
            return await_(type(self._it).__anext__(self._it))
        except StopAsyncIteration as ex:
            raise StopIteration(*ex.args)


class async_generator(async_iter[T]):
    __slots__ = ()

    def send(self, val: Any) -> T:
        try:
            return await_(cast(AsyncGenerator[T, Any], self._it).asend(val))
        except StopAsyncIteration as ex:
            raise StopIteration(*ex.args)

    def throw(self, *exc: Any) -> T:
        try:
            return await_(cast(AsyncGenerator[T, Any], self._it).athrow(*exc))
        except StopAsyncIteration as ex:
            raise StopIteration(*ex.args)

    def close(self) -> None:
        return await_(cast(AsyncGenerator[T, Any], self._it).aclose())
