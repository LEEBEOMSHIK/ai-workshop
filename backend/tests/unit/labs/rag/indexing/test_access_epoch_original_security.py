"""No security metadata is an observation, never a caller boolean or HTTP error."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.unit.labs.rag.indexing.test_access_epoch_process import process_case  # noqa: F401


@pytest.fixture
def security_case(process_case):  # noqa: F811
    from ai_workshop.labs.rag.indexing.access_epoch_original_security import (
        OriginalSecurityAbsenceReader,
    )

    c = process_case

    class Identity:
        def __init__(self):
            self.calls = 0
            self.change = False

        async def observe_original(self, snapshot):
            self.calls += 1
            return (
                replace(c.epoch.original, ephemeral_id="changed")
                if self.change and self.calls > 1
                else c.epoch.original
            )

    class Reader:
        def __init__(self):
            self.value = []
            self.fail = False
            self.paths = []

        async def read(self, path):
            self.paths.append(path)
            if self.fail:
                raise OSError("synthetic-private-error")
            return self.value

    identity, source = Identity(), Reader()
    return SimpleNamespace(
        original=c.epoch.original,
        snapshot=c.epoch.binding.claim.snapshot,
        identity=identity,
        source=source,
        reader=OriginalSecurityAbsenceReader(identity, source),
    )


async def test_empty_actual_security_index_response_issues_only_bound_observation(security_case):
    c = security_case
    result = await c.reader.observe(c.snapshot)
    assert c.reader.assert_original(result, c.original) is None
    assert c.identity.calls == 2
    assert c.source.paths == ["/_cat/indices/.security*?expand_wildcards=all&format=json&h=index"]
    with pytest.raises(ValueError):
        c.reader.assert_original(replace(result), c.original)
    with pytest.raises(ValueError):
        c.reader.assert_original(True, c.original)


@pytest.mark.parametrize("value", [None, "", {}, False, [{"index": ".security-7"}]])
async def test_missing_unknown_or_existing_security_is_not_absence(security_case, value):
    c = security_case
    c.source.value = value
    with pytest.raises(ValueError):
        await c.reader.observe(c.snapshot)


async def test_endpoint_error_or_original_identity_change_never_issues_absence(security_case):
    c = security_case
    c.source.fail = True
    with pytest.raises(ValueError):
        await c.reader.observe(c.snapshot)
    c.source.fail = False
    c.identity.change = True
    c.identity.calls = 0
    with pytest.raises(ValueError):
        await c.reader.observe(c.snapshot)
