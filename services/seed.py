"""Deterministic synthetic data seeder. Writes via parameterised SQL (SQLAlchemy Core).

Usage:
    python -m services.seed                 # rebuild baseline.db and the live workspace
    python -m services.seed --reset-scenarios   # also delete scenario sandboxes

All names, values and activity are fictional.
"""
from __future__ import annotations

import argparse
import calendar
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

import bcrypt
from sqlalchemy.engine import Engine

from services import audit, config, db, health

RNG_SEED = 20261118
SEED_USER = "system@demo.local"


# --------------------------------------------------------------------------------------------- helpers
def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def shift_month(d: date, n: int) -> date:
    y, m = d.year, d.month + n
    while m <= 0:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return date(y, m, 1)


def month_end(first: date) -> date:
    return date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])


def gbp(pounds: int) -> int:
    return pounds * 100


# --------------------------------------------------------------------------------------------- static data
PRODUCTS = [
    ("FB", "Flux Bunkers", "Marine fuel pricing, port coverage and procurement analytics for bunker suppliers."),
    ("FA", "Flux Analytics", "Commodity analytics, forward curves and modelling for trading desks."),
    ("OFF", "The Officials", "Market data: price assessments, benchmarks and research reports."),
]

OWNERS = [
    ("Alex Morgan", "Customer Success Executive", "alex.morgan@demo.local"),
    ("Dana Whitfield", "Commercial Director", "dana.whitfield@demo.local"),
    ("Priya Nair", "Account Manager", "priya.nair@demo.local"),
    ("Tom Ellison", "Trading Relationships Manager", "tom.ellison@demo.local"),
]

USERS = [
    ("cs.exec@demo.local", "Demo123!", "Alex Morgan", "CS_EXEC", 1),
    ("director@demo.local", "Demo123!", "Dana Whitfield", "DIRECTOR", 2),
]

# name, product, ARR £, licensed, active, ttfv days, renewal in days, owner_id, segment, region, prior ARR £, modules
CUSTOMERS = [
    ("Atlantic Bunker Co.", "FB", 48000, 12, 10, 9, 45, 1, "Mid-market", "Europe", 42000,
     "Pricing tool; Port price alerts; Supplier benchmarks; Excel add-in"),
    ("Gulf Marine Fuels", "FB", 36000, 10, 4, 26, 30, 1, "Mid-market", "Middle East", 36000,
     "Pricing tool; Port price alerts; Excel add-in"),
    ("Northstar Energy Trading", "FA", 72000, 20, 17, 12, 160, 3, "Enterprise", "Europe", 60000,
     "Forward curves; Spread analytics; Custom dashboards; Python API"),
    ("Meridian Commodities", "FA", 60000, 15, 7, 35, 55, 3, "Enterprise", "Asia-Pacific", 66000,
     "Forward curves; Spread analytics; Scenario modelling"),
    ("Harbour Refining", "OFF", 30000, 8, 7, 18, 110, 1, "Mid-market", "Europe", 30000,
     "Daily assessments; Weekly reports; Benchmark dashboard"),
    ("Summit Energy Research", "OFF", 24000, 6, 5, 14, 85, 3, "SMB", "North America", 20000,
     "Daily assessments; Weekly reports; Data download"),
]

# 13 months of MAU, oldest → newest (last value = active users; last six of Gulf = 10,9,8,7,5,4)
MAU_SERIES = {
    "Atlantic Bunker Co.": [9, 9, 9, 9, 10, 9, 10, 10, 10, 9, 10, 10, 10],
    "Gulf Marine Fuels": [10, 10, 10, 10, 10, 9, 10, 10, 9, 8, 7, 5, 4],
    "Northstar Energy Trading": [12, 12, 13, 13, 14, 14, 15, 15, 16, 16, 17, 17, 17],
    "Meridian Commodities": [13, 13, 13, 12, 12, 12, 11, 11, 10, 10, 9, 8, 7],
    "Harbour Refining": [6, 6, 6, 7, 7, 7, 7, 7, 6, 7, 7, 7, 7],
    "Summit Energy Research": [4, 4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5],
}

# (days ago, sentiment) for customer meetings
MEETINGS = {
    "Atlantic Bunker Co.": [(0, 4), (40, 5), (85, 4), (140, 4), (200, 4), (265, 5), (330, 4)],
    "Gulf Marine Fuels": [(70, 2), (130, 3), (190, 3), (250, 4), (320, 4)],
    "Northstar Energy Trading": [(0, 5), (0, 4), (38, 5), (90, 4), (150, 4), (215, 4), (290, 4), (350, 4)],
    "Meridian Commodities": [(60, 2), (120, 2), (180, 3), (240, 4), (320, 4)],
    "Harbour Refining": [(0, 4), (48, 4), (100, 4), (170, 4), (240, 3), (310, 4)],
    "Summit Energy Research": [(0, 4), (42, 4), (95, 5), (160, 4), (230, 4), (300, 4)],
}
# minimum days-ago for emails/calls (contact gaps for at-risk accounts)
CONTACT_FLOOR = {"Gulf Marine Fuels": 21, "Meridian Commodities": 28}

