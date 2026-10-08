import pytest

from found_core.domain.auth import Caller
from found_core.domain.errors import Unauthenticated


@pytest.mark.parametrize(
    "raw",
    [["publisher", "reviewer"], "[publisher reviewer]", '["publisher","reviewer"]'],
)
def test_groups_parse_from_any_claim_shape(raw):
    caller = Caller.from_claims({"sub": "u1", "cognito:groups": raw})
    assert caller.groups == {"publisher", "reviewer"}


def test_org_and_user_come_from_claims():
    caller = Caller.from_claims({"sub": "u1", "custom:org_id": "org_h"})
    assert caller.user_id == "u1" and caller.org_id == "org_h"
    assert caller.groups == frozenset()


def test_missing_subject_is_unauthenticated():
    with pytest.raises(Unauthenticated):
        Caller.from_claims({})
    with pytest.raises(Unauthenticated):
        Caller.from_claims(None)
