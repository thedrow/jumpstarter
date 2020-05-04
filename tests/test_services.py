import functools
from stories import Success
from unittest.mock import AsyncMock, Mock

import anyio
import pytest
from transitions import MachineError

from jumpstarter.exceptions import NotAResourceError
from jumpstarter.services import Service
from jumpstarter.services import ServiceRestartState
from jumpstarter.services import ServiceState


@pytest.mark.anyio
async def test_service_initial_state():
    """The service state machine's initial state is ServiceState.initializing."""
    service = Service()

    assert service.is_initializing()


@pytest.mark.parametrize(
    "initial_state,transition",
    [
        (ServiceState.initializing, "starting"),
        (ServiceState.initializing, "started"),
        (ServiceState.initializing, "stopping"),
        (ServiceState.initializing, "stopped"),
        (ServiceState.initializing, "restarting"),
        (ServiceState.initialized, "started"),
        (ServiceState.initialized, "restarting"),
        (ServiceState.initialized, "stopping"),
        (ServiceState.initialized, "stopped"),
        (ServiceState.starting, "initialized"),
        (ServiceState.starting, "starting"),
        (ServiceState.starting, "restarting"),
        (ServiceState.starting, "stopping"),
        (ServiceState.starting, "stopped"),
        (ServiceState.started, "initialized"),
        (ServiceState.started, "starting"),
        (ServiceState.started, "started"),
        (ServiceState.started, "stopped"),
        (ServiceState.stopping, "initialized"),
        (ServiceState.stopping, "starting"),
        (ServiceState.stopping, "started"),
        (ServiceState.stopping, "restarting"),
        (ServiceState.stopping, "stopping"),
        (ServiceState.stopped, "initialized"),
        (ServiceState.stopped, "stopped"),
        (ServiceState.stopped, "started"),
        (ServiceState.stopped, "restarting"),
        (ServiceState.stopped, "stopping"),
        ("restarting", "initialized"),
        ("restarting", "restarting"),
        ("restarting", "stopped"),
        ("restarting", "starting"),
        ("restarting", "started"),
        (ServiceRestartState.starting, "initialized"),
        (ServiceRestartState.starting, "starting"),
        (ServiceRestartState.starting, "stopped"),
        pytest.param(ServiceRestartState.starting, "stopping", marks=pytest.mark.xfail),
        (ServiceRestartState.starting, "restarting"),
        (ServiceRestartState.stopping, "initialized"),
        (ServiceRestartState.stopping, "starting"),
        (ServiceRestartState.stopping, "started"),
        pytest.param(ServiceRestartState.stopping, "stopping", marks=pytest.mark.xfail),
        (ServiceRestartState.stopping, "restarting"),
        (ServiceRestartState.stopped, "initialized"),
        (ServiceRestartState.stopped, "started"),
        (ServiceRestartState.stopped, "stopped"),
        pytest.param(ServiceRestartState.stopped, "stopping", marks=pytest.mark.xfail),
        (ServiceRestartState.stopped, "restarting"),
    ],
)
@pytest.mark.anyio
async def test_service_state_machine_forbidden_transitions(initial_state, transition):
    """The state machine cannot change state from {initial_state} using the {transition} transition."""
    machine = Service()
    machine.add_transition("travel", ServiceState.initializing, initial_state)
    await machine.travel()

    with pytest.raises(MachineError, match=f"Can't trigger event {transition} from state {initial_state}!"):
        await getattr(machine, transition)()
        print(f"State machine transitioned to {machine.state} instead of failing")


@pytest.mark.parametrize(
    "initial_state,transition,final_state",
    [
        (ServiceState.initializing, "initialized", ServiceState.initialized),
        (ServiceState.initialized, "starting", ServiceState.starting),
        (ServiceState.stopped, "starting", ServiceState.starting),
        (ServiceState.starting, "started", ServiceState.started),
        (ServiceState.started, "stopping", ServiceState.stopping),
        (ServiceState.stopping, "stopped", ServiceState.stopped),
        (ServiceState.started, "restarting", ServiceState.restarting),
        ("restarting", "stopping", "restarting_stopping"),
        (ServiceRestartState.stopping, "stopped", "restarting_stopped"),
        (ServiceRestartState.stopped, "starting", "restarting_starting"),
        (ServiceRestartState.starting, "started", ServiceState.started),
        (ServiceState.initialized, "crashed", ServiceState.crashed),
        (ServiceState.starting, "crashed", ServiceState.crashed),
        (ServiceState.started, "crashed", ServiceState.crashed),
        ("restarting", "crashed", ServiceState.crashed),
        (ServiceState.stopping, "crashed", ServiceState.crashed),
        (ServiceState.stopped, "crashed", ServiceState.crashed),
        (ServiceRestartState.starting, "crashed", ServiceState.crashed),
        (ServiceRestartState.stopping, "crashed", ServiceState.crashed),
        (ServiceRestartState.stopped, "crashed", ServiceState.crashed),
    ],
)
@pytest.mark.anyio
async def test_service_state_machine_allowed_transitions(initial_state, transition, final_state):
    """The state machine can change state from {initial_state} using the {transition} transition to {final_state}"""
    machine = Service()
    machine.add_transition("travel", ServiceState.initializing, initial_state)
    await machine.travel()

    await getattr(machine, transition)()

    if hasattr(final_state, "name"):
        final_state = final_state.name

    assert getattr(machine, f"is_{final_state}")()


