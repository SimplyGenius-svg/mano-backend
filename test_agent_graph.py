from src.agent.graph_builder import GraphBuilder
from dotenv import load_dotenv
import os

def main():
    # Example test email (partner requesting a digest and capital allocation)
    load_dotenv()
    test_email = {
        "email_type": "partner",
        "sender_email": "jane@vcfirm.com",
        "subject": "Weekly Digest & New Capital Request",
        "body": (
            "Hi Mano,\n\n"
            "Can you send me the weekly digest of top AI and fintech pitches?\n"
            "Also, we're considering a $2M investment in AcmeAI's Series A. "
            "Please prepare a summary and next steps.\n\n"
            "Thanks,\nJane"
        ),
        "metadata": {
            "thread_length": 2,
            "received_at": "2025-05-14T10:00:00Z"
        }
    }

    # Build the graph
    graph = GraphBuilder().build_graph()

    # Run the graph with the test email
    print("=== Running Agentified LangGraph ===")
    result = graph.invoke(test_email)

    # Output the final result
    print("\n=== Final Output State ===")
    for k, v in result.items():
        print(f"{k}: {v}")

if __name__ == "__main__":
    main()
