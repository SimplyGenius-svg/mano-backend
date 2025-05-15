import os
import json
import datetime
import openai
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, asdict
from enum import Enum
import re
import logging
from src.logic.urgency_scorer import score_urgency  # Keeping your existing urgency scorer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("capital_deployment_cos")

# --- Constants and Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.error("OpenAI API key not found in environment variables")
    raise EnvironmentError("OpenAI API key not found in environment variables")

openai.api_key = OPENAI_API_KEY

# --- Data Models ---
class EmailTone(str, Enum):
    FORMAL = "formal"
    CASUAL = "casual"
    URGENT = "urgent"
    FRIENDLY = "friendly"
    APOLOGETIC = "apologetic"
    NEUTRAL = "neutral"
    FRUSTRATED = "frustrated"
    EXCITED = "excited"

@dataclass
class ActionItem:
    description: str
    priority: int  # 1-10
    deadline: Optional[str] = None
    assigned_to: Optional[str] = None
    status: str = "pending"  # pending, in_progress, completed, blocked
    notes: Optional[str] = None

@dataclass
class CapitalRequest:
    amount: Optional[float] = None
    company: Optional[str] = None
    investment_stage: Optional[str] = None
    round_details: Optional[Dict[str, Any]] = None
    due_diligence_status: Optional[str] = None

