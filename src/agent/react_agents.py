import logging
from typing import Dict, Any
import os
import json
from openai import OpenAI
from src.helpers.sentience_engine import process_email_for_memory
from src.partner import (
    load_partner_profile,
    learn_from_interaction,
    generate_partner_response,
    process_capital_request,
    handle_digest_request,
    Partner
)
from weekly_digest import VCDigestGenerator

logger = logging.getLogger("react_agents")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

CAPITAL_REQUEST_TEMPLATE = {
    "amount": None,
    "company": None,
    "investment_stage": None,
    "round_details": None,
    "due_diligence_status": None
}

def coerce_capital_request(val):
    if isinstance(val, dict):
        # Fill missing keys with None
        return {k: val.get(k) for k in CAPITAL_REQUEST_TEMPLATE}
    else:
        # If it's a string or None, return empty template
        return CAPITAL_REQUEST_TEMPLATE.copy()

class EmailProcessingAgent:
    def _llm_extract_email_info(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use LLM to extract intent, urgency, action items, entities, etc. from the email.
        """
        body = state.get("body", "")
        subject = state.get("subject", "No Subject")
        sender = state.get("sender_email", "")
        prompt = f"""
You are an expert executive assistant. Analyze this email and extract information in STRICT JSON format.

Email Subject: {subject}
Email From: {sender}
Email Body:
---
{body}
---

Respond with ONLY valid JSON containing these exact fields:
{{{{
  "intent": "short summary of what sender wants",
  "urgency_score": 5,
  "action_items": [],
  "deadline": null,
  "tone": "neutral",
  "risks": "",
  "capital_request": {{{{
    "amount": null,
    "company": null,
    "investment_stage": null,
    "round_details": null,
    "due_diligence_status": null
  }}}},
  "sentiment_score": 0.0,
  "entities": {{{{}}}}
}}}}
IMPORTANT: Your entire response must be valid JSON. Do not include any text before or after the JSON.
"""
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You respond only with valid JSON. No explanations or additional text."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=900
            )
            content = response.choices[0].message.content.strip()
            
            # Clean up the response if it has markdown formatting
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            result = json.loads(content)
            # Coerce capital_request
            result["capital_request"] = coerce_capital_request(result.get("capital_request"))
            return result
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed: {e}, content: {content[:200]}")
            return None
        except Exception as e:
            logger.error(f"LLM email extraction failed: {e}")
            return None

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("[EmailProcessingAgent] LLM-based extraction of email info...")
        llm_result = self._llm_extract_email_info(state)
        if llm_result:
            state["email_analysis"] = llm_result
        else:
            # Fallback: minimal safe default
            state["email_analysis"] = {
                "intent": "General note",
                "urgency_score": 1,
                "action_items": [],
                "deadline": None,
                "tone": "neutral",
                "risks": "",
                "capital_request": CAPITAL_REQUEST_TEMPLATE.copy(),
                "sentiment_score": 0.0,
                "entities": {}
            }
        return state

class PartnerProfileAgent:
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("[PartnerProfileAgent] Loading and updating partner profile...")
        try:
            sender = state.get("sender_email") or state.get("email_analysis", {}).get("sender")
            partner = load_partner_profile(sender)
            if not partner:
                # Fallback minimal profile
                partner = Partner(
                    email=sender,
                    name=sender.split("@")[0].title(),
                    role="Partner"
                )
            email_analysis = state.get("email_analysis", {})
            if email_analysis:
                class EmailAnalysisObj:
                    def __init__(self, data, state):
                        self.subject = state.get("subject", "")
                        self.intent = data.get("intent", "")
                        self.sentiment_score = data.get("sentiment_score", 0.0)
                        self.tone = data.get("tone", "neutral")
                        cr = data.get("capital_request")
                        if isinstance(cr, dict):
                            self.capital_request = cr
                        else:
                            self.capital_request = CAPITAL_REQUEST_TEMPLATE.copy()
                        self.deadline = data.get("deadline")
                analysis_obj = EmailAnalysisObj(email_analysis, state)
                learn_from_interaction(sender, analysis_obj)
            state["partner_profile"] = partner
        except Exception as e:
            logger.error(f"PartnerProfileAgent failed: {e}")
            # Fallback minimal profile
            sender = state.get("sender_email", "unknown@unknown.com")
            partner = Partner(
                email=sender,
                name=sender.split("@")[0].title(),
                role="Partner"
            )
            state["partner_profile"] = partner
        return state

class InvestmentAnalysisAgent:
    def _llm_investment_analysis(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use LLM to analyze the investment opportunity, summarize risks, and provide a recommendation.
        """
        email_analysis = state.get("email_analysis", {})
        prompt = f"""
        You are a venture capital analyst. Analyze this email for investment opportunities.

        Email Analysis: {json.dumps(email_analysis, indent=2)}

        Respond with ONLY valid JSON containing these exact fields:
        {{
            "investment_summary": "1-2 sentence summary",
            "risks": ["risk1", "risk2"],
            "opportunities": ["opp1", "opp2"],
            "recommendation": "Pass",
            "rationale": "short explanation"
        }}

        IMPORTANT: Your entire response must be valid JSON. No explanations or additional text.
        """
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You respond only with valid JSON. No explanations or additional text."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=700
            )
            content = response.choices[0].message.content.strip()
            
            # Clean up the response if it has markdown formatting
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed: {e}, content: {content[:200]}")
            return None
        except Exception as e:
            logger.error(f"LLM investment analysis failed: {e}")
            return None

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("[InvestmentAnalysisAgent] LLM-based investment analysis...")
        llm_result = self._llm_investment_analysis(state)
        if llm_result:
            state["capital_analysis"] = llm_result
        else:
            state["capital_analysis"] = {
                "investment_summary": "No analysis available.",
                "risks": [],
                "opportunities": [],
                "recommendation": "Consider",
                "rationale": "LLM analysis failed."
            }
        return state

