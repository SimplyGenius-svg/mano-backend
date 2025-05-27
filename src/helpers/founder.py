import os
import fitz  # PyMuPDF
import smtplib
import re
import json
import datetime
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict, field
from src.util.firebase import db
from firebase_admin import firestore
from dotenv import load_dotenv

from src.gpt_helpers import generate_pitch_summary, generate_friendly_feedback, chat_with_gpt
from src.memory_logger import save_memory
from src.helpers.sentience_engine import process_email_for_memory
from src.util.vector_client import store_vector, search_vectors  # Assuming you'll implement this

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("founder_manager")

load_dotenv()

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

# Enhanced VC thesis with specific investment criteria
VC_THESIS = """
We invest in early-stage startups leveraging AI to create defensible workflows within vertical SaaS, infrastructure, or marketplaces. 

Investment Criteria:
1. Market: Target market size of at least $1B+ with clear growth trajectory
2. Team: Founders with domain expertise, technical capability, and execution history
3. Technology: Proprietary technology or approach with clear differentiation
4. Traction: Evidence of product-market fit or compelling early adoption metrics
5. Business Model: Clear path to sustainable unit economics and scalability
6. Competitive Moat: Sustainable advantages that prevent easy replication

Stage Focus:
- Pre-seed to Series A investments
- Initial checks between $500K and $3M
- Ability to follow-on in future rounds

Industry Preferences:
- AI/ML infrastructure and tooling
- Vertical SaaS with industry-specific workflows
- Enterprise automation and productivity
- Data intelligence platforms
- Fintech infrastructure
- Healthcare technology

Founders must show deep understanding of their space, product velocity, and clarity in go-to-market execution.
"""

# --- Data Models ---
@dataclass
class Founder:
    """Data model for a startup founder"""
    email: str
    name: str = ""
    company: str = ""
    role: str = ""
    last_interaction: str = ""
    pitch_count: int = 0
    response_rate: float = 0.0
    tags: List[str] = field(default_factory=list)
    funding_stage: str = ""
    sector: str = ""
    location: str = ""
    linkedin: str = ""
    website: str = ""
    intro_source: str = ""
    follow_ups: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)

@dataclass
class PitchAnalysis:
    """Detailed analysis of a startup pitch"""
    company: str
    founder_email: str
    summary: str
    market_size: Optional[float] = None  # In billions USD
    team_score: int = 0  # 1-10
    tech_score: int = 0  # 1-10
    traction_score: int = 0  # 1-10
    business_model_score: int = 0  # 1-10
    moat_score: int = 0  # 1-10
    overall_score: float = 0.0  # 0-10
    thesis_alignment: float = 0.0  # 0-10
    funding_stage: str = ""
    sector: str = ""
    funds_requested: Optional[float] = None  # In millions USD
    valuation: Optional[float] = None  # In millions USD
    key_metrics: Dict[str, Any] = field(default_factory=dict)
    risks: List[str] = field(default_factory=list)
    opportunities: List[str] = field(default_factory=list)
    recommendation: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)

# --- PDF Processing Functions ---
def extract_text_from_pdf(pdf_bytes) -> str:
    """Extract text content from PDF bytes"""
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            text = "\n".join([page.get_text() for page in doc])
            logger.info(f"Successfully extracted {len(text)} characters from PDF")
            return text
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return ""

def extract_pdf_metadata(pdf_bytes) -> Dict[str, Any]:
    """Extract metadata and structure from PDF"""
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            metadata = {
                "title": doc.metadata.get("title", ""),
                "author": doc.metadata.get("author", ""),
                "subject": doc.metadata.get("subject", ""),
                "keywords": doc.metadata.get("keywords", ""),
                "page_count": len(doc),
                "file_size": len(pdf_bytes),
                "has_images": any(len(page.get_images()) > 0 for page in doc),
                "has_tables": any("table" in page.get_text().lower() for page in doc),
                "sections": []
            }
            
            # Extract section headings based on text formatting
            for page_num, page in enumerate(doc):
                blocks = page.get_text("dict")["blocks"]
                for block in blocks:
                    if "lines" in block:
                        for line in block["lines"]:
                            for span in line.get("spans", []):
                                # Heuristic for headings: bold or large text
                                if span.get("size", 0) > 14 or "bold" in span.get("font", "").lower():
                                    text = span.get("text", "").strip()
                                    if text and len(text) < 100:  # Reasonable heading length
                                        metadata["sections"].append({
                                            "text": text,
                                            "page": page_num + 1
                                        })
            
            logger.info(f"Extracted metadata from PDF: {len(metadata['sections'])} sections identified")
            return metadata
    except Exception as e:
        logger.error(f"PDF metadata extraction failed: {e}")
        return {
            "page_count": 0,
            "sections": []
        }

def extract_financial_data(text: str) -> Dict[str, Any]:
    """Extract financial metrics and projections from text"""
    financial_data = {}
    
    # Look for revenue figures
    revenue_patterns = [
        r"(?:revenue|arr|sales).*?(?:\$|\€)?\s*(\d[\d\.,]+)(?:\s*(?:k|m|b|million|billion|M|B))?\b",
        r"(?:\$|\€)?\s*(\d[\d\.,]+)(?:\s*(?:k|m|b|million|billion|M|B))?\b.*?(?:revenue|arr|sales)",
    ]
    
    for pattern in revenue_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            # Process the value
            value_str = match.group(1).replace(",", "")
            try:
                value = float(value_str)
                
                # Determine multiplier if present
                multiplier = 1
                if "k" in match.group(0).lower():
                    multiplier = 1000
                elif any(x in match.group(0).lower() for x in ["m", "million"]):
                    multiplier = 1000000
                elif any(x in match.group(0).lower() for x in ["b", "billion"]):
                    multiplier = 1000000000
                
                # Store the revenue figure
                financial_data["revenue"] = value * multiplier
                break
            except ValueError:
                pass
    
    # Look for valuation
    valuation_patterns = [
        r"(?:valuation|valued at).*?(?:\$|\€)?\s*(\d[\d\.,]+)(?:\s*(?:k|m|b|million|billion|M|B))?\b",
        r"(?:\$|\€)?\s*(\d[\d\.,]+)(?:\s*(?:k|m|b|million|billion|M|B))?\b.*?valuation",
    ]
    
    for pattern in valuation_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            value_str = match.group(1).replace(",", "")
            try:
                value = float(value_str)
                
                # Determine multiplier if present
                multiplier = 1
                if "k" in match.group(0).lower():
                    multiplier = 1000
                elif any(x in match.group(0).lower() for x in ["m", "million"]):
                    multiplier = 1000000
                elif any(x in match.group(0).lower() for x in ["b", "billion"]):
                    multiplier = 1000000000
                
                # Store the valuation
                financial_data["valuation"] = value * multiplier
                break
            except ValueError:
                pass
    
    # Look for funding requested
    funding_patterns = [
        r"(?:raising|raise|seeking|looking for).*?(?:\$|\€)?\s*(\d[\d\.,]+)(?:\s*(?:k|m|b|million|billion|M|B))?\b",
        r"(?:round size|funding round).*?(?:\$|\€)?\s*(\d[\d\.,]+)(?:\s*(?:k|m|b|million|billion|M|B))?\b",
    ]
    
    for pattern in funding_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            value_str = match.group(1).replace(",", "")
            try:
                value = float(value_str)
                
                # Determine multiplier if present
                multiplier = 1
                if "k" in match.group(0).lower():
                    multiplier = 1000
                elif any(x in match.group(0).lower() for x in ["m", "million"]):
                    multiplier = 1000000
                elif any(x in match.group(0).lower() for x in ["b", "billion"]):
                    multiplier = 1000000000
                
                # Store the funding request
                financial_data["funding_requested"] = value * multiplier
                break
            except ValueError:
                pass
    
    return financial_data

