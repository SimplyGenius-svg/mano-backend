from vector_db import PitchVectorDB
import argparse

def main():
    parser = argparse.ArgumentParser(description="Query the vector database for similar pitches")
    parser.add_argument("--query", type=str, help="Search query")
    parser.add_argument("--industry", type=str, default=None, help="Filter by industry")
    parser.add_argument("--min-score", type=float, default=None, help="Minimum match score (1-5)")
    parser.add_argument("--limit", type=int, default=5, help="Number of results to return")
    
    args = parser.parse_args()
    
    db = PitchVectorDB()
    
    if args.query:
        results = db.search_similar_pitches(
            query_text=args.query,
            n_results=args.limit,
            industry=args.industry,
            min_score=args.min_score
        )
    else:
        results = db.get_all_pitches(
            industry=args.industry,
            min_score=args.min_score,
            limit=args.limit
        )
    
    print(f"\n📊 Found {len(results)} matching pitches:\n")
    
    for i, pitch in enumerate(results, 1):
        print(f"--- Pitch #{i} ---")
        print(f"Company: {pitch['company_name']}")
        print(f"Industry: {pitch['industry']}")
        print(f"Match Score: {pitch['match_score']}")
        print(f"From: {pitch['founder_email']}")
        print(f"Subject: {pitch['subject']}")
        print(f"Summary: {pitch['summary'][:150]}...")
        print(f"Date: {pitch['date_received']}")
        if 'distance' in pitch and pitch['distance'] is not None:
            print(f"Similarity: {1 - pitch['distance']:.2f}")
        print()
    
if __name__ == "__main__":
    main()