MEETING_SUBJECTS = {
    "FB": ["Quarterly business review", "Port coverage review", "Pricing workflow check-in", "Procurement desk catch-up"],
    "FA": ["Analytics roadmap session", "Desk usage review", "Model validation workshop", "Quarterly business review"],
    "OFF": ["Research needs review", "Benchmark coverage review", "Quarterly business review", "Editorial feedback session"],
}
AS_OF_MEETING_SUBJECTS = {
    "Atlantic Bunker Co.": ["Quarterly check-in — Houston coverage interest"],
    "Northstar Energy Trading": ["Gas desk expansion discovery", "Analytics power-user workshop"],
    "Harbour Refining": ["Benchmark coverage review"],
    "Summit Energy Research": ["Research workflow review"],
}

CONTACTS = {
    "Atlantic Bunker Co.": [("Hannah Cole", "Head of Bunker Procurement", 1, 0, None),
                            ("Liam Ortega", "Commercial Director", 0, 1, None),
                            ("Ruth Becker", "Senior Bunker Trader", 0, 0, None)],
    "Gulf Marine Fuels": [("Marco Ruiz", "Head of Pricing", 1, 0, 105),
                          ("Aisha Rahman", "Operations Director", 0, 1, None),
                          ("Kenji Watanabe", "Pricing Analyst", 0, 0, None)],
    "Northstar Energy Trading": [("Oliver Grant", "Head of Analytics", 1, 0, None),
                                 ("Sophie Lindqvist", "Chief Operating Officer", 0, 1, None),
                                 ("Raj Patel", "Head of Gas Desk", 0, 0, None)],
    "Meridian Commodities": [("Clara Jensen", "Head of Trading Operations", 1, 0, None),
                             ("Victor Hale", "Chief Financial Officer", 0, 1, None),
                             ("Nadia Petrov", "Quantitative Analyst", 0, 0, None)],
    "Harbour Refining": [("Fiona McLeod", "Market Research Lead", 1, 0, None),
                         ("Daniel Osei", "VP Strategy", 0, 1, None)],
    "Summit Energy Research": [("Ben Carter", "Research Director", 1, 1, None),
                               ("Mia Laurent", "Energy Analyst", 0, 0, None)],
}

FEATURES = {
    "FB": [("Pricing tool", "Real-time delivered bunker price lookups"),
           ("Port price alerts", "Threshold alerts by port and grade"),
           ("Supplier benchmarks", "Compare supplier quotes vs assessed prices"),
           ("Delivery scheduler", "Stem scheduling and nomination tracking"),
           ("Market commentary", "Daily marine fuel market notes"),
           ("Excel add-in", "Live prices in spreadsheets")],
    "FA": [("Forward curves", "Curve building and history"),
           ("Spread analytics", "Inter-commodity and time spreads"),
           ("Custom dashboards", "Desk dashboards and sharing"),
           ("Python API", "Programmatic data and analytics access"),
           ("Scenario modelling", "What-if and stress scenarios"),
           ("Alerts", "Market move notifications")],
    "OFF": [("Daily assessments", "End-of-day price assessments"),
            ("Weekly reports", "Weekly market research reports"),
            ("Benchmark dashboard", "Benchmark history and comparisons"),
            ("Data download", "Bulk historical data download"),
            ("Methodology library", "Assessment methodology documents"),
            ("API feed", "Programmatic price feed")],
}
# feature name -> (adopted, usage 90d)
FEATURE_USAGE = {
    "Atlantic Bunker Co.": {"Pricing tool": (1, 1420), "Port price alerts": (1, 310), "Supplier benchmarks": (1, 260),
                            "Delivery scheduler": (0, 0), "Market commentary": (1, 190), "Excel add-in": (1, 540)},
    "Gulf Marine Fuels": {"Pricing tool": (1, 380), "Port price alerts": (1, 40), "Supplier benchmarks": (0, 0),
                          "Delivery scheduler": (0, 0), "Market commentary": (1, 35), "Excel add-in": (1, 60)},
    "Northstar Energy Trading": {"Forward curves": (1, 2310), "Spread analytics": (1, 1680), "Custom dashboards": (1, 940),
                                 "Python API": (1, 15600), "Scenario modelling": (1, 420), "Alerts": (1, 610)},
    "Meridian Commodities": {"Forward curves": (1, 520), "Spread analytics": (1, 210), "Custom dashboards": (0, 0),
                             "Python API": (0, 0), "Scenario modelling": (1, 45), "Alerts": (0, 0)},
    "Harbour Refining": {"Daily assessments": (1, 880), "Weekly reports": (1, 210), "Benchmark dashboard": (1, 330),
                         "Data download": (1, 95), "Methodology library": (0, 0), "API feed": (0, 0)},
    "Summit Energy Research": {"Daily assessments": (1, 610), "Weekly reports": (1, 190), "Benchmark dashboard": (0, 0),
                               "Data download": (1, 140), "Methodology library": (1, 30), "API feed": (0, 0)},
}

PORTS = [("Singapore", "Singapore", 1.264, 103.84), ("Rotterdam", "Netherlands", 51.95, 4.14),
         ("Fujairah", "United Arab Emirates", 25.12, 56.36), ("Houston", "United States", 29.73, -95.27),
         ("Gibraltar", "Gibraltar", 36.14, -5.35), ("Antwerp", "Belgium", 51.26, 4.40),
         ("Algeciras", "Spain", 36.13, -5.44), ("Balboa", "Panama", 8.95, -79.57)]
