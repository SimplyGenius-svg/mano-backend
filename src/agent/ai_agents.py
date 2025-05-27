from langgraph.graph import StateGraph
from src.agent.react_agents import (
    EmailProcessingAgent,
    PartnerProfileAgent,
    InvestmentAnalysisAgent,
    DigestGenerationAgent,
    ReplyGeneratorAgent
)

def email_processing_agent(state):
    return EmailProcessingAgent().process(state)

def partner_profile_agent(state):
    return PartnerProfileAgent().process(state)

def investment_analysis_agent(state):
    return InvestmentAnalysisAgent().process(state)

def digest_generation_agent(state):
    return DigestGenerationAgent().process(state)

def reply_generator_agent(state):
    return ReplyGeneratorAgent().process(state)

# For compatibility with the existing graph, provide aliases
email_classifier_agent = email_processing_agent
founder_agent = partner_profile_agent
pitch_analysis_agent = investment_analysis_agent
reply_generator_agent = reply_generator_agent
partner_agent = partner_profile_agent
capital_analysis_agent = investment_analysis_agent
digest_generator_agent = digest_generation_agent
unclassified_logger_agent = lambda state: state  # No-op for now