@pytest.fixture
def mock_schedule_background_tasks():
    mock = AsyncMock(return_value=Success())
    mock.__name__ = "schedule_background_tasks"

    return mock


@pytest.mark.anyio
async def test_service_lifecycle(mock_schedule_background_tasks):
    """Service Lifecycle is as follows:
    +----------------------+
    |     Initializing     |
    +----------------------+
               ↓
    +----------------------+
    |      Initialized     |
    +----------------------+
               ↓
    +----------------------+
    |       Starting       |
    +----------------------+
               ↓
    +----------------------+
    |       Started        |
    +----------------------+
               ↓
    +----------------------+
    |       Stopping       |
    +----------------------+
               ↓
    +----------------------+
    |       Stopped        |
    +----------------------+
    """
    states = []
    service = Service()
    service.schedule_background_tasks = mock_schedule_background_tasks

    service.after_state_change = lambda: states.append(service.state)

    async with anyio.create_task_group() as tg:
        await service.start(task_group=tg)

    assert service.is_started()
    assert states == [ServiceState.initialized, ServiceState.starting, ServiceState.started]
    assert service.started_event.is_set()
    assert not service.shutdown_event.is_set()

    states.clear()

    await service.stop()

    assert service.is_stopped()
    assert states == [ServiceState.stopping, ServiceState.stopped]
    assert not service.started_event.is_set()
    assert service.shutdown_event.is_set()

    states.clear()

    async with anyio.create_task_group() as tg:
        await service.start(task_group=tg)

        assert service.is_started()
        assert states == [ServiceState.starting, ServiceState.started]
        states.clear()

        await service.restart(task_group=tg)

    assert service.is_started()
    assert states == [
        "restarting",
        ServiceRestartState.stopping,
        ServiceRestartState.stopped,
        ServiceRestartState.starting,
        ServiceState.started,
    ]
    assert service.started_event.is_set()
    assert not service.shutdown_event.is_set()


@pytest.fixture()
def mock_async_context_manager():
    return AsyncMock()


@pytest.fixture()
def example_acquiring_resources_service(mock_async_context_manager):
    class ResourceAcquiringService(Service):
        @Service.acquire_resource
        def mock(self, ctx):
            return mock_async_context_manager

    return ResourceAcquiringService


@pytest.mark.anyio
async def test_acquire_resources(
        example_acquiring_resources_service, mock_async_context_manager, mock_schedule_background_tasks
):
    service = example_acquiring_resources_service()
    service.schedule_background_tasks = mock_schedule_background_tasks
    async with anyio.create_task_group() as tg:
        await service.start(task_group=tg)

    mock_async_context_manager.__aenter__.assert_awaited_once_with(mock_async_context_manager)

    await service.stop()

    mock_async_context_manager.__aexit__.assert_awaited_once_with(mock_async_context_manager, None, None, None)


@pytest.fixture(scope="session")
def example_service_acquiring_not_a_resource():
    class ResourceAcquiringNotAResourceService(Service):
        @Service.acquire_resource
        def not_a_resource(self, ctx):
            return object()

    return ResourceAcquiringNotAResourceService


@pytest.mark.anyio
async def test_attempt_to_acquire_an_object_which_is_not_a_context_manager_raises_an_error(
        example_service_acquiring_not_a_resource, mock_schedule_background_tasks
):
    service = example_service_acquiring_not_a_resource()
    service.schedule_background_tasks = mock_schedule_background_tasks
    with pytest.raises(NotAResourceError):
        async with anyio.create_task_group() as tg:
            await tg.spawn(functools.partial(service.start, task_group=tg))


@pytest.fixture(scope="session")
def example_resource_acquiring_service_which_times_out():
    class WillTimeout:
        async def __aenter__(self):
            await anyio.sleep(1)

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    class TimeoutService(Service):
        @Service.acquire_resource(timeout=0.1)
        def will_timeout(self, ctx):
            return WillTimeout()

    return TimeoutService