# customer -> {port: (subscribed, base monthly lookups, stems)}
CUSTOMER_PORTS = {
    "Atlantic Bunker Co.": {"Rotterdam": (1, 140, 22), "Antwerp": (1, 90, 14), "Gibraltar": (1, 110, 18),
                            "Algeciras": (1, 60, 9), "Houston": (0, 0, 11)},
    "Gulf Marine Fuels": {"Fujairah": (1, 120, 25), "Singapore": (1, 70, 12), "Balboa": (0, 0, 4)},
}

BENCHMARKS = {
    "Harbour Refining": [("Brent Dated", "Europe", 1), ("Gasoil 0.1% NWE", "Europe", 1), ("Naphtha CIF NWE", "Europe", 1),
                         ("Jet CIF NWE", "Europe", 1), ("Mediterranean Fuel Oil", "Europe", 0), ("Singapore 380 CST", "Asia", 0)],
    "Summit Energy Research": [("WTI Houston", "Americas", 1), ("Gulf Coast ULSD", "Americas", 1),
                               ("Brent Dated", "Europe", 1), ("Canadian Heavy Diff", "Americas", 0),
                               ("LNG DES Asia", "Asia", 0), ("Gasoil 0.1% NWE", "Europe", 0)],
}

COUNTERPARTIES = [
    ("Northfold Energy Partners", "Europe", "Active", "Approved", "Crude; Fuel oil", 900, 38, 410_000_000),
    ("Corvane Commodities", "Asia-Pacific", "Active", "Under Review", "Middle distillates", 600, 22, 260_000_000),
    ("Vellmar Oil Trading", "Middle East", "Active", "Approved", "Crude; Naphtha", 1200, 30, 520_000_000),
    ("Ostrava Fuel Markets", "Europe", "Developing", "Pending KYC", "Gasoil; Biofuels", 60, 0, 0),
]


