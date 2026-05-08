"""
Unit tests for ixse/models.py.

TDD — written before the implementation.
Coverage:
  1. Session creation with all fields
  2. utilized auto-computed by model_validator (cp AND dp)
  3. SessionPort validates card and port > 0
  4. tags defaults to empty list
  5. PollStatus defaults to None / False
  6. datetime fields reject naive datetimes
"""

import pytest
from datetime import datetime, timezone, timedelta
from pydantic import ValidationError

from ixse.models import Session, SessionPort, PlaneStatus, PollStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc


def make_port(**overrides) -> dict:
    base = {"chassis_name": "lab-01", "card": 1, "port": 1}
    return {**base, **overrides}


def make_session(**overrides) -> dict:
    base = {
        "id": "sess-001",
        "name": "bgp-test",
        "ixnet_server": "ixnet-server-01",
        "ports": [make_port()],
        "cp_active": True,
        "dp_active": True,
        "last_polled": datetime.now(UTC),
    }
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# 1. Session creation with all fields
# ---------------------------------------------------------------------------


class TestSessionCreation:
    def test_full_session_round_trips(self):
        data = make_session(tags=["bgp", "lab-a"])
        s = Session(**data)
        assert s.id == "sess-001"
        assert s.name == "bgp-test"
        assert s.ixnet_server == "ixnet-server-01"
        assert len(s.ports) == 1
        assert s.cp_active is True
        assert s.dp_active is True
        assert s.tags == ["bgp", "lab-a"]
        assert isinstance(s.last_polled, datetime)

    def test_session_port_attached(self):
        s = Session(**make_session())
        port = s.ports[0]
        assert isinstance(port, SessionPort)
        assert port.chassis_name == "lab-01"
        assert port.card == 1
        assert port.port == 1

    def test_multiple_ports(self):
        ports = [make_port(card=1, port=i) for i in range(1, 5)]
        s = Session(**make_session(ports=ports))
        assert len(s.ports) == 4


# ---------------------------------------------------------------------------
# 2. utilized auto-computed via model_validator
# ---------------------------------------------------------------------------


class TestUtilizedComputation:
    @pytest.mark.parametrize(
        "cp, dp, expected",
        [
            (True, True, True),
            (True, False, False),
            (False, True, False),
            (False, False, False),
        ],
    )
    def test_session_utilized_is_cp_and_dp(self, cp: bool, dp: bool, expected: bool):
        s = Session(**make_session(cp_active=cp, dp_active=dp))
        assert s.utilized is expected

    def test_session_utilized_cannot_be_overridden_by_caller(self):
        # Even if caller passes utilized=False with both planes active,
        # the validator must recompute it to True.
        s = Session(**make_session(cp_active=True, dp_active=True, utilized=False))
        assert s.utilized is True

    def test_plane_status_utilized_is_cp_and_dp(self):
        for cp, dp, expected in [
            (True, True, True),
            (True, False, False),
            (False, True, False),
            (False, False, False),
        ]:
            ps = PlaneStatus(cp_active=cp, dp_active=dp)
            assert ps.utilized is expected, f"cp={cp} dp={dp} → expected {expected}"

    def test_plane_status_utilized_cannot_be_overridden(self):
        ps = PlaneStatus(cp_active=True, dp_active=True, utilized=False)
        assert ps.utilized is True


# ---------------------------------------------------------------------------
# 3. SessionPort validates card and port > 0
# ---------------------------------------------------------------------------


class TestSessionPortValidation:
    def test_valid_port(self):
        p = SessionPort(**make_port(card=3, port=2))
        assert p.card == 3
        assert p.port == 2

    def test_card_zero_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            SessionPort(**make_port(card=0))
        errors = exc_info.value.errors()
        assert any("card" in str(e["loc"]) for e in errors)

    def test_card_negative_raises(self):
        with pytest.raises(ValidationError):
            SessionPort(**make_port(card=-1))

    def test_port_zero_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            SessionPort(**make_port(port=0))
        errors = exc_info.value.errors()
        assert any("port" in str(e["loc"]) for e in errors)

    def test_port_negative_raises(self):
        with pytest.raises(ValidationError):
            SessionPort(**make_port(port=-5))

    def test_card_and_port_at_min_boundary(self):
        p = SessionPort(**make_port(card=1, port=1))
        assert p.card == 1
        assert p.port == 1

    def test_chassis_name_required(self):
        with pytest.raises(ValidationError):
            SessionPort(card=1, port=1)


# ---------------------------------------------------------------------------
# 4. tags defaults to empty list
# ---------------------------------------------------------------------------


class TestTagDefaults:
    def test_tags_default_empty(self):
        s = Session(**make_session())
        assert s.tags == []

    def test_tags_not_shared_between_instances(self):
        """Mutable default must not be shared (Pydantic handles this correctly)."""
        s1 = Session(**make_session())
        s2 = Session(**make_session())
        s1.tags.append("probe")
        assert s2.tags == []


# ---------------------------------------------------------------------------
# 5. PollStatus defaults to None / False
# ---------------------------------------------------------------------------


class TestPollStatusDefaults:
    def test_empty_poll_status(self):
        ps = PollStatus()
        assert ps.last_polled_at is None
        assert ps.next_scheduled is None
        assert ps.is_polling is False

    def test_poll_status_with_values(self):
        now = datetime.now(UTC)
        nxt = now + timedelta(seconds=30)
        ps = PollStatus(last_polled_at=now, next_scheduled=nxt, is_polling=True)
        assert ps.last_polled_at == now
        assert ps.next_scheduled == nxt
        assert ps.is_polling is True


# ---------------------------------------------------------------------------
# 6. datetime fields reject naive datetimes
# ---------------------------------------------------------------------------


class TestDatetimeUTCEnforcement:
    def test_session_last_polled_with_utc_accepted(self):
        now_utc = datetime.now(UTC)
        s = Session(**make_session(last_polled=now_utc))
        assert s.last_polled.tzinfo is not None

    def test_session_last_polled_naive_rejected(self):
        naive = datetime(2025, 1, 1, 12, 0, 0)  # no tzinfo
        with pytest.raises(ValidationError) as exc_info:
            Session(**make_session(last_polled=naive))
        errors = exc_info.value.errors()
        assert any("last_polled" in str(e["loc"]) for e in errors)

    def test_poll_status_naive_last_polled_at_rejected(self):
        naive = datetime(2025, 6, 1, 0, 0, 0)
        with pytest.raises(ValidationError) as exc_info:
            PollStatus(last_polled_at=naive)
        errors = exc_info.value.errors()
        assert any("last_polled_at" in str(e["loc"]) for e in errors)

    def test_poll_status_naive_next_scheduled_rejected(self):
        naive = datetime(2025, 6, 1, 0, 0, 0)
        with pytest.raises(ValidationError) as exc_info:
            PollStatus(next_scheduled=naive)
        errors = exc_info.value.errors()
        assert any("next_scheduled" in str(e["loc"]) for e in errors)

    def test_non_utc_aware_datetime_is_accepted(self):
        """Aware datetimes in non-UTC zones are valid (tz-aware, not naive)."""
        eastern = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
        # Should not raise — tz-aware is the contract, not UTC-only
        s = Session(**make_session(last_polled=eastern))
        assert s.last_polled.tzinfo is not None
