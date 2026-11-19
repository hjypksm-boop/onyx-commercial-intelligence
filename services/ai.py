"""AI copilot via Groq (Meta Llama). One wrapper with timeout, retries, low temperature and caching.

Guardrails: only structured facts for the relevant account are sent (synthetic data only); the system prompt forbids
inventing figures; every output is an "AI draft — review before use"; nothing is saved without a user action;
deterministic template fallbacks are used whenever no key is configured or the API fails.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field

from services import config

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a commercial analyst assistant inside a DEMONSTRATION customer success platform. All data is synthetic. "
    "Use ONLY the facts provided in the user's JSON. Never invent figures, names, dates, percentages or events that are "
    "not in the facts. If information you would need is missing, write 'Not recorded' and flag it explicitly. "
    "Treat low usage as a signal to investigate, not proof of dissatisfaction. Be concise and professional; "
    "use UK English and GBP (£)."
)
AI_LABEL = "AI draft — review before use"
TEMPLATE_LABEL = "AI unavailable — template draft"

_cache: dict[str, str] = {}


@dataclass
class AIResult:
    text: str
    used_ai: bool
    facts: dict = field(default_factory=dict)
    error: str | None = None
    model: str | None = None

    @property
    def label(self) -> str:
        return AI_LABEL if self.used_ai else TEMPLATE_LABEL


def available() -> bool:
    return config.groq_api_key() is not None


def _client():
    from groq import Groq
    return Groq(api_key=config.groq_api_key(), timeout=25.0, max_retries=2)


def _chat(instructions: str, facts: dict, max_tokens: int = 700) -> tuple[str | None, str | None]:
    if not available():
        return None, "No GROQ_API_KEY configured."
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{instructions}\n\nFACTS (JSON):\n{json.dumps(facts, default=str, indent=1)}"},
    ]
    model = config.groq_model()
    key = hashlib.sha256(json.dumps([model, messages, max_tokens]).encode()).hexdigest()
    if key in _cache:
        return _cache[key], None
    extra = {}
    if "gpt-oss" in model:  # reasoning models spend tokens thinking before answering
        extra["reasoning_effort"] = "low"
        max_tokens += 1024
    try:
        resp = _client().chat.completions.create(model=model, messages=messages, temperature=0.2,
                                                 max_tokens=max_tokens, **extra)
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            return None, "Empty response from model."
        _cache[key] = text
        return text, None
    except Exception as e:  # network, auth, rate limits
        log.warning("Groq call failed: %s", e)
        return None, f"{type(e).__name__}: {e}"


def generate(instructions: str, facts: dict, fallback: str, max_tokens: int = 700) -> AIResult:
    text, err = _chat(instructions, facts, max_tokens)
    if text:
        return AIResult(text, True, facts, None, config.groq_model())
    return AIResult(fallback, False, facts, err)


def test_connection() -> tuple[bool, str]:
    text, err = _chat("Reply with the single word OK.", {"ping": True}, max_tokens=16)
    return (True, f"Connected to {config.groq_model()}") if text else (False, err or "Unknown error")


# ------------------------------------------------------------------------------------------------ features
def meeting_brief(facts: dict) -> AIResult:
    risks = facts.get("health_reason", "Not recorded")
    opps = facts.get("open_opportunities") or []
    tickets = facts.get("open_tickets") or []
    fb = [f"MEETING BRIEF — {facts.get('customer')}",
          f"Context: {facts.get('vertical')} customer, £{facts.get('annual_contract_value_gbp', 0):,.0f} ARR, renewal "
          f"{facts.get('renewal_date')} ({facts.get('days_to_renewal')} days). {facts.get('active_users')} of "
          f"{facts.get('licensed_seats')} seats active ({facts.get('adoption_pct')}%).",
          f"Health: {risks}",
          "Open issues: " + ("; ".join(tickets) if tickets else "none recorded"),
          "Opportunities: " + ("; ".join(o["description"] for o in opps) if opps else "none recorded"),
          "Suggested questions:",
          "  1. How has the team's workflow changed in recent months? Who are the current power users?",
          "  2. Are you consuming our data through other channels (API, exports, shared reports)?",
          "  3. What would make the next 12 months successful for you?",
          "  4. Are there open issues blocking adoption that we should prioritise?"]
    if facts.get("missing_information"):
        fb.append("Missing data: " + " ".join(facts["missing_information"]))
    return generate("Write a concise meeting-preparation brief with sections: Context, Risks, Opportunities, "
                    "Suggested questions (4-6), Talking points. Flag missing data.", facts, "\n".join(fb))


def value_review_summary(facts: dict, template: str) -> AIResult:
    return generate("Write a 4-6 sentence executive summary for a customer value review. Mention value delivered, "
                    "adoption, risks and next steps. State missing information explicitly.", facts, template, 400)


def close_commentary(metrics: dict, template: dict) -> tuple[dict, AIResult]:
    instr = ("Draft end-of-day commercial commentary. Return ONLY a JSON object with keys performance, developments, "
             "risks, growth, priorities; each a 1-3 sentence string. Keep booked revenue and potential pipeline clearly "
             "separate. Use only these figures.")
    res = generate(instr, metrics, json.dumps(template), 900)
    if res.used_ai:
        parsed = _parse_json(res.text, dict)
        if parsed and all(k in parsed for k in template):
            return {k: str(parsed[k]) for k in template}, res
        res = AIResult(json.dumps(template), False, metrics, "Model output was not valid JSON — template used.")
    return dict(template), res


def root_cause_hypotheses(facts: dict, evidence: list[dict]) -> tuple[list[dict], AIResult]:
    payload = {**facts, "evidence": evidence}
    fallback = _rule_hypotheses(evidence)
    instr = ("Suggest 3-5 possible root causes for this account's risk as HYPOTHESES to be validated with the customer. "
             "Include at least one benign alternative explanation (e.g. seasonality, API usage, restructure). Return ONLY a "
             "JSON array of objects with keys cause, category, evidence. category must be one of: Champion change, "
             "Product / data quality, Onboarding gap, Budget / commercial, Organisational change, Seasonality, "
             "Alternative channel (API / data feed), Competitor, Other.")
    res = generate(instr, payload, json.dumps(fallback), 900)
    if res.used_ai:
        parsed = _parse_json(res.text, list)
        if parsed:
            items = [{"cause": str(p.get("cause", ""))[:400], "category": str(p.get("category", "Other")),
                      "evidence": str(p.get("evidence", ""))[:600]} for p in parsed if isinstance(p, dict) and p.get("cause")]
            if items:
                return items, res
        res = AIResult(json.dumps(fallback), False, payload, "Model output was not valid JSON — rule-based suggestions used.")
    return fallback, res


def _rule_hypotheses(evidence: list[dict]) -> list[dict]:
    out = []
    areas = {e["area"]: e["finding"] for e in evidence}
    if "Champion / contact change" in areas:
        out.append({"cause": "Loss of internal champion reduced adoption and advocacy", "category": "Champion change",
                    "evidence": areas["Champion / contact change"]})
    if "Support history" in areas or "Data availability" in areas:
        out.append({"cause": "Unresolved product / data issues eroding trust", "category": "Product / data quality",
                    "evidence": areas.get("Support history", "") + " " + areas.get("Data availability", "")})
    if "Onboarding gaps" in areas:
        out.append({"cause": "Incomplete onboarding limits depth of use", "category": "Onboarding gap",
                    "evidence": areas["Onboarding gaps"]})
    if "Account notes" in areas:
        out.append({"cause": "Organisational change at the customer", "category": "Organisational change",
                    "evidence": areas["Account notes"]})
    out.append({"cause": "Usage may have shifted to another channel (API / exports) rather than declined",
                "category": "Alternative channel (API / data feed)",
                "evidence": areas.get("API / data channel", "Check API and export volumes — not conclusive.")})
    out.append({"cause": "Seasonal trading pattern", "category": "Seasonality",
                "evidence": "Compare with the same period last year before concluding."})
    return out


def followup_email(facts: dict) -> AIResult:
    fb = (f"Subject: Thank you — {facts.get('subject', 'our meeting')}\n\n"
          f"Hi {facts.get('first_name', 'there')},\n\n"
          f"Thank you for your time on {facts.get('date')}. As discussed:\n"
          f"{facts.get('summary') or '- (summary not recorded)'}\n\n"
          f"Next steps:\n{facts.get('next_steps') or '- (next steps not recorded)'}\n\n"
          f"Best regards,\n{facts.get('sender')}")
    return generate("Draft a short, professional follow-up email after this customer meeting. Use only the facts.",
                    facts, fb, 500)


def nl_to_sql(question: str, schema_doc: str) -> AIResult:
    instr = ("Translate the question into ONE read-only SQLite-compatible SELECT statement using ONLY these views/tables:\n"
             f"{schema_doc}\nReturn only the SQL, no explanation, no markdown fences.")
    res = generate(instr, {"question": question}, "", 400)
    if res.used_ai:
        res.text = re.sub(r"^```(?:sql)?|```$", "", res.text.strip(), flags=re.M).strip()
    return res


def _parse_json(text: str, kind):
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        return None
    try:
        val = json.loads(m.group(1))
        return val if isinstance(val, kind) else None
    except json.JSONDecodeError:
        return None
