import os
import json
import logging
import datetime
import re
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from firebase_admin import firestore
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from sentience_engine import process_email_for_memory, EmailAnalysis, CapitalRequest, ActionItem
from gpt_helpers import chat_with_gpt
from memory_logger import save_memory
from firebase import db
from query_engine import query_data

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("partner_manager")

# Load environment variables
load_dotenv()

# --- Constants and Configuration ---
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- Partner-specific Data Models ---
@dataclass
class Partner:
    """Data model for a partner in the VC firm"""
    email: str
    name: str
    role: str
    focus_areas: List[str] = None
    communication_style: str = "standard"  # standard, formal, casual, detailed, brief
    response_preferences: Dict[str, Any] = None
    active_deals: List[str] = None
    recent_interactions: List[str] = None
    priorities: List[str] = None
    
    def __post_init__(self):
        if self.focus_areas is None:
            self.focus_areas = []
        if self.response_preferences is None:
            self.response_preferences = {}
        if self.active_deals is None:
            self.active_deals = []
        if self.recent_interactions is None:
            self.recent_interactions = []
        if self.priorities is None:
            self.priorities = []

@dataclass
class CapitalDeploymentContext:
    """Tracks the current state of capital deployment activities"""
    active_deals: Dict[str, Dict[str, Any]]  # Company name -> deal details
    available_capital: float  # In millions
    upcoming_decisions: List[Dict[str, Any]]
    recent_investments: List[Dict[str, Any]]
    pipeline_stage_counts: Dict[str, int]  # e.g. {"initial_review": 5, "due_diligence": 3}
    partner_allocations: Dict[str, float]  # Partner email -> capital managed (in millions)
    
    def __post_init__(self):
        if self.active_deals is None:
            self.active_deals = {}
        if self.upcoming_decisions is None:
            self.upcoming_decisions = []
        if self.recent_investments is None:
            self.recent_investments = []
        if self.pipeline_stage_counts is None:
            self.pipeline_stage_counts = {}
        if self.partner_allocations is None:
            self.partner_allocations = {}

# --- Partner Profile Management ---
def load_partner_profile(email: str) -> Partner:
    """Load a partner profile from the database, or create one if it doesn't exist"""
    try:
        partner_doc = db.collection("partners").where("email", "==", email).limit(1).get()
        
        if not partner_doc:
            # Create a new partner if not found
            name_match = re.match(r"^([^@]+)@", email)
            name = name_match.group(1).replace(".", " ").title() if name_match else "Unknown"
            
            new_partner = Partner(
                email=email,
                name=name,
                role="Partner",
                focus_areas=[],
                communication_style="standard",
                response_preferences={},
                active_deals=[],
                recent_interactions=[],
                priorities=[]
            )
            
            db.collection("partners").add(new_partner.__dict__)
            logger.info(f"Created new partner profile for {email}")
            return new_partner
        
        # Safe access
        partner_data = partner_doc[0].to_dict()
        
        return Partner(
            email=partner_data.get("email"),
            name=partner_data.get("name"),
            role=partner_data.get("role"),
            focus_areas=partner_data.get("focus_areas", []),
            communication_style=partner_data.get("communication_style", "standard"),
            response_preferences=partner_data.get("response_preferences", {}),
            active_deals=partner_data.get("active_deals", []),
            recent_interactions=partner_data.get("recent_interactions", []),
            priorities=partner_data.get("priorities", [])
        )
        
    except Exception as e:
        logger.error(f"Error loading partner profile: {e}")
        # Fallback to minimal profile
        return Partner(
            email=email,
            name="Partner",
            role="Partner",
            focus_areas=[]
        )


def update_partner_profile(partner: Partner) -> bool:
    """Update a partner's profile in the database"""
    try:
        # Find the partner document
        partner_doc = db.collection("partners").where("email", "==", partner.email).limit(1).get()
        
        if not partner_doc:
            # Create a new document if it doesn't exist
            db.collection("partners").add(partner.__dict__)
        else:
            # Update the existing document
            doc_id = partner_doc[0].id
            db.collection("partners").document(doc_id).update(partner.__dict__)
        
        logger.info(f"Updated profile for partner: {partner.email}")
        return True
    except Exception as e:
        logger.error(f"Failed to update partner profile: {e}")
        return False

def learn_from_interaction(partner_email: str, email_analysis: EmailAnalysis) -> None:
    """Update partner profile based on new interactions"""
    partner = load_partner_profile(partner_email)
    
    # Update recent interactions
    timestamp = datetime.datetime.now().isoformat()
    interaction = {
        "timestamp": timestamp,
        "subject": email_analysis.subject,
        "intent": email_analysis.intent,
        "sentiment": email_analysis.sentiment_score
    }
    
    # Keep only the 10 most recent interactions
    partner.recent_interactions.append(interaction)
    if len(partner.recent_interactions) > 10:
        partner.recent_interactions = partner.recent_interactions[-10:]
    
    # Check for capital request details
    if email_analysis.capital_request and email_analysis.capital_request.company:
        company = email_analysis.capital_request.company
        if company not in partner.active_deals:
            partner.active_deals.append(company)
    
    # Update communication style based on tone patterns
    if hasattr(email_analysis, 'tone') and email_analysis.tone:
        # Simple heuristic - adapt over time based on observed patterns
        tone_map = {
            "formal": "formal",
            "casual": "casual", 
            "urgent": "brief",
            "friendly": "casual",
            "apologetic": "detailed",
            "frustrated": "brief"
        }
        if email_analysis.tone.lower() in tone_map:
            partner.communication_style = tone_map[email_analysis.tone.lower()]
    
    # Save the updated profile
    update_partner_profile(partner)