@dataclass
class EmailAnalysis:
    thread_id: Optional[str]
    sender: str
    recipients: List[str]
    subject: str
    body: str
    source: str
    intent: str
    urgency_score: int  # 1-10
    action_items: List[ActionItem]
    deadline: Optional[str]
    tone: EmailTone
    risks: str
    capital_request: Optional[CapitalRequest] = None
    sentiment_score: Optional[float] = None
    completed: bool = False
    parsed_summary: str = ""
    processed_at: str = datetime.datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with proper handling of nested objects and enums"""
        result = asdict(self)
        # Convert action_items from dataclass instances to dicts
        result['action_items'] = [asdict(item) if hasattr(item, 'to_dict') else item 
                                 for item in self.action_items]
        # Convert capital_request from dataclass to dict if present
        if self.capital_request and hasattr(self.capital_request, 'to_dict'):
            result['capital_request'] = asdict(self.capital_request)
        # Convert Enum to string
        if isinstance(self.tone, EmailTone):
            result['tone'] = self.tone.value
        return result

# --- Enhanced GPT Interaction ---
def call_gpt_capital_analysis(email_body: str, subject: str, sender: str) -> Optional[Dict[str, Any]]:
    """
    Enhanced GPT analysis with focus on capital deployment context
    """
    prompt = f"""
    You are Mano, an intelligent chief of staff for a venture capital firm specializing in capital deployment decisions.
    
    Analyze the following partner email carefully and extract ALL relevant information about potential investments, capital allocation requests, or portfolio company updates.
    
    Email Subject: {subject}
    Email From: {sender}
    Email Body:
    ---
    {email_body}
    ---
    
    Respond in strict JSON format with the following schema:
    {{
        "intent": "Brief summary of what the partner wants (50 words max)",
        "urgency_score": Integer from 1-10 representing true urgency (not just stated urgency),
        "action_items": [
            {{
                "description": "Specific task to perform",
                "priority": Integer from 1-10,
                "deadline": "YYYY-MM-DD format if mentioned, otherwise null",
                "assigned_to": "Person who should handle this if specified, otherwise null"
            }}
        ],
        "deadline": "YYYY-MM-DD format if any overall deadline mentioned, otherwise null",
        "tone": "formal/casual/urgent/friendly/apologetic/neutral/frustrated/excited",
        "risks": "Specific business risks if this email is not addressed promptly",
        "capital_request": {{
            "amount": Numerical amount in millions if mentioned (do not include currency symbols), otherwise null,
            "company": "Company name if mentioned, otherwise null",
            "investment_stage": "seed/series A/series B/etc if mentioned, otherwise null",
            "round_details": {{
                "pre_money_valuation": "Valuation if mentioned, otherwise null",
                "post_money_valuation": "Post-money valuation if mentioned, otherwise null",
                "ownership_percentage": "Target ownership if mentioned, otherwise null"
            }},
            "due_diligence_status": "Status of due diligence if mentioned, otherwise null"
        }},
        "sentiment_score": Numerical sentiment on scale -1.0 (very negative) to 1.0 (very positive)
    }}
    
    Respond ONLY in raw JSON.
    """
    
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a precise, structured assistant specializing in venture capital and capital deployment."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=800
        )
        content = response.choices[0].message.content

        
        try:
            # Attempt to parse the JSON response
            return json.loads(content)
        except json.JSONDecodeError as json_err:
            logger.error(f"Failed to parse JSON from GPT response: {json_err}")
            logger.debug(f"Raw content that failed JSON parsing: {content}")
            
            # Attempt to extract JSON from the response (in case GPT added commentary)
            json_pattern = r'```json\s*([\s\S]*?)\s*```|{[\s\S]*}'
            match = re.search(json_pattern, content)
            if match:
                try:
                    json_str = match.group(1) if match.group(1) else match.group(0)
                    return json.loads(json_str)
                except (json.JSONDecodeError, IndexError) as e:
                    logger.error(f"Secondary JSON extraction failed: {e}")
            
            return None
            
    except Exception as e:
        logger.error(f"GPT analysis failed: {str(e)}")
        return None

# --- Vector DB Integration Placeholder ---
def store_in_vector_db(analysis: EmailAnalysis) -> bool:
    """
    Store the email analysis in a vector database for semantic search
    This is a placeholder - implement with your preferred vector DB
    """
    logger.info(f"Storing email analysis in vector DB for thread: {analysis.thread_id}")
    # TODO: Implement actual vector DB storage
    # Example with something like Pinecone, Weaviate, etc.
    return True

# --- Entity Recognition Functions ---
def extract_entities(text: str) -> Dict[str, List[str]]:
    """
    Extract named entities (companies, people, amounts) from text
    Using GPT for entity extraction
    """
    prompt = f"""
    Extract all named entities from the following text and categorize them.
    
    Text:
    ---
    {text}
    ---
    
    Respond in strict JSON format with these categories:
    {{
        "companies": ["Company1", "Company2"],
        "people": ["Person1", "Person2"],
        "financial_amounts": ["$10M", "$50K"],
        "dates": ["2023-04-15", "next quarter"],
        "locations": ["San Francisco", "New York"]
    }}
    
    Include only entities actually mentioned in the text. Respond ONLY in raw JSON.
    """
    
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a precise entity recognition assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=500
        )
        content = response.choices[0].message.content

        
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from entity extraction")
            return {
                "companies": [],
                "people": [],
                "financial_amounts": [],
                "dates": [],
                "locations": []
            }
            
    except Exception as e:
        logger.error(f"Entity extraction failed: {str(e)}")
        return {
            "companies": [],
            "people": [],
            "financial_amounts": [],
            "dates": [],
            "locations": []
        }

# --- Main Processing Function ---
def process_email_for_memory(email_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fully process an email and return enhanced structured memory
    """
    body = email_data.get("body", "")
    subject = email_data.get("subject", "No Subject")
    sender = email_data.get("sender", "")
    thread_id = email_data.get("thread_id", None)
    recipients = email_data.get("recipients", [])
    source = email_data.get("source", "partner")
    
    logger.info(f"Processing email from {sender}: '{subject}'")
    
    # Local urgency scoring as backup
    backup_urgency = score_urgency(body)
    
    # Try to extract structured understanding from GPT
    gpt_analysis = call_gpt_capital_analysis(body, subject, sender)
    
    if gpt_analysis is None:
        logger.warning("GPT analysis failed. Using backup processing.")
        
        # Create basic analysis as fallback
        analysis = EmailAnalysis(
            thread_id=thread_id,
            sender=sender,
            recipients=recipients,
            subject=subject,
            body=body,
            source=source,
            intent="General note",
            urgency_score=backup_urgency,
            action_items=[],
            deadline=None,
            tone=EmailTone.NEUTRAL,
            risks="",
            capital_request=None,
            sentiment_score=0.0,
            completed=False,
            parsed_summary=email_data.get("parsed_summary", "")
        )
    else:
        # Convert GPT response to proper action items
        action_items = []
        for item in gpt_analysis.get("action_items", []):
            action_items.append(ActionItem(
                description=item.get("description", ""),
                priority=item.get("priority", 5),
                deadline=item.get("deadline"),
                assigned_to=item.get("assigned_to"),
                status="pending"
            ))
        
        # Create capital request if present
        capital_req_data = gpt_analysis.get("capital_request", {})
        if capital_req_data and any(capital_req_data.values()):
            capital_request = CapitalRequest(
                amount=capital_req_data.get("amount"),
                company=capital_req_data.get("company"),
                investment_stage=capital_req_data.get("investment_stage"),
                round_details=capital_req_data.get("round_details"),
                due_diligence_status=capital_req_data.get("due_diligence_status")
            )
        else:
            capital_request = None
        
        # Determine tone enum
        tone_str = gpt_analysis.get("tone", "neutral").lower()
        try:
            tone = EmailTone(tone_str)
        except ValueError:
            tone = EmailTone.NEUTRAL
        
        # Build the final analysis object
        analysis = EmailAnalysis(
            thread_id=thread_id,
            sender=sender,
            recipients=recipients,
            subject=subject,
            body=body,
            source=source,
            intent=gpt_analysis.get("intent", "General note"),
            urgency_score=gpt_analysis.get("urgency_score", backup_urgency),
            action_items=action_items,
            deadline=gpt_analysis.get("deadline"),
            tone=tone,
            risks=gpt_analysis.get("risks", ""),
            capital_request=capital_request,
            sentiment_score=gpt_analysis.get("sentiment_score", 0.0),
            completed=False,
            parsed_summary=email_data.get("parsed_summary", "")
        )
    
    # Additional entity extraction for enrichment
    entities = extract_entities(body)
    
    # Combine into final memory object
    memory_data = analysis.to_dict()
    memory_data["entities"] = entities
    
    # Store in vector DB for later retrieval
    store_in_vector_db(analysis)
    
    logger.info(f"Email processed: {memory_data['intent']} [Urgency: {memory_data['urgency_score']}]")
    
    if memory_data.get("capital_request") and memory_data["capital_request"].get("amount"):
        logger.info(f"Capital request detected: {memory_data['capital_request']['amount']}M for {memory_data['capital_request'].get('company', 'unnamed company')}")
    
    return memory_data