# --------------------------------------------------------------------------------------------- seeding
def build(engine: Engine, as_of: date) -> None:
    """Create schema + views in an EMPTY database and load all synthetic data."""
    rng = random.Random(RNG_SEED)
    D = as_of.isoformat()

    def ago(n: int) -> str:
        return (as_of - timedelta(days=n)).isoformat()

    def ahead(n: int) -> str:
        return (as_of + timedelta(days=n)).isoformat()

    db.run_script(engine, "schema.sql")
    ts = audit.now_ts()

    with engine.begin() as conn:
        ex = lambda sql, p=None: db.execute(conn, sql, p)  # noqa: E731
        ins = lambda sql, p: db.insert_returning_id(conn, sql, p)  # noqa: E731

        ex("INSERT INTO app_config (key, value) VALUES ('as_of_date', :d)", {"d": D})
        ex("INSERT INTO app_config (key, value) VALUES ('seeded_at', :d)", {"d": ts})
        ex("INSERT INTO app_config (key, value) VALUES ('seed_version', '1')")

        for pid, name, desc in PRODUCTS:
            ex("INSERT INTO products (product_id, name, description) VALUES (:a, :b, :c)", {"a": pid, "b": name, "c": desc})
        for name, title, email in OWNERS:
            ex("INSERT INTO owners (name, title, email) VALUES (:a, :b, :c)", {"a": name, "b": title, "c": email})
        for email, pw, dn, role, oid in USERS:
            h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=10)).decode()
            ex("INSERT INTO users (email, password_hash, display_name, role, owner_id) VALUES (:e, :h, :d, :r, :o)",
               {"e": email, "h": h, "d": dn, "r": role, "o": oid})

        ex("""INSERT INTO health_weights (adoption, usage_trend, support, engagement, sentiment, effective_from, changed_by)
              VALUES (:adoption, :usage_trend, :support, :engagement, :sentiment, :ts, :u)""",
           {**health.DEFAULT_WEIGHTS, "ts": ts, "u": SEED_USER})

        port_ids = {}
        for name, country, lat, lon in PORTS:
            port_ids[name] = ins("INSERT INTO ports (name, country, latitude, longitude) VALUES (:a,:b,:c,:d) RETURNING port_id",
                                 {"a": name, "b": country, "c": lat, "d": lon})
        feat_ids = {}
        for pid, feats in FEATURES.items():
            for fname, fdesc in feats:
                feat_ids[(pid, fname)] = ins(
                    "INSERT INTO feature_catalogue (product_id, name, description) VALUES (:p,:n,:d) RETURNING feature_id",
                    {"p": pid, "n": fname, "d": fdesc})

        months = [shift_month(as_of.replace(day=1), -i) for i in range(12, -1, -1)]  # 13 months oldest→newest
        cust_ids: dict[str, int] = {}
        contact_ids: dict[str, list[int]] = {}

        for (name, pid, arr, lic, act, ttfv, renew_in, owner, seg, region, prior_arr, modules) in CUSTOMERS:
            renewal = as_of + timedelta(days=renew_in)
            cur_start = renewal - timedelta(days=365)
            prior_start = cur_start - timedelta(days=365)
            since = prior_start
            cid = ins("""INSERT INTO customers (name, product_id, segment, hq_region, owner_id, customer_since, status)
                         VALUES (:n,:p,:s,:r,:o,:since,'Active') RETURNING customer_id""",
                      {"n": name, "p": pid, "s": seg, "r": region, "o": owner, "since": since.isoformat()})
            cust_ids[name] = cid
            ex("""INSERT INTO subscriptions (customer_id, product_id, licensed_seats, active_users, status)
                  VALUES (:c,:p,:l,:a,'Active')""", {"c": cid, "p": pid, "l": lic, "a": act})
            ex("""INSERT INTO contracts (customer_id, start_date, renewal_date, term_months, arr_pence, status,
                  billing_frequency, modules, is_current) VALUES (:c,:s,:r,12,:arr,'Renewed',:b,:m,0)""",
               {"c": cid, "s": prior_start.isoformat(), "r": cur_start.isoformat(), "arr": gbp(prior_arr),
                "b": "Annual", "m": modules})
            ex("""INSERT INTO contracts (customer_id, start_date, renewal_date, term_months, arr_pence, status,
                  billing_frequency, modules, is_current) VALUES (:c,:s,:r,12,:arr,'Active',:b,:m,1)""",
               {"c": cid, "s": cur_start.isoformat(), "r": renewal.isoformat(), "arr": gbp(arr),
                "b": "Quarterly" if arr < 30000 else "Annual", "m": modules})

            # onboarding milestones
            ms = [("Kick-off call", 2), ("Users provisioned", 5), ("First value achieved", ttfv),
                  ("Core training completed", ttfv + 10), ("Workflow / API integration", ttfv + 30)]
            for seq, (mname, offset) in enumerate(ms, start=1):
                target = since + timedelta(days=[3, 7, 21, 30, 60][seq - 1])
                done = since + timedelta(days=offset)
                incomplete = (name == "Gulf Marine Fuels" and seq >= 4) or (name == "Meridian Commodities" and seq == 5)
                ex("""INSERT INTO onboarding_milestones (customer_id, seq, milestone, target_date, completed_date, is_first_value)
                      VALUES (:c,:s,:m,:t,:d,:f)""",
                   {"c": cid, "s": seq, "m": mname, "t": target.isoformat(),
                    "d": None if incomplete else done.isoformat(), "f": 1 if seq == 3 else 0})

            # contacts
            contact_ids[name] = []
            for cname, title, champ, dm, left_ago in CONTACTS[name]:
                email = cname.lower().replace(" ", ".") + "@" + name.split()[0].lower() + ".example"
                contact_ids[name].append(ins(
                    """INSERT INTO contacts (customer_id, name, title, email, is_champion, is_decision_maker, status, left_date)
                       VALUES (:c,:n,:t,:e,:ch,:dm,:st,:ld) RETURNING contact_id""",
                    {"c": cid, "n": cname, "t": title, "e": email, "ch": champ, "dm": dm,
                     "st": "Left" if left_ago else "Active", "ld": ago(left_ago) if left_ago else None}))

            # daily usage from the MAU series
            series = MAU_SERIES[name]
            assert series[-1] == act, f"{name}: last MAU must equal active users"
            for i, mstart in enumerate(months):
                mau = series[i]
                last_day = min(month_end(mstart), as_of)
                days = [mstart + timedelta(days=k) for k in range((last_day - mstart).days + 1)]
                workdays = [d for d in days if d.weekday() < 5] or days
                intensity = 0.55 if name != "Gulf Marine Fuels" else max(0.2, 0.55 - 0.05 * max(0, i - 6))
                for u in range(1, mau + 1):
                    ukey = f"U{u:02d}"
                    picked = [d for d in workdays if rng.random() < intensity]
                    if not picked:
                        picked = [rng.choice(workdays)]
                    for d in picked:
                        logins = rng.randint(1, 3)
                        sessions = logins + rng.randint(0, 3)
                        row = {"c": cid, "d": d.isoformat(), "u": ukey, "l": logins, "s": sessions,
                               "pq": 0, "ar": 0, "rd": 0, "api": 0}
                        if pid == "FB":
                            row["pq"] = rng.randint(3, 14)
                        elif pid == "FA":
                            heavy = name == "Northstar Energy Trading"
                            row["ar"] = rng.randint(2, 10) if heavy else rng.randint(0, 4)
                            row["api"] = rng.randint(80, 260) if heavy else rng.randint(0, 20)
                        else:
                            row["rd"] = rng.randint(0, 3)
                            row["api"] = rng.randint(0, 30) if name == "Harbour Refining" else rng.randint(0, 8)
                        ex("""INSERT INTO usage_daily (customer_id, usage_date, user_key, logins, sessions, pricing_queries,
                              analytics_runs, reports_downloaded, api_calls) VALUES (:c,:d,:u,:l,:s,:pq,:ar,:rd,:api)""", row)

            # feature usage
            for fname, (adopted, cnt) in FEATURE_USAGE[name].items():
                ex("""INSERT INTO feature_usage (customer_id, feature_id, adopted, usage_count_90d, first_used_date)
                      VALUES (:c,:f,:a,:n,:d)""",
                   {"c": cid, "f": feat_ids[(pid, fname)], "a": adopted, "n": cnt,
                    "d": (since + timedelta(days=ttfv + rng.randint(0, 120))).isoformat() if adopted else None})

            # ports & port activity
            for pname, (sub, base, stems) in CUSTOMER_PORTS.get(name, {}).items():
                ex("INSERT INTO customer_ports (customer_id, port_id, subscribed) VALUES (:c,:p,:s)",
                   {"c": cid, "p": port_ids[pname], "s": sub})
                for i, mstart in enumerate(months):
                    factor = series[i] / max(series)
                    ex("""INSERT INTO port_activity (customer_id, port_id, month, price_lookups, stems_reported)
                          VALUES (:c,:p,:m,:l,:s)""",
                       {"c": cid, "p": port_ids[pname], "m": month_key(mstart),
                        "l": int(base * factor * rng.uniform(0.85, 1.15)) if sub else 0,
                        "s": max(0, int(stems * (0.6 + 0.4 * factor) * rng.uniform(0.8, 1.2)))})

            for bname, breg, blic in BENCHMARKS.get(name, []):
                ex("INSERT INTO benchmark_coverage (customer_id, benchmark, region, licensed) VALUES (:c,:b,:r,:l)",
                   {"c": cid, "b": bname, "r": breg, "l": blic})

            # meetings / correspondence history
            subjects = MEETING_SUBJECTS[pid]
            contacts_here = [c for c in CONTACTS[name]]
            as_of_subjects = list(AS_OF_MEETING_SUBJECTS.get(name, []))
            for k, (dago, sent) in enumerate(MEETINGS[name]):
                if dago == 0 and as_of_subjects:
                    subj = as_of_subjects.pop(0)
                else:
                    subj = subjects[k % len(subjects)]
                active_contacts = [c[0] for c in contacts_here if not c[4] or c[4] < dago]
                attendees = ", ".join(active_contacts[:2] + [OWNERS[owner - 1][0]])
                summary = _meeting_summary(name, sent, dago)
                ex("""INSERT INTO activities (customer_id, activity_type, activity_date, subject, summary, attendees,
                      sentiment, next_steps, owner_id, created_by, created_at)
                      VALUES (:c,'Meeting',:d,:s,:sm,:a,:se,:n,:o,:u,:ts)""",
                   {"c": cid, "d": ago(dago), "s": subj, "sm": summary, "a": attendees, "se": sent,
                    "n": "Share recap and agreed actions", "o": owner, "u": SEED_USER, "ts": ts})
            floor = CONTACT_FLOOR.get(name, 3)
            dago = floor
            k = 0
            while dago < 365:
                typ = "Email" if k % 2 == 0 else "Call"
                ex("""INSERT INTO activities (customer_id, activity_type, activity_date, subject, summary, owner_id,
                      created_by, created_at) VALUES (:c,:t,:d,:s,:sm,:o,:u,:ts)""",
                   {"c": cid, "t": typ, "d": ago(dago),
                    "s": ["Usage report shared", "Renewal timeline check", "Product update follow-up",
                          "Support ticket update", "Training invitation"][k % 5],
                    "sm": f"{typ} with {CONTACTS[name][min(k % 2, len(CONTACTS[name]) - 1)][0]}.", "o": owner,
                    "u": SEED_USER, "ts": ts})
                dago += rng.randint(12, 24)
                k += 1

        # ---------------------------------------------------------------- support tickets
        T = lambda c, subj, sev, status, opened, closed, sla, breach, esc: ex(  # noqa: E731
            """INSERT INTO support_tickets (customer_id, subject, severity, status, opened_date, closed_date, sla_hours,
               sla_breached, escalated) VALUES (:c,:s,:sev,:st,:o,:cl,:sla,:b,:e)""",
            {"c": cust_ids[c], "s": subj, "sev": sev, "st": status, "o": ago(opened),
             "cl": ago(closed) if closed is not None else None, "sla": sla, "b": breach, "e": esc})
        T("Gulf Marine Fuels", "Fujairah price feed latency during Asian hours", "High", "In progress", 34, None, 24, 1, 1)
        T("Gulf Marine Fuels", "Excel add-in authentication errors after password reset", "Medium", "Open", 18, None, 48, 0, 0)
        T("Gulf Marine Fuels", "Singapore grade mapping question", "Low", "Closed", 140, 137, 72, 0, 0)
        T("Gulf Marine Fuels", "Alert emails delayed", "Medium", "Closed", 210, 205, 48, 0, 0)
        T("Meridian Commodities", "Forward curve gaps — Brent/Dubai spreads", "High", "In progress", 25, None, 24, 1, 1)
        T("Meridian Commodities", "Scenario model export timeout", "Medium", "Closed", 70, 60, 48, 1, 0)
        T("Meridian Commodities", "SSO configuration change", "Low", "Closed", 190, 188, 72, 0, 0)
        T("Northstar Energy Trading", "Dashboard export formatting", "Low", "Open", 6, None, 72, 0, 0)
        T("Northstar Energy Trading", "API rate limit increase request", "Medium", "Closed", 75, 73, 48, 0, 0)
        T("Northstar Energy Trading", "Curve rebuild slow at month end", "High", "Closed", 160, 158, 24, 0, 0)
        T("Atlantic Bunker Co.", "New user onboarding — trader accounts", "Low", "Closed", 55, 54, 72, 0, 0)
        T("Atlantic Bunker Co.", "Gibraltar price alert threshold bug", "Medium", "Closed", 180, 176, 48, 1, 0)
        T("Harbour Refining", "Report PDF download failing in Edge", "Low", "Closed", 95, 93, 72, 0, 0)
        T("Summit Energy Research", "Report PDF font rendering", "Low", "Open", 9, None, 72, 0, 0)
        T("Summit Energy Research", "Historical data file missing column", "Medium", "Closed", 120, 117, 48, 0, 0)

        # data availability incidents (Flux Analytics)
        for c, dago, ds, hrs, imp, res in [
            ("Meridian Commodities", 12, "ICE Brent spreads", 9.5, "High", 11),
            ("Meridian Commodities", 33, "Dubai partials", 6.0, "Medium", 32),
            ("Meridian Commodities", 64, "Forward curve history", 14.0, "High", 62),
            ("Meridian Commodities", 150, "Fuel oil cracks", 3.0, "Low", 150),
            ("Northstar Energy Trading", 41, "European gas curves", 2.0, "Low", 41),
            ("Northstar Energy Trading", 200, "Power forwards", 4.5, "Medium", 199),
        ]:
            ex("""INSERT INTO data_incidents (customer_id, incident_date, dataset, duration_hours, impact, resolved_date)
                  VALUES (:c,:d,:ds,:h,:i,:r)""",
               {"c": cust_ids[c], "d": ago(dago), "ds": ds, "h": hrs, "i": imp, "r": ago(res)})

        # ---------------------------------------------------------------- AS_OF day activity (baseline)
        A = lambda c, typ, subj, summ, cp=None, sent=None, owner=1: ex(  # noqa: E731
            """INSERT INTO activities (customer_id, counterparty_id, activity_type, activity_date, subject, summary,
               sentiment, owner_id, created_by, created_at) VALUES (:c,:cp,:t,:d,:s,:sm,:se,:o,:u,:ts)""",
            {"c": cust_ids.get(c) if c else None, "cp": cp, "t": typ, "d": D, "s": subj, "sm": summ, "se": sent,
             "o": owner, "u": SEED_USER, "ts": ts})
        A("Harbour Refining", "Demo", "Benchmark dashboard demonstration",
          "Walked the research team through benchmark comparisons; strong interest in additional regional reports.")
        A("Summit Energy Research", "Email", "Meeting recap and broader data access outline",
          "Sent recap with outline of broader data access options.", owner=3)
        A("Meridian Commodities", "Escalation", "Escalated curve data gaps to Data Operations",
          "Third data availability incident in 90 days escalated to Data Operations lead.", owner=3)

        # ---------------------------------------------------------------- counterparties
        cp_ids = {}
        for (cname, region, rel, appr, prods, avg_trades, _, base_notional) in COUNTERPARTIES:
            cp_ids[cname] = ins("""INSERT INTO counterparties (name, region, relationship_status, approval_status, owner_id,
                                   relationship_since, primary_products) VALUES (:n,:r,:rs,:a,4,:s,:p) RETURNING counterparty_id""",
                                {"n": cname, "r": region, "rs": rel, "a": appr, "s": ago(rng.randint(400, 1200)), "p": prods})
            first = cname.split()[0]
            ins("""INSERT INTO contacts (counterparty_id, name, title, email, is_champion, is_decision_maker)
                   VALUES (:c,:n,:t,:e,1,1) RETURNING contact_id""",
                {"c": cp_ids[cname], "n": f"{['Elise', 'Hugo', 'Samir', 'Petra'][len(cp_ids) - 1]} {first}son",
                 "t": "Head of Origination", "e": f"origination@{first.lower()}.example"})
            for i, mstart in enumerate(months[1:]):
                if appr == "Pending KYC":
                    trades, notional = 0, 0
                else:
                    trades = max(0, int(avg_trades / 12 * rng.uniform(0.7, 1.3)))
                    notional = int(base_notional / 12 * rng.uniform(0.6, 1.4))
                ex("INSERT INTO trading_activity (counterparty_id, month, trade_count, notional_usd) VALUES (:c,:m,:t,:n)",
                   {"c": cp_ids[cname], "m": month_key(mstart), "t": trades, "n": notional})
        for cname, typ, desc, sev, status, opened, resolved in [
            ("Corvane Commodities", "Confirmation", "Late trade confirmations on two gasoil cargoes", "Medium", "Open", 9, None),
            ("Corvane Commodities", "Credit", "Credit line review pending updated financials", "High", "In progress", 21, None),
            ("Northfold Energy Partners", "Settlement", "Invoice quantity mismatch on Forties cargo", "Low", "Resolved", 60, 52),
            ("Vellmar Oil Trading", "Execution", "Price-fixing window dispute on naphtha deal", "Medium", "Open", 4, None),
            ("Ostrava Fuel Markets", "Service", "KYC documentation outstanding (UBO register)", "Medium", "Open", 15, None),
        ]:
            ex("""INSERT INTO counterparty_issues (counterparty_id, issue_type, description, severity, status, opened_date,
                  resolved_date, owner_id) VALUES (:c,:t,:d,:s,:st,:o,:r,4)""",
               {"c": cp_ids[cname], "t": typ, "d": desc, "s": sev, "st": status, "o": ago(opened),
                "r": ago(resolved) if resolved is not None else None})
        for cname, subj in [("Northfold Energy Partners", "Q1 crude programme planning"),
                            ("Corvane Commodities", "Confirmation process review"),
                            ("Vellmar Oil Trading", "Naphtha pricing dispute resolution")]:
            A(None, "Meeting", subj, "Relationship meeting with origination team.", cp=cp_ids[cname], owner=4)
        for cname in cp_ids:
            for dago in (35, 80, 140):
                ex("""INSERT INTO activities (counterparty_id, activity_type, activity_date, subject, summary, owner_id,
                      created_by, created_at) VALUES (:c,'Call',:d,'Relationship check-in','Routine call.',4,:u,:ts)""",
                   {"c": cp_ids[cname], "d": ago(dago + len(cname) % 7), "u": SEED_USER, "ts": ts})

        # ---------------------------------------------------------------- opportunities
        opp = lambda c, pid, desc, pounds, prob, stage, created, close, owner, nxt, closed=None, path=(): _opp(  # noqa: E731
            conn, cust_ids[c], pid, desc, gbp(pounds), prob, stage, ago(created), ahead(close) if close >= 0 else ago(-close),
            owner, nxt, ago(closed) if closed is not None else None, [(s, ago(d)) for s, d in path])
        opp("Atlantic Bunker Co.", "FB", "Houston port expansion", 18000, 0.5, "Qualified", 35, 40, 1,
            "Send Houston coverage proposal with sample pricing", path=[("Identified", 35), ("Qualified", 14)])
        opp("Northstar Energy Trading", "FA", "Additional analytics seats", 24000, 0.6, "Proposal", 50, 30, 3,
            "Confirm seat count and gas desk start date with COO",
            path=[("Identified", 50), ("Qualified", 31), ("Proposal", 9)])
        opp("Harbour Refining", "OFF", "Additional market reports", 12000, 0.3, "Identified", 12, 75, 1,
            "Scope regional report bundle after demo", path=[("Identified", 12)])
        opp("Summit Energy Research", "OFF", "Broader data access", 8000, 0.4, "Qualified", 28, 60, 3,
            "Share data access tiers and pricing", path=[("Identified", 28), ("Qualified", 10)])
        opp("Northstar Energy Trading", "FA", "Python API add-on", 12000, 1.0, "Closed Won", 400, -205, 3,
            "Delivered", closed=205, path=[("Identified", 400), ("Proposal", 300), ("Closed Won", 205)])
        opp("Meridian Commodities", "FA", "Freight analytics module", 15000, 0.0, "Closed Lost", 260, -150, 3,
            "Lost — budget freeze", closed=150, path=[("Identified", 260), ("Qualified", 220), ("Closed Lost", 150)])

        # ---------------------------------------------------------------- tasks
        for title, c, cat, pri, owner, due, status, notes, cp in [
            ("Prepare Gulf Marine renewal risk brief", "Gulf Marine Fuels", "Renewal preparation", "Critical", 1, -3, "Open",
             "Renewal in 30 days; usage down sharply.", None),
            ("Chase Fujairah latency fix with Data Ops", "Gulf Marine Fuels", "Customer escalation", "High", 1, -5,
             "In progress", "Ticket breached SLA.", None),
            ("Send Meridian incident RCA", "Meridian Commodities", "Customer escalation", "High", 3, -2, "Open", None, None),
            ("Book Meridian executive sponsor call", "Meridian Commodities", "Renewal preparation", "High", 3, 0, "Open",
             "No meeting in 60 days.", None),
            ("Send Atlantic QBR recap", "Atlantic Bunker Co.", "Sales follow-up", "Medium", 1, 0, "Open", None, None),
            ("Compile daily commercial summary", None, "Commercial reporting", "Medium", 1, 0, "Open", None, None),
            ("Houston coverage proposal", "Atlantic Bunker Co.", "Sales follow-up", "High", 1, 1, "Open", None, None),
            ("Northstar gas desk seat proposal", "Northstar Energy Trading", "Sales follow-up", "High", 3, 1, "Open", None, None),
            ("Harbour regional reports demo follow-up", "Harbour Refining", "Product demonstration", "Medium", 1, 3, "Open",
             None, None),
            ("Summit data access pricing", "Summit Energy Research", "Sales follow-up", "Medium", 3, 5, "Open", None, None),
            ("Gulf Marine: re-run core training", "Gulf Marine Fuels", "Onboarding", "Medium", 1, 7, "Open",
             "Core training milestone never completed.", None),
            ("Corvane credit review documents", None, "Customer escalation", "High", 4, 2, "Blocked",
             "Awaiting financials.", "Corvane Commodities"),
            ("Ostrava KYC follow-up", None, "Onboarding", "Medium", 4, 4, "Open", None, "Ostrava Fuel Markets"),
            ("Northstar renewal planning", "Northstar Energy Trading", "Renewal preparation", "Low", 3, 30, "Open", None, None),
            ("Summit onboarding survey", "Summit Energy Research", "Onboarding", "Low", 3, -20, "Done", None, None),
            ("Harbour Q3 usage report", "Harbour Refining", "Commercial reporting", "Low", 1, -10, "Done", None, None),
        ]:
            ex("""INSERT INTO tasks (title, customer_id, counterparty_id, category, priority, owner_id, due_date, status,
                  notes, source, created_on, completed_on) VALUES (:t,:c,:cp,:cat,:p,:o,:d,:s,:n,'Seed',:cr,:co)""",
               {"t": title, "c": cust_ids.get(c) if c else None, "cp": cp_ids.get(cp) if cp else None, "cat": cat,
                "p": pri, "o": owner, "d": ahead(due) if due >= 0 else ago(-due), "s": status, "n": notes,
                "cr": ago(max(1, -due + 7) if due < 0 else 7),
                "co": ago(-due) if status == "Done" else None})

        # account notes
        for c, dago, body in [
            ("Gulf Marine Fuels", 100, "Marco Ruiz (champion, Head of Pricing) has left the business. Kenji Watanabe is the "
                                       "day-to-day contact but has no budget authority."),
            ("Meridian Commodities", 75, "Meridian announced a desk restructure in APAC; two analysts moved to a new team."),
            ("Northstar Energy Trading", 20, "New gas desk launching next quarter — Raj Patel hiring 4 analysts."),
            ("Atlantic Bunker Co.", 30, "Atlantic expanding supply operations into the US Gulf; Houston pricing requested."),
        ]:
            ex("INSERT INTO account_notes (customer_id, note_date, author, body) VALUES (:c,:d,:a,:b)",
               {"c": cust_ids[c], "d": ago(dago), "a": "alex.morgan@demo.local", "b": body})

        audit.log(conn, SEED_USER, "database", None, "create", f"Demonstration database seeded (as of {D})")

    db.run_script(engine, "views.sql")
    # health history: previous 11 month-ends, then the as-of snapshot
    hist = [month_end(shift_month(as_of.replace(day=1), -i)).isoformat() for i in range(11, 0, -1)]
    health.write_history(engine, hist)
    health.refresh_snapshots(engine)


