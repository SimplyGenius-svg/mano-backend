import os
import json
import logging
from typing import Dict, List, Optional, Union, Any
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
from firebase_admin import firestore
from openai import OpenAI
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("vc_digest")

# Load environment variables
load_dotenv()
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEFAULT_TIMEZONE = "America/Los_Angeles"  # Default timezone for date calculations

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Access Firestore DB (assuming it's already initialized in firebase.py)
from firebase import db

class VCDigestGenerator:
    """
    Generates and sends weekly digests of top startup pitches for VC partners.
    """
    
    def __init__(self, partner_emails: Union[str, List[str]] = None):
        """
        Initialize the digest generator.
        
        Args:
            partner_emails: Email(s) of partners to send digest to
        """
        self.partner_emails = partner_emails or ["gyanbhambhani@gmail.com"]
        if isinstance(self.partner_emails, str):
            self.partner_emails = [self.partner_emails]
            
        logger.info(f"Initialized VC Digest Generator for {len(self.partner_emails)} partner(s)")
    
    def fetch_recent_founder_pitches(self, days_back: int = 7, limit: int = 50) -> List[Dict]:
        """
        Fetch recent founder pitches from Firestore.
        
        Args:
            days_back: Number of days to look back
            limit: Maximum number of pitches to fetch
            
        Returns:
            List of founder pitch data dictionaries
        """
        logger.info(f"Fetching founder pitches from the last {days_back} days")
        
        # Calculate the date threshold
        cutoff_date = datetime.now(pytz.timezone(DEFAULT_TIMEZONE)) - timedelta(days=days_back)
        
        try:
            # Query Firestore for pitches received after the cutoff date
            pitches_ref = db.collection("founder_pitches")\
                .where("received_at", ">=", cutoff_date)\
                .order_by("received_at", direction=firestore.Query.DESCENDING)\
                .limit(limit)
            
            pitches = list(pitches_ref.stream())
            
            logger.info(f"Found {len(pitches)} pitches from the last {days_back} days")
            
            # Convert to list of dictionaries and add ID
            result = []
            for pitch in pitches:
                pitch_data = pitch.to_dict()
                pitch_data["id"] = pitch.id
                result.append(pitch_data)
                
            return result
        except Exception as e:
            logger.error(f"Error fetching founder pitches: {e}")
            return []
    
    def search_pitches(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Search for specific pitches using keywords/filters.
        
        Args:
            query: Search query (industry, founder name, etc.)
            limit: Maximum number of results
            
        Returns:
            List of matching pitch data dictionaries
        """
        logger.info(f"Searching pitches with query: '{query}'")
        
        try:
            # This is a simple implementation. For production, consider:
            # 1. Using a dedicated search service like Algolia
            # 2. Implementing more advanced filtering logic
            # 3. Adding fulltext search capabilities
            
            # Get all pitches (in production, this should be paginated/limited)
            pitches_ref = db.collection("founder_pitches").limit(100)
            pitches = list(pitches_ref.stream())
            
            # Filter results based on the query string (case-insensitive)
            query_lower = query.lower()
            results = []
            
            for pitch in pitches:
                pitch_data = pitch.to_dict()
                pitch_data["id"] = pitch.id
                
                # Check various fields for the query term
                if any(query_lower in str(value).lower() for value in pitch_data.values()):
                    results.append(pitch_data)
                    
                    # Break if we've hit the limit
                    if len(results) >= limit:
                        break
            
            logger.info(f"Found {len(results)} pitches matching query: '{query}'")
            return results
        except Exception as e:
            logger.error(f"Error searching pitches: {e}")
            return []
    
    def rank_pitches(self, pitches: List[Dict], top_n: int = 10, custom_criteria: Dict = None) -> List[Dict]:
        """
        Rank pitches based on partner preferences and other criteria.
        
        Args:
            pitches: List of pitches to rank
            top_n: Number of top pitches to return
            custom_criteria: Optional dictionary of custom ranking criteria
            
        Returns:
            List of ranked pitch dictionaries (top N)
        """
        logger.info(f"Ranking {len(pitches)} pitches to find top {top_n}")
        
        if not pitches:
            logger.warning("No pitches to rank")
            return []
        
        try:
            # Default ranking criteria
            criteria = {
                "traction_weight": 0.3,         # Weight for traction/revenue
                "team_weight": 0.2,             # Weight for team experience
                "market_weight": 0.2,           # Weight for market size/opportunity
                "investment_weight": 0.15,      # Weight for existing investment
                "innovation_weight": 0.15,      # Weight for product innovation
                # Additional weights for custom scoring
                "ai_bonus": 0.1,                # Bonus for AI startups
                "sustainability_bonus": 0.05,   # Bonus for sustainability-focused startups
            }
            
            # Override with custom criteria if provided
            if custom_criteria:
                criteria.update(custom_criteria)
                
            # Calculate scores for each pitch
            for pitch in pitches:
                # Initialize base score
                score = 0
                
                # Extract metrics for scoring (with defaults if missing)
                traction = pitch.get("traction", {})
                revenue = traction.get("revenue", 0)
                growth_rate = traction.get("growth_rate", 0)
                
                team = pitch.get("team", {})
                team_size = len(team.get("members", []))
                team_experience = team.get("experience_score", 0)
                
                market = pitch.get("market", {})
                market_size = market.get("size_usd", 0)
                
                investment = pitch.get("investment", {})
                raised_amount = investment.get("raised_amount", 0)
                
                # Apply weightings to calculate score
                score += (revenue * 0.7 + growth_rate * 0.3) * criteria["traction_weight"]
                score += (team_experience * 0.7 + team_size * 0.3) * criteria["team_weight"]
                score += market_size * criteria["market_weight"]
                score += raised_amount * criteria["investment_weight"]
                
                # Innovation score (could be more sophisticated in production)
                innovation_score = pitch.get("innovation_score", 5) / 10
                score += innovation_score * criteria["innovation_weight"]
                
                # Apply category bonuses
                if "ai" in pitch.get("category", "").lower() or "artificial intelligence" in pitch.get("description", "").lower():
                    score += criteria["ai_bonus"]
                
                if "sustainability" in pitch.get("category", "").lower() or "green" in pitch.get("description", "").lower():
                    score += criteria["sustainability_bonus"]
                
                # Store the score
                pitch["ranking_score"] = score
            
            # Sort pitches by score (descending)
            ranked_pitches = sorted(pitches, key=lambda x: x.get("ranking_score", 0), reverse=True)
            
            # Return the top N pitches
            return ranked_pitches[:top_n]
        except Exception as e:
            logger.error(f"Error ranking pitches: {e}")
            return pitches[:top_n]  # Fall back to original order
    
    def generate_digest_content(self, pitches: List[Dict], partner_name: str = "Partner") -> str:
        """
        Generate the digest content using OpenAI for summarization.
        
        Args:
            pitches: List of top pitch dictionaries
            partner_name: Name of the partner for personalization
            
        Returns:
            Formatted digest content as string
        """
        logger.info(f"Generating digest content for {len(pitches)} pitches")
        
        if not pitches:
            return f"No pitches to summarize for the requested period."
        
        try:
            # Format pitches for the prompt
            pitch_summaries = []
            for i, pitch in enumerate(pitches, 1):
                founder = pitch.get("founder", {})
                company = pitch.get("company", {})
                investment = pitch.get("investment", {})
                
                summary = (
                    f"#{i}: {company.get('name', 'Unnamed Startup')}\n"
                    f"Founder: {founder.get('name', 'Unknown')}\n"
                    f"Description: {company.get('description', 'No description provided')}\n"
                    f"Stage: {company.get('stage', 'Unknown')}\n"
                    f"Sector: {company.get('sector', 'Unknown')}\n"
                    f"Raised to date: ${investment.get('raised_amount', 0):,}\n"
                    f"Ask: ${investment.get('ask_amount', 0):,}\n"
                    f"Key metrics: {pitch.get('key_metrics', 'None provided')}\n"
                )
                pitch_summaries.append(summary)
            
            joined_summaries = "\n\n".join(pitch_summaries)
            
            # Create the prompt for OpenAI
            prompt = f"""
            You are summarizing this week's top founder pitches for a venture capital partner named {partner_name}.
            
            Here are the top pitches for the week:
            ---
            {joined_summaries}
            ---
            
            Please create a professional weekly digest with the following sections:
            1. A brief introduction personalized to {partner_name}
            2. A summary of key themes or trends from this week's pitches
            3. Brief highlights of each startup, focusing on what makes them interesting investment opportunities
            4. A concise conclusion
            
            Format the digest in a clean, professional manner. Use markdown formatting for readability.
            Include the company name, a one-line description, their ask, and why they might be worth investigating further.
            Prioritize clarity and actionable insights.
            """
            
            # Call OpenAI API for content generation
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "system", "content": "You are a professional VC analyst providing insightful weekly pitch digests."},
                          {"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=1500
            )
            
            digest_content = response.choices[0].message.content
            logger.info("Digest content successfully generated")
            
            return digest_content
        except Exception as e:
            logger.error(f"Error generating digest content: {e}")
            # Fallback to simple digest if API fails
            return self._generate_fallback_digest(pitches, partner_name)
    
    def _generate_fallback_digest(self, pitches: List[Dict], partner_name: str) -> str:
        """
        Generate a simple fallback digest without using the AI API.
        Used when the API call fails.
        
        Args:
            pitches: List of top pitch dictionaries
            partner_name: Name of the partner
            
        Returns:
            Simple formatted digest as string
        """
        logger.info("Generating fallback digest content")
        
        # Generate a simple text digest
        content = f"# Weekly Pitch Digest for {partner_name}\n\n"
        content += f"Here are the top {len(pitches)} pitches from this week:\n\n"
        
        for i, pitch in enumerate(pitches, 1):
            founder = pitch.get("founder", {})
            company = pitch.get("company", {})
            investment = pitch.get("investment", {})
            
            content += f"## {i}. {company.get('name', 'Unnamed Startup')}\n"
            content += f"**Founder:** {founder.get('name', 'Unknown')}\n"
            content += f"**Description:** {company.get('description', 'No description provided')}\n"
            content += f"**Asking:** ${investment.get('ask_amount', 0):,}\n"
            content += f"**Already raised:** ${investment.get('raised_amount', 0):,}\n\n"
        
        content += "Let me know if you'd like more details on any of these startups.\n\n"
        content += "Best regards,\nMano"
        
        return content
    
    def send_digest_email(self, content: str, partner_email: str, partner_name: str = "Partner") -> bool:
        """
        Send the digest email to a specific partner.
        
        Args:
            content: The digest content
            partner_email: Email address to send to
            partner_name: Name of the partner for personalization
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        logger.info(f"Preparing digest email for {partner_email}")
        
        try:
            # Create a multipart message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"🚀 Weekly Startup Pitch Digest - {datetime.now().strftime('%b %d, %Y')}"
            msg["From"] = f"Mano <{EMAIL_USER}>"
            msg["To"] = partner_email
            
            # Create plain text version
            text = content.replace("#", "").replace("**", "").replace("__", "")
            msg.attach(MIMEText(text, "plain"))
            
            # Create HTML version
            formatted_content = content.replace('# ', '<h1>') \
                .replace('\n## ', '</h1><h2>') \
                .replace('\n\n', '</p><p>') \
                .replace('**', '<strong>') \
                .replace('</strong>', '</strong>') \
                .replace('\n', '<br>')

            html_content = f"""
            <html>
              <head>
                <style>
                  body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 650px; margin: 0 auto; }}
                  h1 {{ color: #0066cc; border-bottom: 1px solid #ddd; padding-bottom: 10px; }}
                  h2 {{ color: #2c3e50; margin-top: 20px; }}
                  .company {{ font-weight: bold; color: #0066cc; }}
                  .metrics {{ background-color: #f9f9f9; padding: 10px; border-left: 4px solid #ddd; margin: 15px 0; }}
                  .footer {{ margin-top: 30px; color: #666; font-size: 0.9em; border-top: 1px solid #ddd; padding-top: 10px; }}
                  .ask {{ color: #e74c3c; font-weight: bold; }}
                </style>
              </head>
              <body>
                {formatted_content}
                <div class="footer">
                  <p>This digest was automatically generated by Mano for {partner_name}.<br>
                  To configure your digest preferences or request more information about any startup, simply reply to this email.</p>
                </div>
              </body>
            </html>
            """

            msg.attach(MIMEText(html_content, "html"))
            
            # Send the email
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(EMAIL_USER, EMAIL_PASS)
                server.sendmail(EMAIL_USER, [partner_email], msg.as_string())
            
            logger.info(f"✅ Weekly digest sent to {partner_email}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to send digest to {partner_email}: {e}")
            return False
    def process_digest_for_partner(self, partner_email: str, partner_name: str = None, days_back: int = 7, 
                                  top_n: int = 10, custom_criteria: Dict = None) -> bool:
        """
        Process and send a complete digest for a specific partner.
        
        Args:
            partner_email: Email address of the partner
            partner_name: Name of the partner (defaults to email username)
            days_back: Number of days to look back for pitches
            top_n: Number of top pitches to include
            custom_criteria: Optional dictionary of custom ranking criteria
            
        Returns:
            bool: True if digest processed and sent successfully
        """
        # Use email username as partner name if not provided
        if not partner_name:
            partner_name = partner_email.split('@')[0].replace('.', ' ').title()
        
        logger.info(f"Processing digest for {partner_name} ({partner_email})")
        
        try:
            # Fetch recent pitches
            recent_pitches = self.fetch_recent_founder_pitches(days_back=days_back)
            
            if not recent_pitches:
                logger.warning(f"No pitches found for the last {days_back} days")
                # Send a notification email about no pitches
                empty_content = f"# Weekly Pitch Digest\n\nHello {partner_name},\n\nThere were no new pitches received in the last {days_back} days. I'll continue monitoring and notify you when new pitches arrive.\n\nBest regards,\nMano"
                return self.send_digest_email(empty_content, partner_email, partner_name)
            
            # Rank the pitches based on criteria
            top_pitches = self.rank_pitches(recent_pitches, top_n=top_n, custom_criteria=custom_criteria)
            
            # Generate digest content
            digest_content = self.generate_digest_content(top_pitches, partner_name)
            
            # Send the digest
            return self.send_digest_email(digest_content, partner_email, partner_name)
        except Exception as e:
            logger.error(f"Failed to process digest for {partner_email}: {e}")
            return False
    
    def process_all_partner_digests(self, days_back: int = 7, top_n: int = 10) -> Dict[str, bool]:
        """
        Process and send digests for all configured partners.
        
        Args:
            days_back: Number of days to look back for pitches
            top_n: Number of top pitches to include
            
        Returns:
            Dict mapping partner emails to success status
        """
        logger.info(f"Processing digests for {len(self.partner_emails)} partners")
        
        results = {}
        
        # Fetch pitches once for all partners
        recent_pitches = self.fetch_recent_founder_pitches(days_back=days_back)
        
        if not recent_pitches:
            logger.warning(f"No pitches found for the last {days_back} days")
            # Send notification emails to all partners
            empty_content = f"# Weekly Pitch Digest\n\nHello,\n\nThere were no new pitches received in the last {days_back} days. I'll continue monitoring and notify you when new pitches arrive.\n\nBest regards,\nMano"
            
            for email in self.partner_emails:
                results[email] = self.send_digest_email(empty_content, email)
            
            return results
        
        # Process for each partner (with potentially different ranking criteria)
        for email in self.partner_emails:
            try:
                # Get partner preferences from database (if available)
                partner_prefs = self._get_partner_preferences(email)
                partner_name = partner_prefs.get("name", email.split('@')[0].replace('.', ' ').title())
                custom_criteria = partner_prefs.get("ranking_criteria")
                
                # Rank the pitches based on this partner's criteria
                top_pitches = self.rank_pitches(recent_pitches, top_n=top_n, custom_criteria=custom_criteria)
                
                # Generate digest content
                digest_content = self.generate_digest_content(top_pitches, partner_name)
                
                # Send the digest
                success = self.send_digest_email(digest_content, email, partner_name)
                results[email] = success
            except Exception as e:
                logger.error(f"Error processing digest for partner {email}: {e}")
                results[email] = False
        
        return results
    
    def _get_partner_preferences(self, partner_email: str) -> Dict:
        """
        Get partner preferences from the database.
        
        Args:
            partner_email: Email of the partner
            
        Returns:
            Dictionary of partner preferences
        """
        try:
            # Try to fetch partner document from Firestore
            partner_doc = db.collection("partners").document(partner_email).get()
            
            if partner_doc.exists:
                return partner_doc.to_dict()
            else:
                logger.info(f"No preferences found for partner {partner_email}")
                return {}
        except Exception as e:
            logger.error(f"Error fetching partner preferences: {e}")
            return {}
    
    def update_partner_preferences(self, partner_email: str, preferences: Dict) -> bool:
        """
        Update partner preferences in the database.
        
        Args:
            partner_email: Email of the partner
            preferences: Dictionary of preferences to update
            
        Returns:
            bool: True if update was successful
        """
        try:
            # Update or create partner document in Firestore
            db.collection("partners").document(partner_email).set(
                preferences, merge=True
            )
            logger.info(f"Updated preferences for partner {partner_email}")
            return True
        except Exception as e:
            logger.error(f"Error updating partner preferences: {e}")
            return False


# Entry point for standalone usage
if __name__ == "__main__":
    logger.info("Starting VC Pitch Digest process")
    
    # Configuration (could be moved to config file or environment variables)
    CONFIG = {
        "partners": ["gyanbhambhani@gmail.com", "bheleparamveer@gmail.com"],  # List of partner emails
        "days_back": 7,                          # Look back 7 days for pitches
        "top_n": 10,                             # Include top 10 pitches
    }
    
    try:
        # Initialize and run the digest generator
        digest_generator = VCDigestGenerator(CONFIG["partners"])
        
        # Process digests for all partners
        results = digest_generator.process_all_partner_digests(
            days_back=CONFIG["days_back"],
            top_n=CONFIG["top_n"]
        )
        
        # Log results
        success_count = sum(1 for success in results.values() if success)
        logger.info(f"Digest processing completed. {success_count}/{len(results)} successful.")
        
        for email, success in results.items():
            status = "✅ Sent" if success else "❌ Failed"
            logger.info(f"{status}: {email}")
    
    except Exception as e:
        logger.error(f"Error in main digest process: {e}")