# --- Thread Analysis ---
def analyze_email_thread(thread_messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze a full email thread to provide context and relationship between messages
    """
    if not thread_messages:
        return {}
    
    # Construct the thread history for analysis
    thread_history = []
    for msg in thread_messages:
        thread_history.append({
            "sender": msg.get("sender", ""),
            "timestamp": msg.get("timestamp", ""),
            "subject": msg.get("subject", ""),
            "snippet": msg.get("body", "")[:200] + "..." if len(msg.get("body", "")) > 200 else msg.get("body", "")
        })
    
    prompt = f"""
    Analyze this email thread history and identify:
    1. The overall topic/purpose of the thread
    2. Any patterns in communication
    3. How the discussion has evolved
    4. Outstanding issues that need resolution
    
    Thread History:
    {json.dumps(thread_history, indent=2)}
    
    Respond in strict JSON format:
    {{
        "thread_topic": "Main topic of the thread",
        "key_participants": ["Person1", "Person2"],
        "evolution": "How the conversation has developed",
        "unresolved_items": ["Item1", "Item2"],
        "recommended_actions": ["Action1", "Action2"]
    }}
    
    Respond ONLY in raw JSON.
    """
    
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a precise thread analysis assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=600
        )
        content = response.choices[0].message.content

        
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from thread analysis")
            return {
                "thread_topic": "Unknown",
                "key_participants": [],
                "evolution": "",
                "unresolved_items": [],
                "recommended_actions": []
            }
            
    except Exception as e:
        logger.error(f"Thread analysis failed: {str(e)}")
        return {
            "thread_topic": "Unknown",
            "key_participants": [],
            "evolution": "",
            "unresolved_items": [],
            "recommended_actions": []
        }

# --- Usage Example ---
if __name__ == "__main__":
    # Example usage
    sample_email = {
        "thread_id": "thread-123",
        "sender": "partner@vc.com",
        "recipients": ["me@company.com"],
        "subject": "Urgent: Funding decision needed for XYZ startup",
        "body": """
        We need to make a decision on the XYZ startup $2M seed round by Friday. 
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
    result = process_email_for_memory(sample_email)
    
    # Print the result
    print(json.dumps(result, indent=2))