import pytest
from networkx import DiGraph
from tests.mocks import MagicMock


@pytest.fixture
def bootsteps_graph():
    mocked_graph = MagicMock(spec_set=DiGraph)
    mocked_graph.__iter__.return_value = []

    return mocked_graph