# --- Enhanced Email Functions ---
def send_enhanced_email_reply(to_email: str, subject: str, reply_text: str, personalization: Dict[str, Any] = None) -> bool:
    """Send an enhanced HTML email with better formatting and personalization"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Re: {subject}"
    msg["From"] = EMAIL_USER
    msg["To"] = to_email
    
    # Default personalization if none provided
    if not personalization:
        personalization = {
            "greeting": "Hi there",
            "signature": "The Mano Team",
            "title": "Chief of Staff",
            "include_thesis": False
        }
    
    # Plain text version
    plain_text = f"{personalization.get('greeting', 'Hi there')},\n\n{reply_text}\n\nBest,\n{personalization.get('signature', 'The Mano Team')}"
    msg.attach(MIMEText(plain_text, "plain"))

    
    # HTML version with better formatting
    html_parts = []
    html_parts.append(f"<p>{personalization.get('greeting', 'Hi there')},</p>")
    
    # Format the main content with paragraphs
    paragraphs = reply_text.split("\n\n")
    for p in paragraphs:
        if p.strip():
            replaced = p.replace('\n', '<br>')
            html_parts.append(f"<p>{replaced}</p>")

    
    # Add thesis if requested
    if personalization.get("include_thesis", False):
        html_parts.append("<p><strong>Our Investment Thesis:</strong></p>")
        first_paragraph = VC_THESIS.split('\n\n')[0]
        html_parts.append(f"<p><em>{first_paragraph}</em></p>")

    
    # Add signature
    html_parts.append("<p>Best,<br>")
    html_parts.append(f"{personalization.get('signature', 'The Mano Team')}")
    if personalization.get("title"):
        html_parts.append(f"<br><span style='color: #666;'>{personalization.get('title')}</span>")
    html_parts.append("</p>")
    
    html_content = f"""
    <html>
      <head>
        <style>
          body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
          }}
          p {{
            margin-bottom: 16px;
          }}
        </style>
      </head>
      <body>
        {''.join(html_parts)}
      </body>
    </html>
    """
    
    msg.attach(MIMEText(html_content, "html"))
    
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, [to_email], msg.as_string())
        logger.info(f"Enhanced email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return False

def schedule_followup(founder_email: str, days: int = 14, email_type: str = "check_in") -> None:
    """Schedule a follow-up email to be sent in the future"""
    future_date = datetime.datetime.now() + datetime.timedelta(days=days)
    
    followup_data = {
        "founder_email": founder_email,
        "scheduled_date": future_date,
        "email_type": email_type,
        "status": "pending",
        "created_at": firestore.SERVER_TIMESTAMP
    }
    
    try:
        db.collection("scheduled_followups").add(followup_data)
        logger.info(f"Scheduled {email_type} follow-up for {founder_email} on {future_date.strftime('%Y-%m-%d')}")
    except Exception as e:
        logger.error(f"Failed to schedule follow-up: {e}")

# --- Founder Profile Management ---
def load_founder_profile(email: str) -> Founder:
    """Load or create a founder profile"""
    try:
        founder_docs = db.collection("founders").where("email", "==", email).limit(1).get()
        founder_doc = founder_docs[0] if founder_docs else None

        
        if not founder_doc:
            # Create new founder profile
            name_match = re.match(r"^([^@]+)@", email)
            name = name_match.group(1).replace(".", " ").title() if name_match else ""
            
            founder = Founder(email=email, name=name)
            db.collection("founders").add(founder.to_dict())
            logger.info(f"Created new founder profile for {email}")
            return founder
        
        # Return existing profile
        founder_data = founder_doc.to_dict()
        return Founder(
            email=founder_data.get("email"),
            name=founder_data.get("name", ""),
            company=founder_data.get("company", ""),
            role=founder_data.get("role", ""),
            last_interaction=founder_data.get("last_interaction", ""),
            pitch_count=founder_data.get("pitch_count", 0),
            response_rate=founder_data.get("response_rate", 0.0),
            tags=founder_data.get("tags", []),
            funding_stage=founder_data.get("funding_stage", ""),
            sector=founder_data.get("sector", ""),
            location=founder_data.get("location", ""),
            linkedin=founder_data.get("linkedin", ""),
            website=founder_data.get("website", ""),
            intro_source=founder_data.get("intro_source", ""),
            follow_ups=founder_data.get("follow_ups", 0)
        )
    except Exception as e:
        logger.error(f"Error loading founder profile: {e}")
        # Return a default profile as fallback
        return Founder(email=email)

def update_founder_profile(founder: Founder) -> bool:
    """Update a founder's profile in the database"""
    try:
        # Find the founder document
        founder_docs = db.collection("founders").where("email", "==", founder.email).limit(1).get()
        founder_doc = founder_docs[0] if founder_docs else None

        
        if not founder_doc:
            # Create a new document if it doesn't exist
            db.collection("founders").add(founder.to_dict())
        else:
            # Update the existing document
            doc_id = founder_doc.id
            db.collection("founders").document(doc_id).update(founder.to_dict())
        
        logger.info(f"Updated profile for founder: {founder.email}")
        return True
    except Exception as e:
        logger.error(f"Failed to update founder profile: {e}")
        return False

def extract_founder_info(email_body: str, pdf_text: str = "") -> Dict[str, Any]:
    """Extract founder information from email and pitch deck"""
    combined_text = f"{email_body}\n\n{pdf_text}"
    
    # Extract company name
    company_patterns = [
        r"(?:at|from|with|CEO of|founder of|co-founder of)\s+([A-Z][A-Za-z0-9\.\-]+(?:\s+[A-Z][A-Za-z0-9\.\-]+){0,2})",
        r"([A-Z][A-Za-z0-9\.\-]+(?:\s+[A-Z][A-Za-z0-9\.\-]+){0,2})(?:\s+is|\s+team|\s+deck)",
    ]
    
    company = ""
    for pattern in company_patterns:
        matches = re.finditer(pattern, combined_text)
        for match in matches:
            company = match.group(1).strip()
            if company and not re.match(r"\b(Inc|LLC|Ltd|Team|Company|Startup)\b", company):
                break
    
    # Extract founder name
    name_patterns = [
        r"(?:^|\n)(?:Hi|Hello|Hey),?\s+(?:I(?:'|a)m|my\s+name\s+is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})",
        r"(?:^|\n)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}),?(?:\s+here|,\s+founder|,\s+CEO)",
    ]
    
    name = ""
    for pattern in name_patterns:
        matches = re.finditer(pattern, combined_text)
        for match in matches:
            name = match.group(1).strip()
            break
    
    # Extract other information
    info = {
        "company": company,
        "name": name,
        "role": "",
        "stage": "",
        "sector": "",
        "location": "",
        "website": "",
        "linkedin": ""
    }
    
    # Extract role
    role_match = re.search(r"(?:^|\n|\s)(CEO|Founder|Co-Founder|CTO|COO|President)(?:\s+and\s+(CEO|Founder|Co-Founder|CTO|COO|President))?", combined_text, re.IGNORECASE)
    if role_match:
        info["role"] = role_match.group(1)
    
    # Extract funding stage
    stage_match = re.search(r"(pre-seed|seed|series\s+[a-c]|early stage)", combined_text, re.IGNORECASE)
    if stage_match:
        info["stage"] = stage_match.group(1)
    
    # Extract sector
    sectors = ["fintech", "healthtech", "edtech", "SaaS", "AI", "machine learning", "marketplace", "e-commerce", "enterprise", "consumer", "gaming"]
    for sector in sectors:
        if re.search(r"\b" + sector + r"\b", combined_text, re.IGNORECASE):
            info["sector"] = sector
            break
    
    # Extract website
    website_match = re.search(r"(https?://[^\s/$.?#].[^\s]*)", combined_text)
    if website_match:
        info["website"] = website_match.group(1)
    
    # Extract LinkedIn
    linkedin_match = re.search(r"(linkedin\.com/[^\s]+)", combined_text)
    if linkedin_match:
        info["linkedin"] = "https://" + linkedin_match.group(1) if not linkedin_match.group(1).startswith("https://") else linkedin_match.group(1)
    
    return info

