"""
core.memory.tests — test suite for the L3 Project Bundle memory backend.

Run with::

    pytest core/memory/tests/ -v

or target just the integration suite::

    pytest core/memory/tests/test_integration.py -v

All tests are hermetic: they use ``tmp_path`` fixtures and do not touch
``/data/projects``. Running the suite never requires the ``anthropic``
SDK — :mod:`core.memory.auto` is imported in a try/except.
"""
