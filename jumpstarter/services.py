from __future__ import annotations

import functools
import typing
from contextlib import AsyncExitStack
from enum import Enum
from enum import auto

import anyio
import math
from _stories.exceptions import StoryDefinitionError
from stories import class_story
from stories import Failure
from stories import Skip
from stories import Success
from stories import arguments
from stories import story
from transitions import MachineError
from transitions.extensions.asyncio import HierarchicalAsyncMachine

from jumpstarter.concurrency import create_value_event
from jumpstarter.exceptions import NotAResourceError


class ServiceRestartState(Enum):
    starting = auto()
    stopping = auto()
    stopped = auto()


class ServiceState(Enum):
    initializing = auto()
    initialized = auto()
    starting = auto()
    started = auto()
    restarting = ServiceRestartState
    stopping = auto()
    stopped = auto()
    crashed = auto()


class Service(HierarchicalAsyncMachine):
    ServiceState = ServiceState

    def __init__(self):
        service_state = type(self).ServiceState

        transitions = [
            ["initialized", service_state.initializing, service_state.initialized],
            ["starting", [service_state.initialized, service_state.stopped], service_state.starting],
            ["started", [service_state.starting, ServiceRestartState.starting], service_state.started],
            ["restarting", service_state.started, "restarting"],
            ["stopping", "restarting", ServiceRestartState.stopping],
            ["stopped", ServiceRestartState.stopping, ServiceRestartState.stopped],
            ["starting", ServiceRestartState.stopped, ServiceRestartState.starting],
            ["stopping", service_state.started, service_state.stopping],
            ["stopped", service_state.stopping, service_state.stopped],
            ["crashed", "*", service_state.crashed],
        ]
        super().__init__(
            states=service_state, transitions=transitions, initial=service_state.initializing, auto_transitions=False
        )

        self._restart_count: int = 0
        self._cancel_scope: anyio.CancelScope = anyio.open_cancel_scope()
        self._exit_stack: AsyncExitStack = AsyncExitStack()
        self._started_event: anyio.Event = anyio.create_event()

        self.on_enter_restarting(self._increase_restart_count)
        self.on_enter_started(self._notify_started)
        self.on_enter_stopping(self._reset_started_event)

    ##############
    # PUBLIC API #
    ##############

    @property
    def started_event(self):
        return self._started_event

    @story
    @arguments("task_group")
    def start(I):
        I.on_first_start
        I.on_start
        I.on_started

    @story
    def stop(I):
        I.on_stop
        I.on_shutdown

    @story
    @arguments("task_group")
    def restart(I):
        I.on_restart
        I.stop
        I.start

    #############
    # CALLBACKS #
    #############

    @class_story
    def on_first_start(cls, I):
        I.skip_if_not_initializing
        I.change_state_to_initialized

    @class_story
    def on_start(cls, I):
        I.change_state_to_starting
        I.acquire_resources
        I.schedule_background_tasks

    @class_story
    def on_started(cls, I):
        I.change_state_to_started

    @class_story
    def on_stop(cls, I):
        I.change_state_to_stopping
        I.release_resources

    @class_story
    def on_shutdown(cls, I):
        I.change_state_to_stopped

    @class_story
    def on_restart(cls, I):
        I.change_state_to_restarting

    #######
    # DSL #
    #######

    @classmethod
    def background_task(cls, task: typing.Callable[[typing.Any, typing.Any], typing.Awaitable[None]]):
        task.__background_task__ = True

        return task

    @classmethod
    def acquire_resource(cls, resource=None, timeout: float = None):
        def decorator(resource):
            resource.__resource__ = True
            resource.__timeout__ = timeout

            return resource

        if resource:
            return decorator(resource)

        return decorator

    #########
    # STEPS #
    #########

    @class_story
    def acquire_resources(cls, I):
        for attribute_name, attribute in __class__.__dict__.copy().items():
            if attribute_name == "acquire_resources":
                continue

            if hasattr(attribute, "__resource__") and attribute.__resource__:
                resource_acquirer = cls.create_resource_acquirer(attribute)
                getattr(I, resource_acquirer)

    @class_story
    def schedule_background_tasks(cls, I):
        for attribute_name, attribute in __class__.__dict__.copy().items():
            if attribute_name == "schedule_background_tasks":
                continue

            if hasattr(attribute, "__background_task__") and attribute.__background_task__:
                task_scheduler = cls.create_task_scheduler(attribute)
                getattr(I, task_scheduler)

    async def release_resources(self, ctx):
        await self._exit_stack.aclose()

        return Success()

    async def skip_if_not_initializing(self, ctx):
        return Success() if self.is_initializing() else Skip()

    async def change_state_to_initialized(self, ctx):
        try:
            await self.initialized()
        except MachineError:
            return Failure()  # TODO: Extend failure protocol

        return Success()

    async def change_state_to_starting(self, ctx):
        try:
            await self.starting()
        except MachineError:
            return Failure()  # TODO: Extend failure protocol

        return Success()

    async def change_state_to_started(self, ctx):
        try:
            await self.started()
        except MachineError:
            return Failure()  # TODO: Extend failure protocol

        return Success()

    async def change_state_to_stopping(self, ctx):
        try:
            await self.stopping()
        except MachineError:
            return Failure()  # TODO: Extend failure protocol

        return Success()

    async def change_state_to_stopped(self, ctx):
        try:
            await self.stopped()
        except MachineError:
            return Failure()  # TODO: Extend failure protocol

        return Success()

    async def change_state_to_restarting(self, ctx):
        try:
            await self.restarting()
        except MachineError:
            return Failure()  # TODO: Extend failure protocol

        return Success()

    #############
    # RESOURCES #
    #############

    def cancel_scope(self, ctx):
        return self._cancel_scope

    cancel_scope.__resource__ = True
    cancel_scope.__timeout__ = None

    ####################
    # BACKGROUND TASKS #
    ####################

    async def sleep_forever(self, ctx):
        await anyio.sleep(math.inf)

    sleep_forever.__background_task__ = True

    ####################################
    # INTERNAL STATE MACHINE CALLBACKS #
    ####################################

    def _increase_restart_count(self):
        self._restart_count += 1

    async def _notify_started(self):
        await self._started_event.set()

    def _reset_started_event(self):
        self.started_event.clear()

    ##################
    # STEP FACTORIES #
    ##################

    @classmethod
    def create_resource_acquirer(cls, resource) -> str:
        resource_name = resource.__name__

        if resource.__timeout__:

            @functools.wraps(resource)
            async def wrapper(self, ctx):
                value_event = create_value_event()

                async def callback():
                    try:
                        async with anyio.fail_after(resource.__timeout__):
                            await value_event.set(await self._exit_stack.enter_async_context(resource(self, ctx)))
                    except AttributeError as e:
                        raise NotAResourceError() from e

                await ctx.task_group.spawn(callback)

                setattr(ctx, resource_name, value_event)
                return Success()

        else:

            @functools.wraps(resource)
            async def wrapper(self, ctx):
                value_event = create_value_event()

                async def callback():
                    try:
                        await value_event.set(await self._exit_stack.enter_async_context(resource(self, ctx)))
                    except AttributeError as e:
                        raise NotAResourceError(f"{resource.__name__} is not a resource") from e

                await ctx.task_group.spawn(callback)

                setattr(ctx, resource_name, value_event)
                return Success()

        wrapper.__name__ = f"acquire_{resource_name}"
        wrapper.__resource__ = False
        setattr(cls, wrapper.__name__, wrapper)
        return f"acquire_{resource_name}"

    @classmethod
    def create_task_scheduler(cls, task) -> str:
        @functools.wraps(task)
        async def wrapper(self, ctx):
            async def task_runner():
                while not self._cancel_scope.cancel_called:
                    await task(self, ctx)

                    # Let the scheduler decide if we should context switch
                    # in case the whole task always blocks
                    await anyio.sleep(0)

            await ctx.task_group.spawn(task_runner)

            return Success()

        wrapper.__name__ = f"schedule_{task.__name__}"
        wrapper.__background_task__ = False
        setattr(cls, wrapper.__name__, wrapper)
        return wrapper.__name__

    ###################
    # SPECIAL METHODS #
    ###################

    def __getattr__(self, item):
        # TODO: Remove this workaround once https://github.com/pytransitions/transitions/pull/422 is merged
        callback_type, target = self._identify_callback(item)

        if callback_type is not None:
            if callback_type in self.transition_cls.dynamic_methods:
                if target not in self.events:
                    raise AttributeError("event '{}' is not registered on <Machine@{}>".format(target, id(self)))
                return functools.partial(self.events[target].add_callback, callback_type)

            elif callback_type in self.state_cls.dynamic_methods:
                state = self.get_state(target)
                return functools.partial(state.add_callback, callback_type[3:])
        return self.__getattribute__(item)

    def __init_subclass__(declaring_class, **kwargs):
        @class_story
        def acquire_resources(bound_class, I):
            super(declaring_class, bound_class).acquire_resources(I)

            for attribute_name, attribute in bound_class.__dict__.copy().items():
                if hasattr(attribute, "__resource__") and attribute.__resource__:
                    resource_acquirer = bound_class.create_resource_acquirer(attribute)
                    getattr(I, resource_acquirer)

        declaring_class.acquire_resources = acquire_resources

        @class_story
        def schedule_background_tasks(bound_class, I):
            super(declaring_class, bound_class).schedule_background_tasks(I)

            for attribute_name, attribute in bound_class.__dict__.copy().items():
                if attribute_name == "schedule_background_tasks":
                    continue

                if hasattr(attribute, "__background_task__") and attribute.__background_task__:
                    task_scheduler = bound_class.create_task_scheduler(attribute)
                    getattr(I, task_scheduler)

        declaring_class.schedule_background_tasks = schedule_background_tasks