# --- Advanced Pitch Analysis ---
def analyze_pitch_alignment(email_body: str, pdf_text: str) -> PitchAnalysis:
    """Analyze how well a pitch aligns with the VC thesis"""
    
    # Combine email and PDF content
    combined_text = f"{email_body}\n\n{pdf_text}"
    
    # Extract basic company info
    founder_info = extract_founder_info(email_body, pdf_text)
    company = founder_info.get("company", "Unnamed Startup")
    
    # Extract financial data
    financial_data = extract_financial_data(combined_text)
    
    # Use GPT for detailed analysis
    analysis_prompt = f"""
    You are a venture capital analyst evaluating startup pitches against our investment thesis.
    
    OUR INVESTMENT THESIS:
    {VC_THESIS}
    
    STARTUP PITCH:
    {combined_text[:15000]}  # Limit text size to prevent token overflow
    
    Provide a detailed analysis of this startup in the following JSON format:
    
    {{
        "company": "Company name",
        "summary": "2-3 sentence summary of the business",
        "market_size": estimated market size in billions USD (null if unclear),
        "team_score": score from 1-10 based on team strength,
        "tech_score": score from 1-10 based on technology/product,
        "traction_score": score from 1-10 based on traction/metrics,
        "business_model_score": score from 1-10 based on business model viability,
        "moat_score": score from 1-10 based on competitive advantage,
        "overall_score": weighted average score from 0-10,
        "thesis_alignment": score from 0-10 on alignment with our thesis,
        "funding_stage": "pre-seed/seed/series A/etc",
        "sector": "primary sector/category",
        "funds_requested": amount in millions USD (null if not specified),
        "valuation": valuation in millions USD (null if not specified),
        "key_metrics": {{
            "users": user count if mentioned,
            "revenue": annual revenue if mentioned,
            "growth_rate": growth rate if mentioned,
            "unit_economics": unit economics if mentioned
        }},
        "risks": ["risk 1", "risk 2", "risk 3"],
        "opportunities": ["opportunity 1", "opportunity 2", "opportunity 3"],
        "recommendation": "Pass/Consider/Strong Consider"
    }}
    
    Respond ONLY with the JSON object.
    """
    
    try:
        analysis_result = chat_with_gpt(analysis_prompt)
        
        # Parse the JSON response
        try:
            analysis_data = json.loads(analysis_result)
            
            # Create PitchAnalysis object
            pitch_analysis = PitchAnalysis(
                company=analysis_data.get("company", company),
                founder_email=founder_info.get("email", ""),
                summary=analysis_data.get("summary", ""),
                market_size=analysis_data.get("market_size"),
                team_score=analysis_data.get("team_score", 0),
                tech_score=analysis_data.get("tech_score", 0),
                traction_score=analysis_data.get("traction_score", 0),
                business_model_score=analysis_data.get("business_model_score", 0),
                moat_score=analysis_data.get("moat_score", 0),
                overall_score=analysis_data.get("overall_score", 0.0),
                thesis_alignment=analysis_data.get("thesis_alignment", 0.0),
                funding_stage=analysis_data.get("funding_stage", ""),
                sector=analysis_data.get("sector", ""),
                funds_requested=analysis_data.get("funds_requested"),
                valuation=analysis_data.get("valuation"),
                key_metrics=analysis_data.get("key_metrics", {}),
                risks=analysis_data.get("risks", []),
                opportunities=analysis_data.get("opportunities", []),
                recommendation=analysis_data.get("recommendation", "")
            )
            
            # Override with extracted financial data if available
            if financial_data.get("funding_requested") and not pitch_analysis.funds_requested:
                pitch_analysis.funds_requested = financial_data.get("funding_requested") / 1000000  # Convert to millions
            
            if financial_data.get("valuation") and not pitch_analysis.valuation:
                pitch_analysis.valuation = financial_data.get("valuation") / 1000000  # Convert to millions
            
            logger.info(f"Pitch analysis completed for {company} with alignment score {pitch_analysis.thesis_alignment}")
            return pitch_analysis
            
        except json.JSONDecodeError:
            logger.error("Failed to parse analysis JSON")
            # Return basic analysis
            return PitchAnalysis(
                company=company,
                founder_email=founder_info.get("email", ""),
                summary="Failed to generate detailed analysis",
                overall_score=0.0,
                thesis_alignment=0.0,
                recommendation="Pass"
            )
    except Exception as e:
        logger.error(f"Pitch analysis failed: {e}")
        # Return basic analysis
        return PitchAnalysis(
            company=company,
            founder_email=founder_info.get("email", ""),
            summary=f"Error during analysis: {str(e)}",
            overall_score=0.0,
            thesis_alignment=0.0,
            recommendation="Pass"
        )

def generate_internal_memo(pitch_analysis: PitchAnalysis) -> str:
    """Generate an internal memo for the investment team"""
    memo_template = f"""
    ## Internal Memo: {pitch_analysis.company}
    
    **Analysis Date:** {datetime.datetime.now().strftime('%Y-%m-%d')}
    
    ### Executive Summary
    {pitch_analysis.summary}
    
    ### Key Metrics
    - **Sector:** {pitch_analysis.sector}
    - **Stage:** {pitch_analysis.funding_stage}
    - **Funds Requested:** {f"${pitch_analysis.funds_requested}M" if pitch_analysis.funds_requested else "Not specified"}
    - **Valuation:** {f"${pitch_analysis.valuation}M" if pitch_analysis.valuation else "Not specified"}
    - **Market Size:** {f"${pitch_analysis.market_size}B" if pitch_analysis.market_size else "Not specified"}
    
    ### Scores (1-10 scale)
    - **Team:** {pitch_analysis.team_score}/10
    - **Technology:** {pitch_analysis.tech_score}/10
    - **Traction:** {pitch_analysis.traction_score}/10
    - **Business Model:** {pitch_analysis.business_model_score}/10
    - **Competitive Moat:** {pitch_analysis.moat_score}/10
    - **Overall Score:** {pitch_analysis.overall_score}/10
    - **Thesis Alignment:** {pitch_analysis.thesis_alignment}/10
    
    ### Business Metrics
    {json.dumps(pitch_analysis.key_metrics, indent=2)}
    
    ### Risks
    {chr(10).join(f"- {risk}" for risk in pitch_analysis.risks)}
    
    ### Opportunities
    {chr(10).join(f"- {opportunity}" for opportunity in pitch_analysis.opportunities)}
    
    ### Recommendation
    {pitch_analysis.recommendation}
    """
    
    return memo_template