# --- Capital Deployment Context Management ---
def load_capital_context() -> CapitalDeploymentContext:
    """Load the current capital deployment context from the database"""
    try:
        context_doc = db.collection("capital_context").document("current").get()
        
        if not context_doc.exists:
            # Create default context if it doesn't exist
            default_context = CapitalDeploymentContext(
                active_deals={},
                available_capital=100.0,  # Default to $100M available
                upcoming_decisions=[],
                recent_investments=[],
                pipeline_stage_counts={"initial_review": 0, "due_diligence": 0, "term_sheet": 0, "closed": 0},
                partner_allocations={}
            )
            
            # Save to database
            db.collection("capital_context").document("current").set(default_context.__dict__)
            logger.info("Created new capital deployment context")
            return default_context
        
        # Context exists, load it
        context_data = context_doc.to_dict()
        return CapitalDeploymentContext(
            active_deals=context_data.get("active_deals", {}),
            available_capital=context_data.get("available_capital", 100.0),
            upcoming_decisions=context_data.get("upcoming_decisions", []),
            recent_investments=context_data.get("recent_investments", []),
            pipeline_stage_counts=context_data.get("pipeline_stage_counts", {}),
            partner_allocations=context_data.get("partner_allocations", {})
        )
    except Exception as e:
        logger.error(f"Error loading capital context: {e}")
        # Return a default context as fallback
        return CapitalDeploymentContext(
            active_deals={},
            available_capital=100.0,
            upcoming_decisions=[],
            recent_investments=[],
            pipeline_stage_counts={"initial_review": 0, "due_diligence": 0, "term_sheet": 0, "closed": 0},
            partner_allocations={}
        )

def update_capital_context(context: CapitalDeploymentContext) -> bool:
    """Update the capital deployment context in the database"""
    try:
        db.collection("capital_context").document("current").set(context.__dict__)
        logger.info("Updated capital deployment context")
        return True
    except Exception as e:
        logger.error(f"Failed to update capital context: {e}")
        return False

def process_capital_request(email_analysis: EmailAnalysis) -> Tuple[bool, str]:
    """Process a capital request and update the capital deployment context"""
    if not email_analysis.capital_request:
        return False, "No capital request found"
    
    capital_request = email_analysis.capital_request
    if not capital_request.company:
        return False, "No company specified in capital request"
    
    context = load_capital_context()
    
    # Check if this is a new deal or an update to an existing deal
    company = capital_request.company
    is_new_deal = company not in context.active_deals
    
    # Create or update deal information
    deal_info = context.active_deals.get(company, {})
    deal_info.update({
        "company": company,
        "last_updated": datetime.datetime.now().isoformat(),
        "requesting_partner": email_analysis.sender
    })
    
    # Update with new information from this request
    if capital_request.amount:
        deal_info["requested_amount"] = capital_request.amount
    
    if capital_request.investment_stage:
        deal_info["stage"] = capital_request.investment_stage
    
    if capital_request.round_details:
        for key, value in capital_request.round_details.items():
            if value:  # Only update if there's a value
                deal_info[key] = value
    
    if capital_request.due_diligence_status:
        deal_info["due_diligence_status"] = capital_request.due_diligence_status
    
    # Determine the pipeline stage based on the information provided
    if "due_diligence_status" in deal_info:
        if deal_info["due_diligence_status"].lower() in ["complete", "completed", "done"]:
            pipeline_stage = "term_sheet"
        else:
            pipeline_stage = "due_diligence"
    elif "requested_amount" in deal_info:
        pipeline_stage = "initial_review"
    else:
        pipeline_stage = "initial_review"
    
    # Update the pipeline stage
    deal_info["pipeline_stage"] = pipeline_stage
    
    # Add to active deals
    context.active_deals[company] = deal_info
    
    # Update pipeline stage counts
    context.pipeline_stage_counts[pipeline_stage] = context.pipeline_stage_counts.get(pipeline_stage, 0) + 1
    
    # Check if this is a pending decision that should be added to upcoming_decisions
    if pipeline_stage in ["term_sheet", "due_diligence"] and email_analysis.deadline:
        # Format decision info
        decision_info = {
            "company": company,
            "amount": deal_info.get("requested_amount"),
            "deadline": email_analysis.deadline,
            "requesting_partner": email_analysis.sender
        }
        
        # Add to upcoming decisions if not already there
        existing_decision = next((d for d in context.upcoming_decisions if d.get("company") == company), None)
        if existing_decision:
            # Update existing decision
            for key, value in decision_info.items():
                if value:  # Only update if there's a value
                    existing_decision[key] = value
        else:
            # Add new decision
            context.upcoming_decisions.append(decision_info)
    
    # Save the updated context
    update_capital_context(context)
    
    if is_new_deal:
        return True, f"Added new deal for {company}"
    else:
        return True, f"Updated existing deal for {company}"

