import nox


@nox.session(python=False)
def pydocstyle(session):
    session.run("poetry", "env", "use", "3.8", external=True)
    session.run("poetry", "install", "-v", external=True)
    session.run("poetry", "run", "pydocstyle", "jumpstarter/", external=True)


@nox.session(python=False)
def pycodestyle(session):
    session.run("poetry", "env", "use", "3.8", external=True)
    session.run("poetry", "install", "-v", external=True)
    session.run("poetry", "run", "pycodestyle", "jumpstarter/", "tests/", external=True)


@nox.session(python=False)
def black(session):
    session.run("poetry", "env", "use", "3.8", external=True)
    session.run("poetry", "install", "-v", external=True)
    session.run("poetry", "run", "black", "--check", "jumpstarter/", "tests/", external=True)


@nox.session(python=False)
@nox.parametrize('python', ('3.6', '3.7', '3.8', 'pypy3'))
def tests(session, python):
    session.run("poetry", "env", "use", python, external=True)
    session.run("poetry", "install", "-v", external=True)
    session.run("poetry", "run", "pytest", "-vvvv", "--anyio-backends", "asyncio,trio", external=True)