# --- Workflow Functions ---
def determine_response_type(pitch_analysis: PitchAnalysis) -> str:
    """Determine the appropriate response based on pitch analysis"""
    if pitch_analysis.thesis_alignment >= 7.0:
        return "high_alignment"
    elif pitch_analysis.thesis_alignment >= 5.0:
        return "medium_alignment"
    else:
        return "low_alignment"

def generate_customized_response(response_type: str, pitch_analysis: PitchAnalysis) -> str:
    """Generate a customized response based on the alignment type"""
    
    # Precompute anything involving backslashes to avoid f-string syntax errors
    if response_type == "high_alignment":
        return (
            f"Thank you for sharing your pitch deck for {pitch_analysis.company}.\n\n"
            f"Your approach to {pitch_analysis.sector} is intriguing, and I particularly appreciate your focus on {pitch_analysis.opportunities[0] if pitch_analysis.opportunities else 'innovative solutions'}.\n\n"
            "I've shared your materials with our investment team for review. Given your stage and focus, there's strong potential alignment with our current thesis.\n\n"
            "I'd like to schedule a brief call to learn more about your vision and traction. Would you have 30 minutes available next week? Please let me know what times work for you.\n\n"
            f"In the meantime, it would be helpful if you could share any additional metrics or information on your {pitch_analysis.risks[0] if pitch_analysis.risks else 'market strategy'}."
        )
    
    elif response_type == "medium_alignment":
        return (
            f"Thank you for sharing your pitch for {pitch_analysis.company}.\n\n"
            f"We appreciate the opportunity to learn about your work in {pitch_analysis.sector}. Your materials have been logged for our team to review.\n\n"
            "While we're currently focused on companies with specific characteristics within this space, we're always looking to stay connected with promising teams like yours.\n\n"
            "If you're open to it, I'd be happy to provide some brief feedback on your pitch or answer any questions you might have about our investment focus."
        )
    
    else:  # low_alignment
        thesis_target_sectors = ', '.join(
            VC_THESIS.split('\n\n')[0].split(' within ')[1].split(', ')
        )
        
        return (
            f"Thank you for sharing your pitch with us.\n\n"
            f"We've reviewed your materials for {pitch_analysis.company} and appreciate the opportunity to learn about your venture.\n\n"
            f"At this time, we're primarily focused on investments that more directly align with our thesis in {thesis_target_sectors}.\n\n"
            "I wish you the best of luck with your fundraising efforts and building your business. If your focus evolves or you have other ventures in the future that might align more closely with our investment areas, please don't hesitate to reach out."
        )


# --- Main Processing Functions ---
def process_pitch_deck(email_obj: Dict[str, Any], pdf_text: str) -> Tuple[PitchAnalysis, str]:
    """Process a pitch deck and determine appropriate response"""
    # Extract basic founder info
    founder_info = extract_founder_info(email_obj["body"], pdf_text)
    
    # Load or create founder profile
    founder = load_founder_profile(email_obj["sender"])
    
    # Update founder profile with extracted info
    if founder_info.get("name") and not founder.name:
        founder.name = founder_info.get("name")
    if founder_info.get("company") and not founder.company:
        founder.company = founder_info.get("company")
    if founder_info.get("role") and not founder.role:
        founder.role = founder_info.get("role")
    if founder_info.get("sector") and not founder.sector:
        founder.sector = founder_info.get("sector")
    
    # Update interaction metrics
    founder.pitch_count += 1
    founder.last_interaction = datetime.datetime.now().isoformat()
    
    # Perform detailed pitch analysis
    pitch_analysis = analyze_pitch_alignment(email_obj["body"], pdf_text)
    
    # Update founder profile with pitch analysis data
    if pitch_analysis.company and not founder.company:
        founder.company = pitch_analysis.company
    if pitch_analysis.sector and not founder.sector:
        founder.sector = pitch_analysis.sector
    if pitch_analysis.funding_stage and not founder.funding_stage:
        founder.funding_stage = pitch_analysis.funding_stage
    
    # Add appropriate tags based on analysis
    if pitch_analysis.thesis_alignment >= 7.0:
        if "high_alignment" not in founder.tags:
            founder.tags.append("high_alignment")
    elif pitch_analysis.thesis_alignment >= 5.0:
        if "medium_alignment" not in founder.tags:
            founder.tags.append("medium_alignment")
    else:
        if "low_alignment" not in founder.tags:
            founder.tags.append("low_alignment")
    
    # Save updated founder profile
    update_founder_profile(founder)
    
    # Determine response type
    response_type = determine_response_type(pitch_analysis)
    
    # Generate appropriate response
    response_text = generate_customized_response(response_type, pitch_analysis)
    
    return pitch_analysis, response_text