# --- Enhanced Partner Email Handling ---
def generate_partner_response(email_analysis: EmailAnalysis, partner: Partner) -> str:
    """Generate a personalized response to a partner email based on analysis and partner profile"""
    # Load the capital context for reference
    capital_context = load_capital_context()
    
    # Build a complete context object for the response generation
    context = {
        "partner": {
            "name": partner.name,
            "role": partner.role,
            "focus_areas": partner.focus_areas,
            "communication_style": partner.communication_style,
            "recent_interactions": partner.recent_interactions[:3] if partner.recent_interactions else []
        },
        "email": {
            "subject": email_analysis.subject,
            "body": email_analysis.body,
            "intent": email_analysis.intent,
            "urgency": email_analysis.urgency_score,
            "action_items": [item.description for item in email_analysis.action_items],
            "sentiment": email_analysis.sentiment_score,
            "capital_request": email_analysis.capital_request.__dict__ if email_analysis.capital_request else None
        },
        "capital": {
            "available": capital_context.available_capital,
            "pipeline_counts": capital_context.pipeline_stage_counts,
            "upcoming_decisions": len(capital_context.upcoming_decisions),
            "active_deals_count": len(capital_context.active_deals)
        }
    }
    
    # Add company-specific context if relevant
    if email_analysis.capital_request and email_analysis.capital_request.company:
        company = email_analysis.capital_request.company
        if company in capital_context.active_deals:
            context["company"] = capital_context.active_deals[company]
    
    # Generate response based on communication style preference
    style_map = {
        "formal": "Respond formally and professionally with precise language and clear structure.",
        "casual": "Respond in a conversational but professional tone. Be personable but still focused on business.",
        "detailed": "Provide comprehensive analysis and detail in your response. Be thorough and meticulous.",
        "brief": "Be concise and to the point. Focus on key information only with minimal elaboration.",
        "standard": "Maintain a balanced, professional tone that's neither overly formal nor casual."
    }
    
    style_instruction = style_map.get(partner.communication_style, style_map["standard"])
    
    # Generate the action plan based on analysis
    action_plan = []
    for item in email_analysis.action_items:
        priority_str = "High priority" if item.priority >= 7 else "Medium priority" if item.priority >= 4 else "Low priority"
        deadline_str = f" (by {item.deadline})" if item.deadline else ""
        action_plan.append(f"- {item.description} - {priority_str}{deadline_str}")
    
    action_plan_str = "\n".join(action_plan) if action_plan else "No specific action items identified."
    
    # Create a comprehensive system prompt for response generation
    system_prompt = f"""
    You are Mano, the intelligent chief of staff for a venture capital firm specializing in capital deployment.
    
    Partner information:
    - Name: {partner.name}
    - Role: {partner.role}
    - Focus areas: {', '.join(partner.focus_areas) if partner.focus_areas else 'General investing'}
    - Communication preference: {partner.communication_style}
    
    Capital context:
    - Available capital: ${capital_context.available_capital}M
    - Active deals: {len(capital_context.active_deals)}
    - Upcoming decisions: {len(capital_context.upcoming_decisions)}
    
    {style_instruction}
    
    Your goal is to be a thoughtful, strategic chief of staff who:
    1. Demonstrates deep understanding of the underlying investment considerations
    2. Thinks ahead and anticipates the partner's needs
    3. Takes clear ownership of action items and next steps
    4. Provides concise but complete responses that respect the partner's time
    5. Shows good judgment about capital deployment decisions
    """
    
    # Create the user prompt that contains the specific query
    user_prompt = f"""
    The partner has sent an email:
    
    Subject: {email_analysis.subject}
    
    Content:
    {email_analysis.body}
    
    Based on my analysis:
    - Intent: {email_analysis.intent}
    - Urgency (1-10): {email_analysis.urgency_score}
    - Sentiment: {email_analysis.sentiment_score}
    
    Action plan:
    {action_plan_str}
    
    {f'Capital request details: {json.dumps(context["email"]["capital_request"], indent=2)}' if context["email"]["capital_request"] else ''}
    
    Please draft a helpful, professional response that directly addresses their needs and provides clear next steps.
    """
    
    try:
        response = chat_with_gpt(user_prompt, system_prompt=system_prompt)
        return response
    except Exception as e:
        logger.error(f"Failed to generate partner response: {e}")
        # Fallback response
        return f"""
        Dear {partner.name},
        
        Thank you for your email. I've noted your request and will work on this right away.
        
        I'll update you as soon as I have more information.
        
        Best regards,
        Mano
        """

