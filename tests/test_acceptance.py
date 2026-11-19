"""Section 21 acceptance values — all produced by SQL over stored records."""
from datetime import date

import pytest

from services import config, customers, db, health, kpis, opportunities, seed

from .conftest import USER


def test_arr(engine):
    assert kpis.portfolio_kpis(engine)["arr_pence"] == 270_000_00
    assert db.query_one(engine, "SELECT arr_pence FROM v_portfolio_kpis")["arr_pence"] == 270_000_00


def test_seats_and_adoption(engine):
    k = kpis.portfolio_kpis(engine)
    assert k["licensed_seats"] == 71
    assert k["active_users"] == 50
    assert round(k["adoption_pct"], 1) == 70.4


def test_calculated_health_categories(engine):
    res = {r.customer_name: r for r in health.compute(engine)}
    at_risk = {n for n, r in res.items() if r.category == "At Risk"}
    assert at_risk == {"Gulf Marine Fuels", "Meridian Commodities"}
    for n, r in res.items():
        if n not in at_risk:
            assert r.category == "Healthy" and r.score >= 80, n
        else:
            assert r.score < 60
    # the stored snapshots used by the KPI views agree with the live calculation
    stored = db.query_df(engine, "SELECT customer_name, health_category FROM v_customer_kpis")
    assert set(stored[stored.health_category == "At Risk"].customer_name) == at_risk


def test_revenue_at_risk(engine):
    assert kpis.portfolio_kpis(engine)["revenue_at_risk_pence"] == 96_000_00


def test_pipeline_totals(engine):
    t = opportunities.totals(engine)
    assert t["potential_expansion_pence"] == 62_000_00
    assert t["weighted_pipeline_pence"] == 30_200_00
    assert kpis.portfolio_kpis(engine)["potential_expansion_pence"] == 62_000_00


def test_gulf_mau_series_and_decline(engine):
    cid = db.scalar(engine, "SELECT customer_id FROM customers WHERE name = 'Gulf Marine Fuels'")
    dec = customers.mau_decline(engine, cid)
    assert dec["series"] == [10, 9, 8, 7, 5, 4]
    assert round(dec["change"] * 100) == -60
    assert dec["from_month"] == "2026-06" and dec["to_month"] == "2026-11"


def test_gulf_series_when_as_of_not_november(tmp_path):
    path = seed.build_sqlite_file(tmp_path / "march.db", "2026-03-10")
    eng = db.get_engine(config.sqlite_url(path))
    cid = db.scalar(eng, "SELECT customer_id FROM customers WHERE name = 'Gulf Marine Fuels'")
    assert customers.mau_decline(eng, cid)["series"] == [10, 9, 8, 7, 5, 4]
    assert kpis.portfolio_kpis(eng)["revenue_at_risk_pence"] == 96_000_00
    eng.dispose()


def test_counterparties_excluded(engine):
    n = db.scalar(engine, "SELECT COUNT(*) FROM counterparties")
    assert n >= 3
    k = kpis.portfolio_kpis(engine)
    assert k["accounts"] == 6  # only subscription customers
    # notional exists but never reaches ARR
    assert db.scalar(engine, "SELECT SUM(notional_usd) FROM trading_activity") > 0
    assert k["arr_pence"] == 270_000_00 and k["licensed_seats"] == 71


def test_weights_must_total_100(engine):
    bad = {"adoption": 30, "usage_trend": 25, "support": 15, "engagement": 15, "sentiment": 10}
    assert health.validate_weights(bad)
    with pytest.raises(ValueError):
        health.save_weights(engine, bad, USER)
    ok = {"adoption": 40, "usage_trend": 20, "support": 10, "engagement": 15, "sentiment": 15}
    health.save_weights(engine, ok, USER)
    assert health.get_weights(engine) == ok


def test_missing_component_renormalises():
    inp = {"customer_id": 1, "customer_name": "X", "licensed_seats": 10, "active_users": 8,
           "mau_prev3_avg": 8, "mau_last3_avg": 8, "prev3_months_with_data": 3,
           "open_high": 0, "open_medium": 0, "open_low": 0, "sla_breaches_90d": 0,
           "days_since_contact": 0, "days_to_renewal": 200, "days_since_meeting": 10,
           "sentiment_avg": None, "sentiment_n": 0}
    r = health.evaluate_row(inp, health.DEFAULT_WEIGHTS)
    assert r.available == 4
    assert r.components["sentiment"]["score"] is None
    # adoption 80, usage 80, support 100, engagement 100 with weights 30/25/15/15 re-normalised over 85
    expected = (80 * 30 + 80 * 25 + 100 * 15 + 100 * 15) / 85
    assert r.score == round(expected, 1)
    assert "Partial score" in r.reason
    assert r.score > 0


def test_expected_value():
    assert opportunities.expected_value(18_000_00, 0.5) == 9_000_00
    assert opportunities.expected_value(24_000_00, 0.6) == 14_400_00


def test_closed_won_moves_to_booked(engine):
    oid = db.scalar(engine, "SELECT opportunity_id FROM opportunities WHERE description = 'Houston port expansion'")
    as_of = db.as_of(engine)
    before = opportunities.booked_acv(engine, as_of, as_of)
    opportunities.move_stage(engine, USER, oid, "Closed Won")
    t = opportunities.totals(engine)
    assert t["potential_expansion_pence"] == 62_000_00 - 18_000_00
    assert opportunities.booked_acv(engine, as_of, as_of) == before + 18_000_00
    assert t["booked_acv_today_pence"] == 18_000_00
    hist = opportunities.stage_history(engine, oid)
    assert hist.iloc[-1]["to_stage"] == "Closed Won"


def test_as_of_is_seed_date_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AS_OF_DATE", raising=False)
    assert seed.resolve_as_of(None) == date.today()
