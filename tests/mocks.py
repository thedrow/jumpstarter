try:
    from unittest.mock import Mock, MagicMock, NonCallableMock, sentinel, AsyncMock
except ImportError:
    from mock import Mock, MagicMock, NonCallableMock, sentinel, AsyncMock


def create_mock_step(
    name, requires=set(), required_by=set(), last=False, include_if=True, spec=None, mock_class=Mock,
):
    mock_step = mock_class(name=name, spec=spec)
    mock_step.requires = requires
    mock_step.required_by = required_by
    mock_step.last = last
    del mock_step.start
    del mock_step.stop
    if isinstance(include_if, bool):
        mock_step.include_if.return_value = include_if
    else:
        mock_step.include_if.side_effect = include_if

    return mock_step


def create_start_stop_mock_step(
    name, requires=set(), required_by=set(), last=False, include_if=True, mock_class=Mock,
):
    mock_step = NonCallableMock(name=name)
    mock_step.requires = requires
    mock_step.required_by = required_by
    mock_step.last = last
    mock_step.start = mock_class()
    mock_step.stop = mock_class()
    if isinstance(include_if, bool):
        mock_step.include_if.return_value = include_if
    else:
        mock_step.include_if.side_effect = include_if

    return mock_step


__all__ = (
    "create_mock_step",
    "create_start_stop_mock_step",
    "Mock",
    "MagicMock",
    "NonCallableMock",
    "sentinel",
    "AsyncMock",
)