class DigestGenerationAgent:
    def _llm_digest_summary(self, state: Dict[str, Any]) -> str:
        """
        Use LLM to summarize and rank pitches for the digest.
        """
        # For demo, we use a placeholder for pitches; in real use, fetch from DB or state
        pitches = state.get("pitches", [])
        partner_name = state.get("partner_profile").name if state.get("partner_profile") else "Partner"
        prompt = f"""
        You are a VC chief of staff. Given the following list of startup pitches, create a weekly digest for {partner_name}:
        - Summarize key themes/trends
        - Highlight the most promising startups (ranked)
        - Use markdown formatting
        - Be concise, actionable, and professional
        
        Pitches (JSON):
        {pitches}
        
        Respond with the full digest as markdown text.
        """
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a professional VC analyst providing weekly digests."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=1200
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM digest summary failed: {e}")
            return "Weekly digest could not be generated."

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("[DigestGenerationAgent] LLM-based digest generation...")
        # In a real system, you would fetch recent pitches from DB or state
        # Here, we use state["pitches"] if available, else fallback to empty
        digest_content = self._llm_digest_summary(state)
        state["digest_content"] = digest_content
        state["digest_generated"] = digest_content != "Weekly digest could not be generated."
        return state

class ReplyGeneratorAgent:
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("[ReplyGeneratorAgent] Generating reply for partner...")
        try:
            partner = state.get("partner_profile")
            email_analysis = state.get("email_analysis")
            if not partner or not email_analysis:
                logger.warning("Missing partner or email analysis for reply generation.")
                state["reply"] = "[Error: Missing context for reply generation]"
                return state
            class EmailAnalysisObj:
                def __init__(self, data, state):
                    self.body = state.get("body", "")
                    self.intent = data.get("intent", "")
                    self.urgency_score = data.get("urgency_score", 5)
                    # Convert action_items to objects with .description
                    items = data.get("action_items", [])
                    self.action_items = []
                    for item in items:
                        if isinstance(item, str):
                            obj = type("ActionItem", (), {"description": item, "priority": 5, "deadline": None, "assigned_to": None, "status": "pending"})()
                            self.action_items.append(obj)
                        elif isinstance(item, dict):
                            obj = type("ActionItem", (), item)()
                            self.action_items.append(obj)
                        else:
                            self.action_items.append(item)
                    self.sentiment_score = data.get("sentiment_score", 0.0)
                    cr = data.get("capital_request")
                    if isinstance(cr, dict):
                        self.capital_request = cr
                    else:
                        self.capital_request = CAPITAL_REQUEST_TEMPLATE.copy()
                    self.deadline = data.get("deadline")
                    self.subject = state.get("subject", "")
                    self.sender = state.get("sender_email", "")
            analysis_obj = EmailAnalysisObj(email_analysis, state)
            reply = generate_partner_response(analysis_obj, partner)
            state["reply"] = reply
        except Exception as e:
            logger.error(f"ReplyGeneratorAgent failed: {e}")
            state["reply"] = f"[Error: {e}]"
        return state 