def handle_founder_email(email_obj: Dict[str, Any]) -> Dict[str, Any]:
    """Enhanced handler for founder emails with pitch decks"""
    start_time = datetime.datetime.now()
    
    # Check for attachments
    attachments = email_obj.get("attachments", {})
    pdf_text = ""
    pdf_metadata = {}
    has_attachment = False
    
    if attachments:
        pdf_filename, pdf_bytes = next(iter(attachments.items()))
        pdf_text = extract_text_from_pdf(pdf_bytes)
        if pdf_text.strip():
            has_attachment = True
            pdf_metadata = extract_pdf_metadata(pdf_bytes)
            logger.info(f"Processed PDF: {pdf_filename} with {len(pdf_text)} characters, {pdf_metadata.get('page_count', 0)} pages")
    else:
        logger.info("No pitch deck attached — continuing with email body only")

    email_body = email_obj["body"].strip()
    sender = email_obj["sender"]
    subject = email_obj["subject"]
    
    # Load founder profile
    founder = load_founder_profile(sender)
    
    # Determine if this is a meaningful pitch
    meaningful_pitch = False
    
    # If we have PDF content, it's likely a pitch
    if pdf_text.strip():
        meaningful_pitch = True
    
    # Check email body for pitch indicators if no PDF
    if not meaningful_pitch:
        pitch_indicators = ["pitch", "startup", "raising", "funding", "investment", "venture", "seed round"]
        if any(indicator in email_body.lower() for indicator in pitch_indicators):
            meaningful_pitch = True
    
    # Process as a pitch
    if meaningful_pitch:
        logger.info(f"Processing pitch from {sender}")
        
        # Process the pitch and get analysis and response
        pitch_analysis, response_text = process_pitch_deck(email_obj, pdf_text)
        
        # Save pitch to Firestore
        try:
            pitch_data = {
                "sender": sender,
                "subject": subject,
                "body": email_body,
                "parsed_summary": pitch_analysis.summary,
                "has_attachment": has_attachment,
                "thread_id": email_obj.get("thread_id"),
                "recipients": email_obj.get("recipients", []),
                "source": "founder",
                "company": pitch_analysis.company,
                "sector": pitch_analysis.sector,
                "funding_stage": pitch_analysis.funding_stage,
                "thesis_alignment": pitch_analysis.thesis_alignment,
                "recommendation": pitch_analysis.recommendation,
                "analysis": pitch_analysis.to_dict(),
                "pdf_metadata": pdf_metadata,
                "timestamp": firestore.SERVER_TIMESTAMP
            }
            
            # Store in Firestore
            pitch_ref = db.collection("pitches").add(pitch_data)
            pitch_id = pitch_ref[1].id
            logger.info(f"Pitch saved for {sender} with ID: {pitch_id}")
            
            # Generate and store internal memo
            memo_text = generate_internal_memo(pitch_analysis)
            
            memo_data = {
                "pitch_id": pitch_id,
                "founder_email": sender,
                "company": pitch_analysis.company,
                "content": memo_text,
                "created_at": firestore.SERVER_TIMESTAMP
            }
            
            db.collection("internal_memos").add(memo_data)
            logger.info(f"Internal memo generated for {pitch_analysis.company}")
            
            # Store vector embeddings for semantic search
            try:
                vector_data = {
                    "text": f"{email_body}\n\n{pdf_text[:5000]}",
                    "metadata": {
                        "type": "pitch",
                        "company": pitch_analysis.company,
                        "sector": pitch_analysis.sector,
                        "thesis_alignment": pitch_analysis.thesis_alignment,
                        "pitch_id": pitch_id
                    }
                }
                
                store_vector(vector_data)
                logger.info(f"Vector embeddings stored for {pitch_analysis.company}")
            except Exception as e:
                logger.error(f"Failed to store vector embeddings: {e}")
            
            # Send response email
            response_personalization = {
                "greeting": f"Hi {founder.name or 'there'}",
                "signature": "The Mano Team",
                "title": "Chief of Staff",
                "include_thesis": pitch_analysis.thesis_alignment < 5.0  # Include thesis for low alignment
            }
            
            send_enhanced_email_reply(sender, subject, response_text, response_personalization)
            logger.info(f"Pitch response sent to {sender}")
            
            # Schedule appropriate follow-up based on alignment
            if pitch_analysis.thesis_alignment >= 7.0:
                schedule_followup(sender, days=7, email_type="high_interest")
            elif pitch_analysis.thesis_alignment >= 5.0:
                schedule_followup(sender, days=14, email_type="medium_interest")
            
            # If this is a high alignment pitch, notify the investment team
            if pitch_analysis.thesis_alignment >= 7.0:
                notify_investment_team(pitch_analysis, pitch_id)
            
            return {
                "status": "success",
                "message": "Pitch processed successfully",
                "pitch_analysis": pitch_analysis.to_dict(),
                "response_type": determine_response_type(pitch_analysis)
            }
            
        except Exception as e:
            logger.error(f"Error processing pitch: {e}")
            return {
                "status": "error",
                "message": f"Error processing pitch: {str(e)}"
            }
    
    # Not a meaningful pitch, handle as general inquiry
    else:
        logger.info(f"Handling general inquiry from {sender}")
        
        # Send a request for more information
        inquiry_response = """
Thank you for reaching out!

It looks like we weren't able to extract a full pitch or deck from your message. Could you kindly resend your pitch, preferably with a PDF deck if you have one?

This would help us better understand your startup and evaluate alignment with our investment thesis.
"""
        
        response_personalization = {
            "greeting": f"Hi {founder.name or 'there'}",
            "signature": "The Mano Team",
            "title": "Chief of Staff",
            "include_thesis": True  # Include thesis for clarification
        }
        
        send_enhanced_email_reply(sender, subject, inquiry_response, response_personalization)
        logger.info(f"Information request sent to {sender}")
        
        # Save as a general inquiry
        try:
            inquiry_data = {
                "sender": sender,
                "subject": subject,
                "body": email_body,
                "type": "general_inquiry",
                "thread_id": email_obj.get("thread_id"),
                "recipients": email_obj.get("recipients", []),
                "source": "founder",
                "timestamp": firestore.SERVER_TIMESTAMP
            }
            
            db.collection("founder_communications").add(inquiry_data)
            logger.info(f"General inquiry saved for {sender}")
        except Exception as e:
            logger.error(f"Failed to save inquiry: {e}")
        
        return {
            "status": "success",
            "message": "General inquiry handled",
            "type": "information_request"
        }

