from src.agent.ai_agents import *
from langgraph.graph import StateGraph
from typing import TypedDict, Literal, Optional, Dict, Any

class EmailState(TypedDict, total=False):
    email_type: Literal["founder", "partner", "unclassified"]
    sender_email: str
    subject: str
    body: str
    metadata: Dict[str, Any]
    pitch_insights: Optional[Dict[str, Any]]
    capital_info: Optional[Dict[str, Any]]
    capital_analysis: Optional[Dict[str, Any]]
    digest_content: Optional[str]
    summary: Optional[str]
    reply: Optional[str]
    email_analysis: Optional[Dict[str, Any]]
    partner_profile: Optional[Any]
    digest_generated: Optional[bool]

class GraphBuilder:
    def __init__(self):
        self.graph = StateGraph(state_schema=EmailState)

    def build_graph(self):
        # Define the nodes and their corresponding agent functions
        nodes = {
            "EmailProcessingAgent": email_processing_agent,
            "PartnerProfileAgent": partner_profile_agent,
            "InvestmentAnalysisAgent": investment_analysis_agent,
            "ReplyGeneratorAgent": reply_generator_agent,
        }

        # Add nodes to the graph
        for node_name, agent_func in nodes.items():
            self.graph.add_node(node_name, agent_func)

        # Define a linear flow to avoid state collisions
        self.graph.set_entry_point("EmailProcessingAgent")
        self.graph.add_edge("EmailProcessingAgent", "PartnerProfileAgent")
        self.graph.add_edge("PartnerProfileAgent", "InvestmentAnalysisAgent")
        self.graph.add_edge("InvestmentAnalysisAgent", "ReplyGeneratorAgent")

        # Set single finish point
        self.graph.set_finish_point("ReplyGeneratorAgent")

        return self.graph.compile()
