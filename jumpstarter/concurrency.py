import typing

import anyio


def create_value_event(default: typing.Optional[typing.Any] = None):
    class ValueEvent(anyio._get_asynclib().Event):
        def __init__(self, default: typing.Optional[typing.Any] = None) -> None:
            self._value: typing.Any = default

            super().__init__()

        async def set(self, value: typing.Any) -> None:
            self._value = value
            await super().set()

        def clear(self) -> None:
            self._value = None
            super().clear()

        @property
        async def value(self) -> typing.Any:
            await self.wait()

            return self._value

    return ValueEvent(default)