@pytest.mark.anyio
async def test_acquire_resource_with_timeout(
        example_resource_acquiring_service_which_times_out, mock_schedule_background_tasks
):
    service = example_resource_acquiring_service_which_times_out()
    service.schedule_background_tasks = mock_schedule_background_tasks

    with pytest.raises(TimeoutError):
        async with anyio.create_task_group() as tg:
            await service.start(task_group=tg)


class ResourceAcquiringService(Service):
    def __init__(self, mock_async_context_manager):
        self.mock_async_context_manager = mock_async_context_manager

        super(ResourceAcquiringService, self).__init__()

    @Service.acquire_resource
    def mock(self, ctx):
        return self.mock_async_context_manager


class ResourceAcquiringExtendedService(ResourceAcquiringService):
    pass


@pytest.mark.anyio
async def test_acquire_resources_with_inheritance(mock_async_context_manager, mock_schedule_background_tasks):
    service = ResourceAcquiringExtendedService(mock_async_context_manager)
    service.schedule_background_tasks = mock_schedule_background_tasks
    async with anyio.create_task_group() as tg:
        await service.start(task_group=tg)

    mock_async_context_manager.__aenter__.assert_awaited_once_with(mock_async_context_manager)

    await service.stop()

    mock_async_context_manager.__aexit__.assert_awaited_once_with(mock_async_context_manager, None, None, None)


@pytest.mark.anyio
@pytest.mark.timeout(1)
async def test_service_with_dependencies(mock_schedule_background_tasks):
    """Service must wait for dependencies to start before starting itself and stop before stopping itself"""
    service1 = Service()
    service1.schedule_background_tasks = mock_schedule_background_tasks
    service2 = Service()
    service2.schedule_background_tasks = mock_schedule_background_tasks
    service3 = Service()
    service3.schedule_background_tasks = mock_schedule_background_tasks

    service3.register_dependency(service1)
    service3.register_dependency(service2)

    async with anyio.create_task_group() as tg:
        await tg.spawn(functools.partial(service3.start, task_group=tg))
        await tg.spawn(functools.partial(service2.start, task_group=tg))
        await tg.spawn(functools.partial(service1.start, task_group=tg))

    assert service3.is_started()
    assert service2.is_started()
    assert service1.is_started()

    async with anyio.create_task_group() as tg:
        await tg.spawn(service3.stop)
        await tg.spawn(service2.stop)
        await tg.spawn(service1.stop)

    assert service3.is_stopped()
    assert service2.is_stopped()
    assert service1.is_stopped()


@pytest.mark.anyio
async def test_start_idempotency(mock_schedule_background_tasks):
    started_counter = 0

    def started_callback():
        nonlocal started_counter
        started_counter += 1

    continue_event = anyio.create_event()

    async def wait_for_continue():
        await continue_event.wait()

    started_event_mock = Mock(spec_set=anyio.Event)
    service = Service()
    service.on_enter_starting(wait_for_continue)
    service.on_enter_started(started_callback)
    service._started_event = started_event_mock
    service.schedule_background_tasks = mock_schedule_background_tasks

    result = None

    async def start_while_in_progress():
        nonlocal result
        result = await service.start.run(task_group=tg)
        await continue_event.set()

    async with anyio.create_task_group() as tg:
        await tg.spawn(functools.partial(service.start.run, task_group=tg))
        await anyio.sleep(0.1)
        await tg.spawn(start_while_in_progress)

    started_event_mock.wait.assert_awaited_once_with()
    assert result.is_success
    assert started_counter == 1

    result = await service.start.run(task_group=tg)
    assert result.is_success
    assert started_counter == 1


@pytest.mark.anyio
async def test_stop_idempotency(mock_schedule_background_tasks):
    stopped_counter = 0

    def stopped_callback():
        nonlocal stopped_counter
        stopped_counter += 1

    continue_event = anyio.create_event()

    async def wait_for_continue():
        await continue_event.wait()

    shutdown_event_mock = Mock(spec_set=anyio.Event)
    service = Service()
    service.on_enter_stopping(wait_for_continue)
    service.on_enter_stopped(stopped_callback)
    service._shutdown_event = shutdown_event_mock
    service.schedule_background_tasks = mock_schedule_background_tasks

    result = None

    async def stop_while_in_progress():
        nonlocal result
        result = await service.stop.run()
        await continue_event.set()

    async with anyio.create_task_group() as tg:
        await service.start(task_group=tg)
        await tg.spawn(service.stop.run)
        await anyio.sleep(0.1)
        await tg.spawn(stop_while_in_progress)

    shutdown_event_mock.wait.assert_awaited_once_with()
    assert result.is_success
    assert stopped_counter == 1

    result = await service.stop.run()
    assert result.is_success
    assert stopped_counter == 1
