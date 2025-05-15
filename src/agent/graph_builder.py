from langgraph.graph import StateGraph
from src.agent import agents
from typing import TypedDict, Literal, Optional, Dict, Any

class EmailState(TypedDict, total=False):
    email_type: Literal["founder", "partner", "unclassified"]
    sender_email: str
    subject: str
    body: str
    metadata: Dict[str, Any]
    pitch_insights: Optional[Dict[str, Any]]
    capital_info: Optional[Dict[str, Any]]
    summary: Optional[str]
    reply: Optional[str]


class GraphBuilder:
    def __init__(self):
        self.graph = StateGraph(state_schema=EmailState)
        

    def build_graph(self):
        # Define the nodes and their corresponding agent functions
        nodes = {
            "EmailClassifierAgent": agents.email_classifier_agent,
            "FounderAgent": agents.founder_agent,
            "PitchAnalysisAgent": agents.pitch_analysis_agent,
            "ReplyGeneratorAgent": agents.reply_generator_agent,
            "PartnerAgent": agents.partner_agent,
            "CapitalAnalysisAgent": agents.capital_analysis_agent,
            "DigestGeneratorAgent": agents.digest_generator_agent,
            "UnclassifiedLoggerAgent": agents.unclassified_logger_agent
        }

        # Add nodes to the graph
        for node_name, agent_func in nodes.items():
            self.graph.add_node(node_name, agent_func)

        # Define edges
        self.graph.set_entry_point("EmailClassifierAgent")
        self.graph.add_edge("EmailClassifierAgent", "FounderAgent")
        self.graph.add_edge("FounderAgent", "PitchAnalysisAgent")
        self.graph.add_edge("PitchAnalysisAgent", "ReplyGeneratorAgent")
        self.graph.add_edge("EmailClassifierAgent", "PartnerAgent")
        self.graph.add_edge("PartnerAgent", "CapitalAnalysisAgent")
        self.graph.add_edge("CapitalAnalysisAgent", "DigestGeneratorAgent")
        self.graph.add_edge("EmailClassifierAgent", "UnclassifiedLoggerAgent")

        # Finalize
        self.graph.set_finish_point("ReplyGeneratorAgent")
        self.graph.set_finish_point("DigestGeneratorAgent")
        self.graph.set_finish_point("UnclassifiedLoggerAgent")

        return self.graph.compile()