def handle_founder_reply(email_obj: Dict[str, Any]) -> Dict[str, Any]:
    """Enhanced handler for founder replies to previous communications"""
    sender = email_obj["sender"]
    subject = email_obj["subject"]
    body = email_obj["body"]
    
    # Load founder profile
    founder = load_founder_profile(sender)
    
    # Update interaction metrics
    founder.last_interaction = datetime.datetime.now().isoformat()
    founder.follow_ups += 1
    update_founder_profile(founder)
    
    try:
        # Find the most recent pitch from this founder
        pitch_docs = db.collection("pitches")\
            .where("sender", "==", sender)\
            .order_by("timestamp", direction=firestore.Query.DESCENDING)\
            .limit(1)\
            .get()

        pitch_doc = pitch_docs[0] if pitch_docs else None  # ✅
        
        if not pitch_doc:
            # No previous pitch found, try to find any communication
            comm_docs = db.collection("founder_communications")\
                .where("sender", "==", sender)\
                .order_by("timestamp", direction=firestore.Query.DESCENDING)\
                .limit(1)\
                .get()
                
            comm_doc = comm_docs[0] if comm_docs else None  # ✅
            
            if not comm_doc:
                # No history at all, treat as new inquiry
                no_history_response = """
Thanks for your message. I don't seem to have your original pitch in our system. 

Would you mind sharing your pitch deck so I can better understand your startup and how I might help?
"""
                send_enhanced_email_reply(sender, subject, no_history_response, {
                    "greeting": f"Hi {founder.name or 'there'}",
                    "signature": "The Mano Team",
                    "title": "Chief of Staff"
                })
                
                logger.info(f"No history found for {sender}, requested pitch")
                return {"status": "success", "message": "No history, requested pitch"}
            
            # Found some communication but no pitch
            general_response = """
Thanks for your follow-up. I've noted your message.

To help me provide the most relevant assistance, could you share a pitch deck if you haven't already? This would give our team better context about your startup.

If you have specific questions or areas where you'd like feedback, please let me know.
"""
            send_enhanced_email_reply(sender, subject, general_response, {
                "greeting": f"Hi {founder.name or 'there'}",
                "signature": "The Mano Team",
                "title": "Chief of Staff"
            })
            
            # Save the communication
            comm_data = {
                "sender": sender,
                "subject": subject,
                "body": body,
                "type": "follow_up",
                "thread_id": email_obj.get("thread_id"),
                "timestamp": firestore.SERVER_TIMESTAMP
            }
            
            db.collection("founder_communications").add(comm_data)
            logger.info(f"Follow-up saved for {sender} (no pitch history)")
            
            return {"status": "success", "message": "General follow-up handled"}
        
        # We found a previous pitch
        pitch_data = pitch_doc.to_dict()
        pitch_id = pitch_doc.id
        
        # Check if this is a request for feedback
        feedback_indicators = ["feedback", "thoughts", "opinion", "what do you think", "any input", "suggestions"]
        is_feedback_request = any(indicator in body.lower() for indicator in feedback_indicators)
        
        if is_feedback_request:
            logger.info(f"Processing feedback request from {sender}")
            
            # Get the pitch analysis from the stored pitch
            pitch_analysis = pitch_data.get("analysis", {})
            
            if not pitch_analysis:
                # We don't have detailed analysis, generate basic feedback
                feedback = generate_friendly_feedback(f"""
Original Pitch Subject: {pitch_data.get('subject', 'Unknown')}

Original Pitch Summary: {pitch_data.get('parsed_summary', 'No summary available')}

Founder Reply: {body}
""")
            else:
                # Generate detailed feedback based on stored analysis
                feedback_prompt = f"""
You are a VC associate providing constructive feedback to a founder.

COMPANY: {pitch_analysis.get('company', 'the company')}
SECTOR: {pitch_analysis.get('sector', 'your sector')}

STRENGTHS:
- {pitch_analysis.get('opportunities', ['No specific strengths noted'])[0] if pitch_analysis.get('opportunities') else 'Your approach to the market'}
- {pitch_analysis.get('opportunities', ['No specific strengths noted'])[1] if len(pitch_analysis.get('opportunities', [])) > 1 else 'The clarity of your vision'}

AREAS FOR IMPROVEMENT:
- {pitch_analysis.get('risks', ['No specific risks noted'])[0] if pitch_analysis.get('risks') else 'Further detail on your go-to-market strategy'}
- {pitch_analysis.get('risks', ['No specific risks noted'])[1] if len(pitch_analysis.get('risks', [])) > 1 else 'Additional metrics on customer acquisition costs'}

ALIGNMENT WITH OUR THESIS:
This scores a {pitch_analysis.get('thesis_alignment', 'moderate')} out of 10 on alignment with our current thesis.

FOUNDER'S REQUEST:
{body}

Provide friendly, constructive feedback that:
1. Acknowledges their strengths
2. Offers 1-2 specific suggestions for improvement
3. Is honest but encouraging
4. Doesn't make funding promises
5. Keeps the door open for future interaction

Write in a personal, helpful tone as if from a VC associate to a founder.
"""
                feedback = chat_with_gpt(feedback_prompt)
            
            # Send the feedback
            send_enhanced_email_reply(sender, subject, feedback, {
                "greeting": f"Hi {founder.name or 'there'}",
                "signature": "The Mano Team",
                "title": "Chief of Staff"
            })
            
            # Record that feedback was provided
            db.collection("pitches").document(pitch_id).update({
                "feedback_provided": True,
                "feedback_timestamp": firestore.SERVER_TIMESTAMP,
                "feedback_text": feedback
            })
            
            # Save the communication
            comm_data = {
                "sender": sender,
                "subject": subject,
                "body": body,
                "type": "feedback_request",
                "pitch_id": pitch_id,
                "response": feedback,
                "thread_id": email_obj.get("thread_id"),
                "timestamp": firestore.SERVER_TIMESTAMP
            }
            
            db.collection("founder_communications").add(comm_data)
            logger.info(f"Feedback provided to {sender}")
            
            return {"status": "success", "message": "Feedback provided"}
        
        # Not explicitly asking for feedback - check for meeting request
        meeting_indicators = ["meet", "call", "chat", "discuss", "zoom", "time this week", "time next week", "available"]
        is_meeting_request = any(indicator in body.lower() for indicator in meeting_indicators)
        
        if is_meeting_request:
            logger.info(f"Processing meeting request from {sender}")
            
            # Get the pitch alignment from the stored pitch
            alignment_score = pitch_data.get("thesis_alignment", 0)
            
            if alignment_score >= 6.0:
                # High enough alignment - suggest meeting
                meeting_response = f"""
Thank you for your interest in connecting!

I'd be happy to schedule a call to discuss your startup further. Would any of these times work for you?

- Monday between 2-4pm ET
- Tuesday between 10am-12pm ET
- Thursday between 1-3pm ET

Once you confirm a time, I'll send a calendar invite with details.

Looking forward to learning more about {pitch_data.get('company', 'your company')}.
"""
            else:
                # Lower alignment - politely decline meeting
                meeting_response = f"""
Thank you for your interest in connecting.

At this time, our team is focused on startups that more closely align with our current investment thesis, and we have limited bandwidth for calls.

However, I'm happy to continue the conversation over email if you have specific questions or updates about your progress. As your company evolves, there may be opportunities for us to engage more deeply in the future.

I appreciate your understanding.
"""
            
            # Send the response
            send_enhanced_email_reply(sender, subject, meeting_response, {
                "greeting": f"Hi {founder.name or 'there'}",
                "signature": "The Mano Team",
                "title": "Chief of Staff"
            })
            
            # Save the communication
            comm_data = {
                "sender": sender,
                "subject": subject,
                "body": body,
                "type": "meeting_request",
                "pitch_id": pitch_id,
                "meeting_offered": alignment_score >= 6.0,
                "thread_id": email_obj.get("thread_id"),
                "timestamp": firestore.SERVER_TIMESTAMP
            }
            
            db.collection("founder_communications").add(comm_data)
            logger.info(f"Meeting request handled for {sender}")
            
            return {
                "status": "success", 
                "message": "Meeting request handled",
                "meeting_offered": alignment_score >= 6.0
            }
        
        # General follow-up - generate contextual response
        logger.info(f"Processing general follow-up from {sender}")
        
        # Get context from previous communications
        context_docs = db.collection("founder_communications")\
            .where("sender", "==", sender)\
            .order_by("timestamp", direction=firestore.Query.DESCENDING)\
            .limit(3)\
            .stream()
            
        context = []
        for doc in context_docs:
            context_data = doc.to_dict()
            context.append({
                "type": context_data.get("type", "communication"),
                "body": context_data.get("body", "")[:200] + "..." if len(context_data.get("body", "")) > 200 else context_data.get("body", ""),
                "timestamp": context_data.get("timestamp")
            })
        
        # Generate contextual response
        general_prompt = f"""
You are a VC firm's Chief of Staff responding to a founder follow-up email.

FOUNDER: {founder.name or sender}
COMPANY: {pitch_data.get('company', 'Unknown')}
PREVIOUS PITCH SUMMARY: {pitch_data.get('parsed_summary', 'No summary available')}
THESIS ALIGNMENT SCORE: {pitch_data.get('thesis_alignment', 'Unknown')} / 10

RECENT INTERACTIONS:
{json.dumps(context, indent=2)}

CURRENT MESSAGE:
{body}

Draft a helpful, friendly response that:
1. Acknowledges their message
2. Provides relevant information or assistance
3. Maintains appropriate expectations based on their alignment score
4. Suggests a reasonable next step

Keep your response under 150 words and in a professional but personable tone.
"""
        
        general_response = chat_with_gpt(general_prompt)
        
        # Send the response
        send_enhanced_email_reply(sender, subject, general_response, {
            "greeting": f"Hi {founder.name or 'there'}",
            "signature": "The Mano Team",
            "title": "Chief of Staff"
        })
        
        # Save the communication
        comm_data = {
            "sender": sender,
            "subject": subject,
            "body": body,
            "type": "general_follow_up",
            "pitch_id": pitch_id,
            "response": general_response,
            "thread_id": email_obj.get("thread_id"),
            "timestamp": firestore.SERVER_TIMESTAMP
        }
        
        db.collection("founder_communications").add(comm_data)
        logger.info(f"General follow-up handled for {sender}")
        
        return {"status": "success", "message": "General follow-up handled"}
        
    except Exception as e:
        logger.error(f"Failed to handle founder reply: {e}")
        
        # Send fallback response
        fallback_response = """
Thank you for your message. I've noted your email and will follow up appropriately.

If you have a specific question or request that wasn't addressed in this automatic response, please let me know.
"""
        
        send_enhanced_email_reply(sender, subject, fallback_response, {
            "greeting": f"Hi {founder.name or 'there'}",
            "signature": "The Mano Team",
            "title": "Chief of Staff"
        })
        
        return {"status": "error", "message": f"Error handling reply: {str(e)}"}

