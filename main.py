from agent import ai_agents
from src.agent.graph_builder import GraphBuilder

def main():
    # Build the LangGraph
    graph_builder_instance = GraphBuilder()
    graph = graph_builder_instance.build_graph()

    # Define a sample email input
    test_email = {
        "email_type": "founder",  # Try "partner" or "unknown" for other paths
        "sender_email": "jane@startup.com",
        "subject": "Pitch: Revolutionary AI Startup",
        "body": "We'd love to discuss our new funding round...",
        "metadata": {
            "thread_length": 3,
            "received_at": "2025-05-14T10:00:00Z"
        }
    }

    # Invoke the graph with the test input
    print("=== Running AI Agent Graph ===")
    result = graph.invoke(test_email)

    # Output the final result
    print("\n=== Final Output State ===")
    print(result)

if __name__ == "__main__":
    main()
# This script serves as the entry point for running the LangGraph-based AI agent system.