import os
import chromadb
import pandas as pd
from sentence_transformers import SentenceTransformer
from pathlib import Path
import json
from datetime import datetime

class PitchVectorDB:
    def __init__(self, persist_directory="./vector_db"):
        # Initialize the embedding model
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Create directory if it doesn't exist
        os.makedirs(persist_directory, exist_ok=True)
        
        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(path=persist_directory)
        
        # Create or get collection for pitches
        self.collection = self.client.get_or_create_collection(
            name="founder_pitches",
            metadata={"hnsw:space": "cosine"}
        )
        
        # Path to store metadata
        self.metadata_path = Path(persist_directory) / "pitch_metadata.csv"
        self.load_metadata()
    
    def load_metadata(self):
        """Load metadata from CSV or create if not exists"""
        if os.path.exists(self.metadata_path):
            self.metadata_df = pd.read_csv(self.metadata_path)
        else:
            self.metadata_df = pd.DataFrame(columns=[
                'id', 'founder_email', 'company_name', 'subject', 
                'summary', 'match_score', 'industry', 'date_received'
            ])
            self.metadata_df.to_csv(self.metadata_path, index=False)
    
    def add_pitch(self, pdf_text, metadata):
        """
        Add a new pitch to the vector database
        
        Args:
            pdf_text (str): The text extracted from the pitch PDF
            metadata (dict): Contains founder_email, subject, summary, match_score, etc.
        
        Returns:
            str: ID of the added pitch
        """
        # Generate a unique ID based on email and timestamp
        pitch_id = f"pitch_{metadata['founder_email']}_{int(datetime.now().timestamp())}"
        
        # Generate embedding from the PDF text
        embedding = self.model.encode(pdf_text)
        
        # Add to ChromaDB
        self.collection.add(
            ids=[pitch_id],
            embeddings=[embedding.tolist()],
            metadatas=[{
                "founder_email": metadata.get("founder_email", "unknown"),
                "subject": metadata.get("subject", "No subject"),
                "company_name": metadata.get("company_name", "Unknown"),
                "industry": metadata.get("industry", "Unknown"),
                "match_score": metadata.get("match_score", "0"),
            }],
            documents=[pdf_text[:10000]]  # Store truncated document text
        )
        
        # Add to metadata dataframe
        new_row = {
            'id': pitch_id,
            'founder_email': metadata.get("founder_email", "unknown"),
            'company_name': metadata.get("company_name", "Unknown"),
            'subject': metadata.get("subject", "No subject"),
            'summary': metadata.get("summary", "No summary"),
            'match_score': metadata.get("match_score", "0"),
            'industry': metadata.get("industry", "Unknown"),
            'date_received': datetime.now().isoformat()
        }
        
        self.metadata_df = pd.concat([self.metadata_df, pd.DataFrame([new_row])], ignore_index=True)
        self.metadata_df.to_csv(self.metadata_path, index=False)
        
        return pitch_id
    
    def search_similar_pitches(self, query_text, n_results=5, industry=None, min_score=None):
        """
        Search for similar pitches based on text query
        
        Args:
            query_text (str): Query text to search for
            n_results (int): Number of results to return
            industry (str, optional): Filter by industry
            min_score (float, optional): Filter by minimum match score
            
        Returns:
            list: List of matching pitches with metadata
        """
        # Generate embedding for query
        query_embedding = self.model.encode(query_text)
        
        # Create filter if needed
        where_filter = {}
        if industry:
            where_filter["industry"] = industry
        if min_score and float(min_score) > 0:
            where_filter["match_score"] = {"$gte": min_score}
        
        # Execute search
        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=n_results,
            where=where_filter if where_filter else None
        )
        
        # Format results
        formatted_results = []
        if results and results['ids'] and len(results['ids'][0]) > 0:
            for i in range(len(results['ids'][0])):
                pitch_id = results['ids'][0][i]
                # Get full metadata from CSV for more details
                full_metadata = self.metadata_df[self.metadata_df['id'] == pitch_id]
                
                if not full_metadata.empty:
                    formatted_results.append({
                        'id': pitch_id,
                        'founder_email': full_metadata['founder_email'].iloc[0],
                        'company_name': full_metadata['company_name'].iloc[0],
                        'subject': full_metadata['subject'].iloc[0],
                        'summary': full_metadata['summary'].iloc[0],
                        'match_score': full_metadata['match_score'].iloc[0],
                        'industry': full_metadata['industry'].iloc[0],
                        'date_received': full_metadata['date_received'].iloc[0],
                        'distance': results['distances'][0][i] if 'distances' in results else None,
                    })
        
        return formatted_results
    
    def get_all_pitches(self, industry=None, min_score=None, limit=100):
        """Get all pitches with optional filtering"""
        query = self.metadata_df
        
        if industry:
            query = query[query['industry'] == industry]
        
        if min_score:
            query = query[query['match_score'].astype(float) >= float(min_score)]
        
        return query.head(limit).to_dict('records')