# --- Notification and Team Collaboration ---
def notify_investment_team(pitch_analysis: PitchAnalysis, pitch_id: str) -> bool:
    """Send notification to investment team about high-potential pitch"""
    try:
        # In a real implementation, would integrate with team communication tools
        # like Slack, email distribution lists, etc.
        
        # For now, save to notifications collection
        notification_data = {
            "type": "high_potential_pitch",
            "pitch_id": pitch_id,
            "company": pitch_analysis.company,
            "sender": pitch_analysis.founder_email,
            "alignment_score": pitch_analysis.thesis_alignment,
            "sector": pitch_analysis.sector,
            "summary": pitch_analysis.summary,
            "status": "unread",
            "created_at": firestore.SERVER_TIMESTAMP
        }
        
        db.collection("team_notifications").add(notification_data)
        logger.info(f"Investment team notified about high-potential pitch: {pitch_analysis.company}")
        
        return True
    except Exception as e:
        logger.error(f"Failed to notify investment team: {e}")
        return False

def handle_scheduled_follow_ups() -> None:
    """Process scheduled follow-ups that are due"""
    now = datetime.datetime.now()
    
    try:
        # Query follow-ups that are due
        due_followups = db.collection("scheduled_followups")\
            .where("status", "==", "pending")\
            .stream()
            
        for followup in due_followups:
            followup_id = followup.id
            followup_data = followup.to_dict()
            
            # Check if this follow-up is due
            scheduled_date = datetime.datetime.fromisoformat(followup_data.get("scheduled_date"))
            
            if scheduled_date <= now:
                logger.info(f"Processing due follow-up: {followup_id}")
                
                founder_email = followup_data.get("founder_email")
                email_type = followup_data.get("email_type")
                
                # Load founder profile
                founder = load_founder_profile(founder_email)
                
                # Get the most recent pitch
                pitch_docs = db.collection("pitches")\
                    .where("sender", "==", founder_email)\
                    .order_by("timestamp", direction=firestore.Query.DESCENDING)\
                    .limit(1)\
                    .stream()
                    
                pitch_doc = next(pitch_docs, None)
                
                if not pitch_doc:
                    # No pitch found, skip this follow-up
                    logger.warning(f"No pitch found for scheduled follow-up: {followup_id}")
                    db.collection("scheduled_followups").document(followup_id).update({
                        "status": "skipped",
                        "processed_at": firestore.SERVER_TIMESTAMP,
                        "error": "No pitch found"
                    })
                    continue
                
                pitch_data = pitch_doc.to_dict()
                
                # Generate and send follow-up email based on type
                if email_type == "high_interest":
                    subject = f"Following up on your {pitch_data.get('company', 'startup')} pitch"
                    body = f"""
I hope this finds you well. I wanted to follow up on the pitch you shared with us for {pitch_data.get('company', 'your startup')}.

Our team has reviewed your materials and found them intriguing. We're particularly interested in your {pitch_data.get('sector', 'approach')} and would like to learn more.

Would you be available for a brief call in the next week to discuss your progress and answer a few questions from our team?

Also, if you have any updated metrics or materials since your original pitch, please feel free to share them.
"""
                elif email_type == "medium_interest":
                    subject = f"Checking in on {pitch_data.get('company', 'your startup')}"
                    body = f"""
I hope you've been well since we last connected about {pitch_data.get('company', 'your startup')}.

I wanted to check in and see how things have been progressing. Have you hit any significant milestones or made key changes to your approach since we last spoke?

While we're still evaluating fit with our current investment focus, we'd love to stay updated on your progress.
"""
                else:
                    subject = "Touching base"
                    body = f"""
I hope things are going well with {pitch_data.get('company', 'your startup')}.

I'm reaching out to check in and see if there have been any significant developments or if you have any questions I might help with.

We appreciate you keeping us in the loop on your journey.
"""
                
                # Send the follow-up
                send_enhanced_email_reply(founder_email, subject, body, {
                    "greeting": f"Hi {founder.name or 'there'}",
                    "signature": "The Mano Team",
                    "title": "Chief of Staff"
                })
                
                # Mark follow-up as completed
                db.collection("scheduled_followups").document(followup_id).update({
                    "status": "completed",
                    "processed_at": firestore.SERVER_TIMESTAMP
                })
                
                # Record the communication
                comm_data = {
                    "sender": "system",
                    "recipient": founder_email,
                    "subject": subject,
                    "body": body,
                    "type": "scheduled_followup",
                    "followup_id": followup_id,
                    "pitch_id": pitch_doc.id,
                    "thread_id": pitch_data.get("thread_id"),
                    "timestamp": firestore.SERVER_TIMESTAMP
                }
                
                db.collection("founder_communications").add(comm_data)
                logger.info(f"Follow-up sent to {founder_email}")
                
                # Schedule next follow-up if appropriate
                if email_type == "high_interest":
                    schedule_followup(founder_email, days=21, email_type="high_interest")
                elif email_type == "medium_interest":
                    schedule_followup(founder_email, days=30, email_type="medium_interest")
    
    except Exception as e:
        logger.error(f"Error processing scheduled follow-ups: {e}")

# --- Search and Retrieval Functions ---
def search_similar_pitches(company_name: str, sector: str = None) -> List[Dict[str, Any]]:
    """Search for similar pitches using vector similarity"""
    try:
        query_text = f"Startup: {company_name}"
        if sector:
            query_text += f", Sector: {sector}"
        
        # Search vectors for similar pitches
        results = search_vectors(query_text, filter_criteria={"type": "pitch"}, limit=5)
        
        # Format results
        similar_pitches = []
        for result in results:
            pitch_id = result.get("metadata", {}).get("pitch_id")
            if pitch_id:
                # Get the full pitch data
                pitch_doc = db.collection("pitches").document(pitch_id).get()
                if pitch_doc.exists:
                    pitch_data = pitch_doc.to_dict()
                    similar_pitches.append({
                        "company": pitch_data.get("company", "Unknown"),
                        "sector": pitch_data.get("sector", "Unknown"),
                        "summary": pitch_data.get("parsed_summary", ""),
                        "thesis_alignment": pitch_data.get("thesis_alignment", 0),
                        "similarity_score": result.get("score", 0)
                    })
        
        return similar_pitches
    except Exception as e:
        logger.error(f"Error searching similar pitches: {e}")
        return []