def _meeting_summary(name: str, sentiment: int, dago: int) -> str:
    tone = {5: "Very positive", 4: "Positive", 3: "Neutral", 2: "Concerned", 1: "Negative"}[sentiment]
    extra = ""
    if name == "Gulf Marine Fuels" and dago == 70:
        extra = " New pricing contact unsure how the team uses the tool after the champion's departure; raised Fujairah latency."
    if name == "Meridian Commodities" and dago == 60:
        extra = " Trading ops frustrated by repeated curve data gaps; CFO reviewing all data spend."
    if name == "Northstar Energy Trading" and dago == 0:
        extra = " Gas desk launching; 4–6 new analysts need seats; heavy Python API usage."
    return f"{tone} meeting.{extra}"


def _opp(conn, cid, pid, desc, pence, prob, stage, created, close, owner, nxt, closed, path):
    oid = db.insert_returning_id(
        conn,
        """INSERT INTO opportunities (customer_id, product_id, description, potential_arr_pence, probability, stage,
           expected_close_date, owner_id, next_action, created_date, closed_date)
           VALUES (:c,:p,:d,:v,:pr,:s,:cl,:o,:n,:cr,:cd) RETURNING opportunity_id""",
        {"c": cid, "p": pid, "d": desc, "v": pence, "pr": prob, "s": stage, "cl": close, "o": owner, "n": nxt,
         "cr": created, "cd": closed})
    prev = None
    for s, d in path:
        db.execute(conn, """INSERT INTO opportunity_stage_history (opportunity_id, from_stage, to_stage, changed_on, changed_by)
                            VALUES (:o,:f,:t,:d,:u)""", {"o": oid, "f": prev, "t": s, "d": d, "u": SEED_USER})
        prev = s
    return oid


