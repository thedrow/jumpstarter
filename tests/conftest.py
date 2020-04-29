import textwrap
import termcolor
import pytest
from networkx import DiGraph
from tests.mocks import MagicMock


@pytest.fixture
def bootsteps_graph():
    mocked_graph = MagicMock(spec_set=DiGraph)
    mocked_graph.__iter__.return_value = []

    return mocked_graph


@pytest.fixture(scope="session", autouse=True)
def docstrings_fixture(request):
    session = request.node
    items = session.items

    for item in items:
        f = getattr(item.module, item.originalname)
        if f.__doc__:
            docstring = textwrap.indent(f.__doc__, "\t")
            for param in item.callspec.params:
                bold_param = (
                    termcolor.colored(f"{{{param}}}", color="yellow", attrs=["bold"])
                    + "\033[%dm" % termcolor.COLORS["blue"]
                    + "\033[%dm" % termcolor.ATTRIBUTES["bold"]
                )
                docstring = docstring.replace(f"{{{param}}}", bold_param)

            docstring = docstring.format(**item.callspec.params).split("\n")
            docstring[0] = termcolor.colored(docstring[0], color="blue", attrs=["bold"])
            for i, line in enumerate(docstring):
                if i == 0:
                    continue
                docstring[i] = termcolor.colored(line, color="cyan", attrs=["dark"])
            docstring = "\n".join(docstring)
            item._nodeid = f"{item.nodeid}\n{docstring}"