def generate_sector_insights(sector: str) -> Dict[str, Any]:
    """Generate insights about a specific sector based on pitches received"""
    try:
        # Query pitches in this sector
        sector_pitches = db.collection("pitches")\
            .where("sector", "==", sector)\
            .stream()
        
        # Collect data
        pitch_count = 0
        total_alignment = 0
        high_alignment_count = 0
        companies = []
        
        for pitch in sector_pitches:
            pitch_data = pitch.to_dict()
            pitch_count += 1
            alignment = pitch_data.get("thesis_alignment", 0)
            total_alignment += alignment
            
            if alignment >= 7.0:
                high_alignment_count += 1
            
            companies.append({
                "name": pitch_data.get("company", "Unknown"),
                "alignment": alignment,
                "timestamp": pitch_data.get("timestamp")
            })
        
        # Calculate metrics
        avg_alignment = total_alignment / pitch_count if pitch_count > 0 else 0
        high_alignment_percentage = (high_alignment_count / pitch_count * 100) if pitch_count > 0 else 0
        
        # Sort companies by alignment
        companies.sort(key=lambda x: x.get("alignment", 0), reverse=True)
        
        return {
            "sector": sector,
            "pitch_count": pitch_count,
            "average_alignment": avg_alignment,
            "high_alignment_percentage": high_alignment_percentage,
            "top_companies": companies[:5] if companies else [],
            "generated_at": datetime.datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error generating sector insights: {e}")
        return {
            "sector": sector,
            "error": str(e),
            "generated_at": datetime.datetime.now().isoformat()
        }

# --- Reporting and Analytics ---
def generate_pitch_flow_report(days: int = 30) -> Dict[str, Any]:
    """Generate a report on pitch flow and metrics over a period"""
    try:
        # Calculate date range
        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=days)
        
        # Query pitches in date range
        pitches = db.collection("pitches")\
            .where("timestamp", ">=", start_date)\
            .stream()
        
        # Collect metrics
        total_pitches = 0
        sectors = {}
        stages = {}
        alignment_distribution = {
            "high": 0,    # >=7
            "medium": 0,  # 5-6.9
            "low": 0      # <5
        }
        weekly_counts = {}
        
        for pitch in pitches:
            pitch_data = pitch.to_dict()
            total_pitches += 1
            
            # Track sector
            sector = pitch_data.get("sector", "Unknown")
            sectors[sector] = sectors.get(sector, 0) + 1
            
            # Track stage
            stage = pitch_data.get("funding_stage", "Unknown")
            stages[stage] = stages.get(stage, 0) + 1
            
            # Track alignment
            alignment = pitch_data.get("thesis_alignment", 0)
            if alignment >= 7.0:
                alignment_distribution["high"] += 1
            elif alignment >= 5.0:
                alignment_distribution["medium"] += 1
            else:
                alignment_distribution["low"] += 1
            
            # Track weekly distribution
            timestamp = pitch_data.get("timestamp")
            if timestamp:
                week_start = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
                week_start = week_start - datetime.timedelta(days=week_start.weekday())
                week_key = week_start.strftime("%Y-%m-%d")
                weekly_counts[week_key] = weekly_counts.get(week_key, 0) + 1
        
        # Sort sectors and stages by count
        sorted_sectors = sorted(sectors.items(), key=lambda x: x[1], reverse=True)
        sorted_stages = sorted(stages.items(), key=lambda x: x[1], reverse=True)
        
        # Sort weekly counts chronologically
        sorted_weekly = sorted(weekly_counts.items())
        
        return {
            "period_days": days,
            "total_pitches": total_pitches,
            "pitch_per_day": total_pitches / days if days > 0 else 0,
            "sectors": sorted_sectors,
            "stages": sorted_stages,
            "alignment_distribution": alignment_distribution,
            "weekly_trend": sorted_weekly,
            "generated_at": datetime.datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error generating pitch flow report: {e}")
        return {
            "period_days": days,
            "error": str(e),
            "generated_at": datetime.datetime.now().isoformat()
        }

def analyze_founder_engagement() -> Dict[str, Any]:
    """Analyze founder engagement metrics"""
    try:
        # Query all founder profiles
        founders = db.collection("founders").stream()
        
        total_founders = 0
        responding_founders = 0
        high_engagement_founders = 0
        follow_up_counts = []
        
        for founder_doc in founders:
            founder_data = founder_doc.to_dict()
            total_founders += 1
            
            # Track response metrics
            follow_ups = founder_data.get("follow_ups", 0)
            follow_up_counts.append(follow_ups)
            
            if follow_ups > 0:
                responding_founders += 1
            
            if follow_ups >= 3:
                high_engagement_founders += 1
        
        # Calculate metrics
        response_rate = (responding_founders / total_founders * 100) if total_founders > 0 else 0
        high_engagement_rate = (high_engagement_founders / total_founders * 100) if total_founders > 0 else 0
        avg_follow_ups = sum(follow_up_counts) / len(follow_up_counts) if follow_up_counts else 0
        
        return {
            "total_founders": total_founders,
            "responding_founders": responding_founders,
            "response_rate": response_rate,
            "high_engagement_founders": high_engagement_founders,
            "high_engagement_rate": high_engagement_rate,
            "average_follow_ups": avg_follow_ups,
            "generated_at": datetime.datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error analyzing founder engagement: {e}")
        return {
            "error": str(e),
            "generated_at": datetime.datetime.now().isoformat()
        }

# --- Main Functions ---
def run_scheduled_tasks() -> None:
    """Run all scheduled background tasks"""
    try:
        # Process due follow-ups
        handle_scheduled_follow_ups()
        
        # Generate daily pitch flow report (if needed)
        now = datetime.datetime.now()
        if now.hour == 8 and now.minute < 15:  # Run daily at approximately 8:00 AM
            report = generate_pitch_flow_report(days=30)
            
            report_data = {
                "type": "pitch_flow",
                "data": report,
                "created_at": firestore.SERVER_TIMESTAMP
            }
            
            db.collection("reports").add(report_data)
            logger.info("Generated daily pitch flow report")
        
        # Log successful run
        db.collection("system_status").document("scheduled_tasks").set({
            "last_run": datetime.datetime.now().isoformat(),
            "status": "success"
        })
        
        logger.info("Scheduled tasks completed successfully")
    except Exception as e:
        logger.error(f"Error running scheduled tasks: {e}")
        
        # Log error
        db.collection("system_status").document("scheduled_tasks").set({
            "last_run": datetime.datetime.now().isoformat(),
            "status": "error",
            "error_message": str(e)
        })

# Entry point for processing a new founder email
if __name__ == "__main__":
    # Example usage with a sample email
    sample_email = {
        "thread_id": "thread-123",
        "sender": "founder@startup.com",
        "recipients": ["vc@example.com"],
        "subject": "Pitch for AI-Driven SaaS Platform",
        "body": """
        Hi there,
        
        I'm Sarah Johnson, founder of DataFlow AI. We're building an AI-driven data pipeline management platform that helps companies automate their ETL workflows.
        
        We're raising a $2M seed round at a $10M valuation. We currently have $50K MRR with 120% growth quarter-over-quarter.
        
        I've attached our pitch deck and would love to connect if there's interest.
        
        Best,
        Sarah
        """,
        "attachments": {}  # Would contain PDF data in a real scenario
    }
    
    # Process the email
    result = handle_founder_email(sample_email)
    
    # Print the result
    print(json.dumps(result, indent=2))