# --------------------------------------------------------------------------------------------- orchestration
def resolve_as_of(as_of: str | date | None = None) -> date:
    if isinstance(as_of, date):
        return as_of
    s = as_of or config.as_of_override()
    return date.fromisoformat(s) if s else date.today()


def build_sqlite_file(path: Path, as_of: str | date | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    url = config.sqlite_url(path)
    db.dispose(url)
    tmp = path.with_suffix(".building")
    if tmp.exists():
        tmp.unlink()
    tmp_url = config.sqlite_url(tmp)
    eng = db.get_engine(tmp_url)
    build(eng, resolve_as_of(as_of))
    eng.dispose()
    db.get_engine.cache_clear()
    shutil.move(tmp, path)
    return path


def reset_scenarios() -> None:
    config.SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    for f in config.SCENARIO_DIR.glob("*.db"):
        db.dispose(config.sqlite_url(f))
        f.unlink()


def reset_live(as_of: str | date | None = None) -> None:
    """Rebuild baseline.db, then make the live workspace a fresh copy (or reseed PostgreSQL)."""
    build_sqlite_file(config.BASELINE_DB_PATH, as_of)
    url = config.database_url()
    if url.startswith("sqlite"):
        live = Path(url.replace("sqlite:///", ""))
        db.dispose(url)
        db.get_engine.cache_clear()
        shutil.copyfile(config.BASELINE_DB_PATH, live)
    else:
        eng = db.get_engine(url)
        _drop_all_postgres(eng)
        build(eng, resolve_as_of(as_of))
    reset_scenarios()


def _drop_all_postgres(engine: Engine) -> None:  # pragma: no cover - requires PostgreSQL
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


def ensure_ready() -> None:
    """Create the databases on first run."""
    if not config.BASELINE_DB_PATH.exists():
        build_sqlite_file(config.BASELINE_DB_PATH)
    url = config.database_url()
    if url.startswith("sqlite"):
        live = Path(url.replace("sqlite:///", ""))
        if not live.exists():
            shutil.copyfile(config.BASELINE_DB_PATH, live)
    else:  # pragma: no cover
        eng = db.get_engine(url)
        if not db.table_exists(eng, "app_config"):
            build(eng, resolve_as_of(None))


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed the ONYX demonstration database")
    ap.add_argument("--as-of", help="Demo clock date YYYY-MM-DD (default: AS_OF_DATE env or today)")
    ap.add_argument("--reset-scenarios", action="store_true", help="(always done) kept for Makefile compatibility")
    args = ap.parse_args()
    reset_live(args.as_of)
    eng = db.get_engine(config.database_url())
    k = db.query_one(eng, "SELECT * FROM v_portfolio_kpis")
    print(f"Seeded. As of {db.as_of(eng)} — ARR £{k['arr_pence'] / 100:,.0f}, adoption {k['adoption_pct']:.1f}%, "
          f"revenue at risk £{k['revenue_at_risk_pence'] / 100:,.0f}, potential expansion "
          f"£{k['potential_expansion_pence'] / 100:,.0f}")


if __name__ == "__main__":
    main()
