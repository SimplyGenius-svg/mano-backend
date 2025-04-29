from component_logger import component_logger

import os
import json
import logging
from firebase import db
from firebase_admin import firestore
from gpt_helpers import chat_with_gpt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("query_engine")

class QueryEngine:
    def __init__(self):
        self.collections = {
            "founders": "founder_communications",
            "startups": "startups",
            "pitches": "pitch_summaries",
            "communications": "founder_communications",
            "reminders": "reminders",
            "partners": "partners"
        }
        
    def parse_query(self, query_text):
        """Convert natural language query to structured query parameters"""
        # Log component usage
        component_logger.log_usage("query_engine", action="parse_query", 
                                  metadata={"query_length": len(query_text)})
        
        system_prompt = """
        You are a database query analyzer. Convert the natural language query into a structured JSON format with these fields:
        - collection: The main data collection to query
        - filters: List of conditions to filter by
        - sort_by: Field to sort results by
        - sort_direction: "asc" or "desc"
        - limit: Number of results to return
        
        Available collections:
        - founders: Information about founders who've contacted us
        - startups: Company information and metrics
        - pitches: Pitch summary data and assessments
        - communications: Email communications history
        - reminders: Scheduled reminders and follow-ups
        - partners: VC partner information
        
        Example query: "Show me the top 5 highest scoring startups from the last month"
        Example output: 
        {
          "collection": "startups",
          "filters": [
            {"field": "created_at", "operator": ">=", "value": "1_month_ago"}
          ],
          "sort_by": "score",
          "sort_direction": "desc",
          "limit": 5
        }
        """
        
        try:
            response = chat_with_gpt(query_text, system_prompt)
            return json.loads(response)
        except Exception as e:
            logger.error(f"Failed to parse query: {e}")
            return None
    
    def execute_query(self, query_params):
        """Execute the structured query against Firestore"""
        if not query_params or "collection" not in query_params:
            return {"error": "Invalid query parameters"}
        
        collection_name = self.collections.get(query_params["collection"])
        if not collection_name:
            return {"error": f"Unknown collection: {query_params['collection']}"}
        
        # Start building the query
        query = db.collection(collection_name)
        
        # Apply filters
        for filter_item in query_params.get("filters", []):
            field = filter_item.get("field")
            operator = filter_item.get("operator")
            value = filter_item.get("value")
            
            # Handle special date values
            if isinstance(value, str) and value.endswith("_ago"):
                value = self._parse_relative_date(value)
                
            query = query.where(field, operator, value)
        
        # Apply sorting
        if "sort_by" in query_params:
            direction = firestore.Query.DESCENDING if query_params.get("sort_direction") == "desc" else firestore.Query.ASCENDING
            query = query.order_by(query_params["sort_by"], direction=direction)
        
        # Apply limit
        if "limit" in query_params:
            query = query.limit(query_params["limit"])
        
        # Execute query
        try:
            results = [doc.to_dict() for doc in query.stream()]
            return results
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            return {"error": f"Query execution failed: {str(e)}"}
    
    def _parse_relative_date(self, relative_date):
        """Convert relative date strings like '1_month_ago' to datetime objects"""
        import datetime
        
        now = datetime.datetime.now()
        parts = relative_date.split('_')
        
        try:
            value = int(parts[0])
            unit = parts[1]
            
            if unit == 'day' or unit == 'days':
                return now - datetime.timedelta(days=value)
            elif unit == 'week' or unit == 'weeks':
                return now - datetime.timedelta(weeks=value)
            elif unit == 'month' or unit == 'months':
                return now - datetime.timedelta(days=value * 30)
            elif unit == 'year' or unit == 'years':
                return now - datetime.timedelta(days=value * 365)
        except:
            pass
        
        return now

    def format_response(self, results, query_text):
        """Format query results into a readable response with visualization"""
        from visualization import suggest_visualization, generate_chart
        
        if isinstance(results, dict) and "error" in results:
            return f"⚠️ Error: {results['error']}"
        
        if not results:
            return "No results found for your query."
        
        # Check if visualization would be helpful
        viz_suggestion = suggest_visualization(results, query_text)
        viz_html = ""
        
        if viz_suggestion["chart_type"] != "none":
            try:
                viz_html = generate_chart(
                    results,
                    viz_suggestion["chart_type"],
                    viz_suggestion["x_field"],
                    viz_suggestion["y_field"],
                    viz_suggestion["title"]
                )
            except Exception as e:
                logger.error(f"Visualization generation failed: {e}")
        
        system_prompt = f"""
        You are a data presentation specialist. Format these database results into a beautiful, readable format.
        Use markdown tables, bullet points, and other formatting to make the data clear and easy to understand.
        
        Original query: "{query_text}"
        
        Results:
        {json.dumps(results, indent=2, default=str)}
        
        Format the data in a way that best answers the query and highlights the most important information.
        """
        
        text_response = chat_with_gpt("Please format these database results in a beautiful, readable way.", system_prompt)
        
        if viz_html:
            return f"{text_response}\n\n{viz_html}"
        else:
            return text_response

def query_data(query_text):
    """Main function to process natural language queries"""
    engine = QueryEngine()
    
    # Parse query
    query_params = engine.parse_query(query_text)
    
    # Handle parsing failures
    if not query_params:
        return """
### ⚠️ I couldn't understand that query

I'm currently able to answer questions about:
- Founders and their communications
- Startups in our database and their metrics
- Pitch summaries and assessments
- Scheduled reminders and follow-ups

Could you try rephrasing your question with more specific details?
"""
    
    # Execute query
    results = engine.execute_query(query_params)
    
    # Check for execution errors
    if isinstance(results, dict) and "error" in results:
        error_msg = results["error"]
        
        if "Unknown collection" in error_msg:
            return f"""
### ⚠️ Query Topic Not Found

I don't have data about "{query_params.get('collection', 'unknown')}".

I can answer questions about:
- founders and their communications
- startups and their metrics
- pitches and their assessments
- scheduled reminders
- partners

Please try asking about one of these topics instead.
"""
        else:
            return f"""
### ⚠️ Query Error

I couldn't complete your request: {error_msg}

Please try a simpler query or contact support if you believe this is a system error.
"""
    
    # Format response
    response = engine.format_response(results, query_text)
    
    return response