def send_enhanced_email_reply(to_email: str, subject: str, reply_text: str, partner: Partner) -> bool:
    """Send an email reply with enhanced formatting based on partner preferences"""
    msg = MIMEMultipart()
    msg["Subject"] = f"Re: {subject}"
    msg["From"] = EMAIL_USER
    msg["To"] = to_email
    
    # Add signature based on partner's communication style
    signature = "\n\nBest regards,\nMano"
    if partner.communication_style == "formal":
        signature = "\n\nKind regards,\nMano\nChief of Staff"
    elif partner.communication_style == "casual":
        signature = "\n\nCheers,\nMano"
    
    # Format the email body
    formatted_reply = reply_text.strip() + signature
    
    # PRECOMPUTE HTML version (no \n in f-string)
    html_formatted_reply = formatted_reply.replace('\n\n', '</p><p>').replace('\n', '<br>')
    
    # Now safely use in f-string
    html_body = f"""
    <html>
      <body>
        <p>{html_formatted_reply}</p>
      </body>
    </html>
    """
    
    msg.attach(MIMEText(formatted_reply, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    
    try:
        import smtplib
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, [to_email], msg.as_string())
        logger.info(f"Reply sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False

    
# --- Main Partner Email Processing Function ---
def process_partner_email(email_obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main function to process an incoming partner email with complete context awareness
    """
    start_time = datetime.datetime.now()
    
    try:
        # Step 1: Run the core analysis using the sentience engine
        email_analysis = process_email_for_memory(email_obj)
        
        # Step 2: Load partner profile
        partner = load_partner_profile(email_obj["sender"])
        
        # Step 3: Process any capital deployment requests
        if isinstance(email_analysis, dict) and email_analysis.get("capital_request"):
            # Convert dict to object if needed
            capital_request = CapitalRequest(
                amount=email_analysis["capital_request"].get("amount"),
                company=email_analysis["capital_request"].get("company"),
                investment_stage=email_analysis["capital_request"].get("investment_stage"),
                round_details=email_analysis["capital_request"].get("round_details"),
                due_diligence_status=email_analysis["capital_request"].get("due_diligence_status")
            )
            
            # Create proper EmailAnalysis object
            email_analysis_obj = EmailAnalysis(
                thread_id=email_analysis.get("thread_id"),
                sender=email_analysis.get("sender"),
                recipients=email_analysis.get("recipients", []),
                subject=email_analysis.get("subject", ""),
                body=email_analysis.get("body", ""),
                source=email_analysis.get("source", ""),
                intent=email_analysis.get("intent", ""),
                urgency_score=email_analysis.get("urgency_score", 5),
                action_items = [
    ActionItem(
        description=item.get("description", ""),
        priority=item.get("priority", 5),
        deadline=item.get("deadline"),
        assigned_to=item.get("assigned_to"),
        status=item.get("status", "pending")
    ) if isinstance(item, dict) 
    else ActionItem(description=item, priority=5) if isinstance(item, str)
    else item
    for item in email_analysis.get("action_items", [])
],

                deadline=email_analysis.get("deadline"),
                tone=email_analysis.get("tone", "neutral"),
                risks=email_analysis.get("risks", ""),
                capital_request=capital_request,
                sentiment_score=email_analysis.get("sentiment_score", 0.0),
                completed=False,
                parsed_summary=email_analysis.get("parsed_summary", "")
            )
        elif not isinstance(email_analysis, EmailAnalysis):
            # Handle case where original analysis returns a dict instead of EmailAnalysis
            logger.warning("Email analysis returned a dict, converting to EmailAnalysis object")
            
            # Check if there's capital request data
            capital_request = None
            if email_analysis.get("capital_request"):
                capital_request = CapitalRequest(
                    amount=email_analysis["capital_request"].get("amount"),
                    company=email_analysis["capital_request"].get("company"),
                    investment_stage=email_analysis["capital_request"].get("investment_stage"),
                    round_details=email_analysis["capital_request"].get("round_details"),
                    due_diligence_status=email_analysis["capital_request"].get("due_diligence_status")
                )
            
            # Convert action items
            action_items = []
            for item in email_analysis.get("action_items", []):
                if isinstance(item, str):
                    action_items.append(ActionItem(description=item, priority=5))
                elif isinstance(item, dict):
                    action_items.append(ActionItem(
                        description=item.get("description", ""),
                        priority=item.get("priority", 5),
                        deadline=item.get("deadline"),
                        assigned_to=item.get("assigned_to"),
                        status=item.get("status", "pending")
                    ))
                else:
                    action_items.append(item)  # Already an ActionItem object
            
            # Create proper EmailAnalysis object
            email_analysis_obj = EmailAnalysis(
                thread_id=email_analysis.get("thread_id"),
                sender=email_analysis.get("sender"),
                recipients=email_analysis.get("recipients", []),
                subject=email_analysis.get("subject", ""),
                body=email_analysis.get("body", ""),
                source=email_analysis.get("source", ""),
                intent=email_analysis.get("intent", ""),
                urgency_score=email_analysis.get("urgency_score", 5),
                action_items=action_items,
                deadline=email_analysis.get("deadline"),
                tone=email_analysis.get("tone", "neutral"),
                risks=email_analysis.get("risks", ""),
                capital_request=capital_request,
                sentiment_score=email_analysis.get("sentiment_score", 0.0),
                completed=False,
                parsed_summary=email_analysis.get("parsed_summary", "")
            )
        else:
            email_analysis_obj = email_analysis
        
        # Process capital request if present
        if email_analysis_obj.capital_request:
            success, message = process_capital_request(email_analysis_obj)
            logger.info(f"Capital request processing: {message}")
        
        # Step 4: Update partner profile with insights from this interaction
        learn_from_interaction(email_obj["sender"], email_analysis_obj)
        
        # Step 5: Check if handling reminders or a standard response
        if "remind" in email_obj["body"].lower():
            from reminder import create_reminder
            reminder_id = create_reminder(email_obj)
            if reminder_id:
                logger.info(f"Created reminder: {reminder_id}")
                
                # Simple confirmation for reminders
                confirmation = f"I've set a reminder for: {email_analysis_obj.intent}"
                send_enhanced_email_reply(email_obj["sender"], email_obj["subject"], confirmation, partner)
        
        # Step 6: Generate an appropriate response based on analysis and partner profile
        elif email_analysis_obj.urgency_score >= 3 or any('ask' in action.description.lower() for action in email_analysis_obj.action_items):
            response = generate_partner_response(email_analysis_obj, partner)
            send_enhanced_email_reply(email_obj["sender"], email_obj["subject"], response, partner)
        
        # Step 7: Save the complete interaction to memory
        save_memory(
            sender_email=email_obj["sender"],
            subject=email_obj["subject"],
            body=email_obj["body"],
            tags=[],  # Add appropriate tags here if needed
            memory_type="investment" if email_analysis_obj.capital_request else "note"
        )
        
        # Calculate processing time
        processing_time = (datetime.datetime.now() - start_time).total_seconds()
        
        # Record metrics
        db.collection("processing_metrics").add({
            "email_id": email_analysis_obj.thread_id,
            "processing_time": processing_time,
            "urgency_score": email_analysis_obj.urgency_score,
            "has_capital_request": bool(email_analysis_obj.capital_request),
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        
        logger.info(f"Completed processing email from {email_obj['sender']} in {processing_time:.2f} seconds")
        
        return {
            "status": "success",
            "message": "Email processed successfully",
            "analysis": email_analysis_obj.__dict__ if hasattr(email_analysis_obj, "__dict__") else email_analysis,
            "processing_time": processing_time
        }
        
    except Exception as e:
        logger.error(f"Error processing partner email: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Error processing email: {str(e)}"
        }

# --- Proactive VC Chief of Staff Functions ---
def generate_daily_capital_digest() -> Dict[str, Any]:
    """
    Generate a daily digest of capital deployment activities
    This could be sent to partners or used for internal tracking
    """
    try:
        # Load capital context
        context = load_capital_context()
        
        # Get current date
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # Count deals by stage
        stage_counts = context.pipeline_stage_counts
        
        # Find upcoming decisions in the next 7 days
        now = datetime.datetime.now()
        upcoming = []
        for decision in context.upcoming_decisions:
            if not decision.get("deadline"):
                continue
                
            try:
                deadline = datetime.datetime.fromisoformat(decision["deadline"])
                days_remaining = (deadline - now).days
                if 0 <= days_remaining <= 7:
                    upcoming.append({
                        "company": decision["company"],
                        "amount": decision.get("amount"),
                        "deadline": decision["deadline"],
                        "days_remaining": days_remaining
                    })
            except (ValueError, TypeError):
                # Skip if deadline can't be parsed
                continue
        
        # Sort by days remaining
        upcoming.sort(key=lambda x: x["days_remaining"])
        
        # Calculate capital metrics
        total_capital_requested = sum(deal.get("requested_amount", 0) 
                                    for deal in context.active_deals.values() 
                                    if deal.get("requested_amount"))
        
        # Create digest content
        digest = {
            "date": today,
            "available_capital": context.available_capital,
            "total_requested": total_capital_requested,
            "pipeline": {
                "initial_review": stage_counts.get("initial_review", 0),
                "due_diligence": stage_counts.get("due_diligence", 0),
                "term_sheet": stage_counts.get("term_sheet", 0),
                "closed": stage_counts.get("closed", 0)
            },
            "upcoming_decisions": upcoming,
            "recent_investments": context.recent_investments[:5] if context.recent_investments else []
        }
        
        # Save digest to database
        db.collection("capital_digests").document(today).set(digest)
        
        return digest
    except Exception as e:
        logger.error(f"Failed to generate capital digest: {e}")
        return {
            "date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "error": str(e)
        }

def identify_capital_allocation_opportunities() -> List[Dict[str, Any]]:
    """
    Proactively identify opportunities for capital allocation
    based on the current portfolio and deployment context
    """
    try:
        context = load_capital_context()
        
        opportunities = []
        
        # Identify deals in due diligence that haven't been updated in over 7 days
        now = datetime.datetime.now()
        for company, deal in context.active_deals.items():
            if deal.get("pipeline_stage") == "due_diligence":
                last_updated = deal.get("last_updated")
                if last_updated:
                    try:
                        updated_date = datetime.datetime.fromisoformat(last_updated)
                        days_since_update = (now - updated_date).days
                        if days_since_update > 7:
                            opportunities.append({
                                "company": company,
                                "deal_stage": "due_diligence",
                                "days_since_update": days_since_update,
                                "requested_amount": deal.get("requested_amount"),
                                "requesting_partner": deal.get("requesting_partner"),
                                "opportunity_type": "stalled_due_diligence"
                            })
                    except (ValueError, TypeError):
                        # Skip if the date can't be parsed
                        continue
        
        # Identify term sheets that are close to decision with no upcoming decision scheduled
        term_sheet_companies = {deal["company"] for deal in context.active_deals.values() 
                               if deal.get("pipeline_stage") == "term_sheet"}
        
        upcoming_decision_companies = {decision["company"] for decision in context.upcoming_decisions}
        
        # Find term sheets without scheduled decisions
        for company in term_sheet_companies:
            if company not in upcoming_decision_companies:
                deal = context.active_deals[company]
                opportunities.append({
                    "company": company,
                    "deal_stage": "term_sheet",
                    "requested_amount": deal.get("requested_amount"),
                    "requesting_partner": deal.get("requesting_partner"),
                    "opportunity_type": "term_sheet_without_decision"
                })
        
        # Identify if we're approaching our capital deployment targets
        if context.available_capital < 20:  # Less than $20M available
            opportunities.append({
                "opportunity_type": "low_available_capital",
                "available_capital": context.available_capital,
                "action_needed": "Alert partners about limited remaining capital"
            })
        
        return opportunities
    except Exception as e:
        logger.error(f"Failed to identify capital opportunities: {e}")
        return []

def create_investment_memo(company_name: str) -> Dict[str, Any]:
    """
    Generate a structured investment memo for a company
    based on all available information in the system
    """
    try:
        # Get company information from active deals
        context = load_capital_context()
        if company_name not in context.active_deals:
            return {"error": f"Company {company_name} not found in active deals"}
        
        deal = context.active_deals[company_name]
        
        # Get all emails related to this company
        company_emails = db.collection("partner_memory")\
            .where("body", "array_contains", company_name)\
            .order_by("timestamp", direction=firestore.Query.DESCENDING)\
            .limit(10)\
            .stream()
        
        # Extract relevant email content
        email_content = []
        for email in company_emails:
            email_data = email.to_dict()
            email_content.append({
                "subject": email_data.get("subject", ""),
                "sender": email_data.get("sender", ""),
                "body": email_data.get("body", "")[:200] + "..." if len(email_data.get("body", "")) > 200 else email_data.get("body", ""),
                "timestamp": email_data.get("timestamp")
            })
        
        # Generate investment memo using GPT
        prompt = f"""
        Create a structured investment memo for {company_name} based on the following information.
        
        Deal information:
        {json.dumps(deal, indent=2)}
        
        Related communications:
        {json.dumps(email_content, indent=2)}
        
        Format the memo with these sections:
        1. Executive Summary
        2. Company Overview
        3. Market Analysis
        4. Investment Thesis
        5. Risks and Mitigations
        6. Deal Terms
        7. Recommendation
        
        For any section where information is unavailable, indicate what additional information is needed.
        """
        
        try:
            memo_content = chat_with_gpt(prompt)
            
            # Create the memo document
            memo = {
                "company": company_name,
                "generated_at": datetime.datetime.now().isoformat(),
                "content": memo_content,
                "deal_stage": deal.get("pipeline_stage", "unknown"),
                "requested_amount": deal.get("requested_amount"),
                "pre_money_valuation": deal.get("pre_money_valuation", "Unknown"),
                "requesting_partner": deal.get("requesting_partner")
            }
            
            # Save to database
            memo_id = f"memo_{company_name.lower().replace(' ', '_')}_{datetime.datetime.now().strftime('%Y%m%d')}"
            db.collection("investment_memos").document(memo_id).set(memo)
            
            return {
                "status": "success",
                "memo_id": memo_id,
                "memo": memo
            }
        except Exception as e:
            logger.error(f"Failed to generate memo: {e}")
            return {"error": f"Failed to generate memo: {str(e)}"}
            
    except Exception as e:
        logger.error(f"Failed to create investment memo: {e}")
        return {"error": str(e)}

# --- Predictive Portfolio Management ---
def predict_capital_needs(timeframe_days: int = 90) -> Dict[str, Any]:
    """
    Predict capital deployment needs over the specified timeframe
    based on current pipeline and historical patterns
    """
    try:
        context = load_capital_context()
        
        # Calculate committed capital from upcoming decisions
        committed_capital = 0
        for decision in context.upcoming_decisions:
            if decision.get("amount"):
                committed_capital += decision["amount"]
        
        # Calculate potential capital from deals in due diligence (with 50% probability)
        due_diligence_capital = 0
        for deal in context.active_deals.values():
            if deal.get("pipeline_stage") == "due_diligence" and deal.get("requested_amount"):
                due_diligence_capital += deal["requested_amount"] * 0.5  # 50% probability
        
        # Calculate potential capital from initial review (with 20% probability)
        initial_review_capital = 0
        for deal in context.active_deals.values():
            if deal.get("pipeline_stage") == "initial_review" and deal.get("requested_amount"):
                initial_review_capital += deal["requested_amount"] * 0.2  # 20% probability
        
        # Total expected deployment
        expected_deployment = committed_capital + due_diligence_capital + initial_review_capital
        
        # Check if we'll exceed available capital
        capital_gap = context.available_capital - expected_deployment
        
        return {
            "timeframe_days": timeframe_days,
            "available_capital": context.available_capital,
            "committed_capital": committed_capital,
            "expected_from_due_diligence": due_diligence_capital,
            "expected_from_initial_review": initial_review_capital,
            "total_expected_deployment": expected_deployment,
            "capital_gap": capital_gap,
            "status": "deficit" if capital_gap < 0 else "surplus",
            "timestamp": datetime.datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to predict capital needs: {e}")
        return {"error": str(e)}

# --- Additional Partner Support Functions ---
def suggest_portfolio_allocations() -> Dict[str, Any]:
    """
    Suggest optimal portfolio allocations based on current investments
    and sector performance
    """
    try:
        # This would typically integrate with external market data sources
        # For now, we'll use a simplified calculation
        
        context = load_capital_context()
        
        # Group active deals by sector/stage
        sectors = {}
        stages = {}
        
        for deal in context.active_deals.values():
            # Extract sector from deal info (if available)
            sector = deal.get("sector", "unknown")
            sectors[sector] = sectors.get(sector, 0) + (deal.get("requested_amount", 0) or 0)
            
            # Extract stage
            stage = deal.get("investment_stage", "unknown")
            stages[stage] = stages.get(stage, 0) + (deal.get("requested_amount", 0) or 0)
        
        # Calculate current allocation percentages
        total_allocated = sum(sectors.values())
        
        sector_allocation = {sector: (amount / total_allocated * 100) if total_allocated else 0 
                            for sector, amount in sectors.items()}
        
        stage_allocation = {stage: (amount / total_allocated * 100) if total_allocated else 0 
                           for stage, amount in stages.items()}
        
        # Get target allocations (in a real system, these would come from firm strategy)
        target_sector_allocation = {
            "AI": 25,
            "SaaS": 25,
            "Fintech": 20,
            "Healthcare": 15,
            "Consumer": 10,
            "unknown": 5
        }
        
        target_stage_allocation = {
            "seed": 20,
            "series A": 40,
            "series B": 25,
            "later stage": 15,
            "unknown": 0
        }
        
        # Calculate gaps for rebalancing
        sector_gaps = {sector: target_sector_allocation.get(sector, 0) - sector_allocation.get(sector, 0)
                      for sector in set(list(target_sector_allocation.keys()) + list(sector_allocation.keys()))}
        
        stage_gaps = {stage: target_stage_allocation.get(stage, 0) - stage_allocation.get(stage, 0)
                     for stage in set(list(target_stage_allocation.keys()) + list(stage_allocation.keys()))}
        
        # Generate recommendations
        recommendations = []
        
        # Add sector-based recommendations
        for sector, gap in sector_gaps.items():
            if gap > 5:  # More than 5% underallocated
                recommendations.append({
                    "type": "sector_allocation",
                    "category": sector,
                    "current_allocation": sector_allocation.get(sector, 0),
                    "target_allocation": target_sector_allocation.get(sector, 0),
                    "gap": gap,
                    "recommendation": f"Increase allocation to {sector} sector by approximately ${(gap/100) * context.available_capital}M"
                })
            elif gap < -5:  # More than 5% overallocated
                recommendations.append({
                    "type": "sector_allocation",
                    "category": sector,
                    "current_allocation": sector_allocation.get(sector, 0),
                    "target_allocation": target_sector_allocation.get(sector, 0),
                    "gap": gap,
                    "recommendation": f"Reduce new investments in {sector} sector until portfolio rebalances"
                })
        
        # Add stage-based recommendations
        for stage, gap in stage_gaps.items():
            if gap > 5:  # More than 5% underallocated
                recommendations.append({
                    "type": "stage_allocation",
                    "category": stage,
                    "current_allocation": stage_allocation.get(stage, 0),
                    "target_allocation": target_stage_allocation.get(stage, 0),
                    "gap": gap,
                    "recommendation": f"Increase allocation to {stage} companies by approximately ${(gap/100) * context.available_capital}M"
                })
        
        return {
            "current_allocations": {
                "by_sector": sector_allocation,
                "by_stage": stage_allocation
            },
            "target_allocations": {
                "by_sector": target_sector_allocation,
                "by_stage": target_stage_allocation
            },
            "recommendations": recommendations,
            "available_capital": context.available_capital
        }
    except Exception as e:
        logger.error(f"Failed to suggest portfolio allocations: {e}")
        return {"error": str(e)}

def sync_portfolio_data() -> bool:
    """
    Synchronize portfolio data from external sources
    This function would typically integrate with portfolio management systems,
    financial databases, etc.
    """
    # This is a placeholder for external system integration
    logger.info("Syncing portfolio data from external sources...")
    
    try:
        # In a real implementation, this would:
        # 1. Fetch data from portfolio management system
        # 2. Update company performance metrics
        # 3. Sync with deal tracking software
        # 4. Import market comparison data
        
        # For demonstration, we'll just update a timestamp
        db.collection("system_status").document("portfolio_sync").set({
            "last_synced": datetime.datetime.now().isoformat(),
            "status": "success"
        })
        
        return True
    except Exception as e:
        logger.error(f"Portfolio data sync failed: {e}")
        
        # Update status with error
        db.collection("system_status").document("portfolio_sync").set({
            "last_synced": datetime.datetime.now().isoformat(),
            "status": "error",
            "error_message": str(e)
        })
        
        return False

# --- API Integration Functions ---
def get_market_data_for_company(company_name: str) -> Dict[str, Any]:
    """
    Fetch relevant market data for a company from external APIs
    This is a placeholder for integration with market data providers
    """
    logger.info(f"Fetching market data for {company_name}")
    
    # In a real implementation, this would query:
    # - Crunchbase or PitchBook for funding data
    # - Market research APIs for sector trends
    # - Financial data providers for comparable companies
    
    # For now, return placeholder data
    return {
        "company": company_name,
        "funding_rounds": [
            {"type": "Seed", "amount": "$2M", "date": "2023-01-15", "investors": ["Angel Group A", "Seed VC"]},
            {"type": "Series A", "amount": "$8M", "date": "2023-09-01", "investors": ["Major VC", "Growth Fund"]}
        ],
        "market_size": "$4.5B by 2025",
        "growth_rate": "22% CAGR",
        "competitors": ["CompetitorA", "CompetitorB", "CompetitorC"],
        "comparable_valuations": {
            "CompetitorA": "$45M (Series A)",
            "CompetitorB": "$80M (Series B)",
            "CompetitorC": "$30M (Seed)"
        },
        "sentiment": "positive",
        "news_mentions": 34,
        "data_source": "placeholder",
        "retrieved_at": datetime.datetime.now().isoformat()
    }

# --- Event Handlers ---
def handle_investment_committee_scheduling(email_obj: Dict[str, Any]) -> bool:
    """
    Process requests to schedule investment committee meetings
    """
    try:
        # Extract company name from email
        body = email_obj.get("body", "")
        subject = email_obj.get("subject", "")
        
        # Simple pattern matching for company name
        company_match = re.search(r"for\s+([A-Za-z0-9\s]+)\s+investment", body + " " + subject)
        company_name = company_match.group(1).strip() if company_match else "Unknown Company"
        
        # Check if we have this company in active deals
        context = load_capital_context()
        deal_info = context.active_deals.get(company_name, {})
        
        # Generate IC meeting information
        ic_info = {
            "company": company_name,
            "requested_by": email_obj.get("sender"),
            "requested_at": datetime.datetime.now().isoformat(),
            "deal_stage": deal_info.get("pipeline_stage", "unknown"),
            "requested_amount": deal_info.get("requested_amount"),
            "status": "pending",
            "materials_ready": False
        }
        
        # Save to database
        ic_id = f"ic_{company_name.lower().replace(' ', '_')}_{datetime.datetime.now().strftime('%Y%m%d')}"
        db.collection("ic_meetings").document(ic_id).set(ic_info)
        
        # Generate response for scheduling
        partner = load_partner_profile(email_obj.get("sender"))
        
        response = f"""
        I've initiated the scheduling process for the investment committee meeting to review {company_name}.
        
        I'll send out calendar invites once I confirm availability with all required participants.
        
        Would you like me to prepare the standard IC deck based on our current information about {company_name}, or will you be preparing materials for this meeting?
        """
        
        # Send response
        send_enhanced_email_reply(email_obj.get("sender"), email_obj.get("subject"), response, partner)
        
        return True
    except Exception as e:
        logger.error(f"Failed to handle IC scheduling: {e}")
        return False
    



def handle_due_diligence_request(email_obj: Dict[str, Any]) -> bool:
    """
    Process requests to initiate or manage due diligence
    """
    try:
        # Extract company name from email
        body = email_obj.get("body", "")
        
        # Simple pattern matching for company name
        company_match = re.search(r"due\s+diligence\s+for\s+([A-Za-z0-9\s]+)", body)
        company_name = company_match.group(1).strip() if company_match else None
        
        if not company_name:
            # Try alternative patterns
            company_match = re.search(r"([A-Za-z0-9\s]+)\s+due\s+diligence", body)
            company_name = company_match.group(1).strip() if company_match else "Unknown Company"
        
        # Create due diligence record
        dd_info = {
            "company": company_name,
            "requested_by": email_obj.get("sender"),
            "started_at": datetime.datetime.now().isoformat(),
            "status": "initiated",
            "completed_sections": [],
            "pending_sections": [
                "financial", 
                "legal", 
                "technical", 
                "market", 
                "team", 
                "customer_references"
            ]
        }
        
        # Save to database
        dd_id = f"dd_{company_name.lower().replace(' ', '_')}_{datetime.datetime.now().strftime('%Y%m%d')}"
        db.collection("due_diligence").document(dd_id).set(dd_info)
        
        # Update company deal status
        context = load_capital_context()
        if company_name in context.active_deals:
            context.active_deals[company_name]["pipeline_stage"] = "due_diligence"
            context.active_deals[company_name]["due_diligence_status"] = "in_progress"
            update_capital_context(context)
        
        # Generate response
        partner = load_partner_profile(email_obj.get("sender"))
        
        response = f"""
        I've initiated the due diligence process for {company_name}. Here's what I've set up:
        
        1. Created a due diligence checklist with all standard sections
        2. Updated our pipeline tracking to show {company_name} in due diligence stage
        3. Prepared a shared folder for the team to upload findings
        
        Please let me know if you need any specific areas of focus or if you'd like me to coordinate with external advisors for specialized review.
        """
        
        # Send response
        send_enhanced_email_reply(email_obj.get("sender"), email_obj.get("subject"), response, partner)
        
        return True
    except Exception as e:
        logger.error(f"Failed to handle due diligence request: {e}")
        return False

# --- Main Entry Point ---
if __name__ == "__main__":
    # Example usage with a sample email
    sample_email = {
        "thread_id": "thread-123",
        "sender": "partner@vc.com",
        "recipients": ["me@company.com"],
        "subject": "Decision needed for XYZ AI startup",
        "body": """
        We need to make a decision on the XYZ AI startup $2M seed round by Friday. 
        They've shown impressive traction with 200% MoM growth and their AI platform
        has strong differentiation from competitors.
        
        I think we should commit to leading this round at a $10M pre-money valuation 
        for 20% ownership. Can you please prepare the investment memo and run the 
        financial models by Thursday EOD?
        
        Also, please schedule a partner meeting for Thursday morning to discuss.
        
        Thanks,
        John
        """,
        "source": "partner"
    }
    
    # Process the email
    result = process_partner_email(sample_email)
    
    # Print the result
    print(json.dumps(result, indent=2))
    
    # Generate a daily digest for demonstration
    digest = generate_daily_capital_digest()
    print("Daily Capital Digest:")
    print(json.dumps(digest, indent=2))