import matplotlib.pyplot as plt
import io
import base64
import pandas as pd
from typing import List, Dict, Any

def generate_chart(data: List[Dict[str, Any]], chart_type: str, x_field: str, y_field: str, title: str = None):
    """Generate a chart visualization from data"""
    plt.figure(figsize=(10, 6))
    
    # Convert to DataFrame for easier manipulation
    df = pd.DataFrame(data)
    
    if chart_type == "bar":
        plt.bar(df[x_field], df[y_field])
    elif chart_type == "line":
        plt.plot(df[x_field], df[y_field])
    elif chart_type == "pie":
        plt.pie(df[y_field], labels=df[x_field], autopct='%1.1f%%')
    elif chart_type == "scatter":
        plt.scatter(df[x_field], df[y_field])
    
    if title:
        plt.title(title)
    plt.xlabel(x_field)
    plt.ylabel(y_field)
    plt.tight_layout()
    
    # Save to bytes buffer
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    
    # Convert to base64 for embedding in HTML/email
    image_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
    plt.close()
    
    return f'<img src="data:image/png;base64,{image_data}" alt="{title}" />'

def suggest_visualization(data, query_text):
    """Suggest appropriate visualization based on data and query"""
    system_prompt = f"""
    Given this data and query, suggest the best visualization:
    - Data fields: {list(data[0].keys()) if data else []}
    - Query: {query_text}
    
    Return a JSON object with these fields:
    - chart_type: one of "bar", "line", "pie", "scatter", "none"
    - x_field: field name for x-axis
    - y_field: field name for y-axis
    - title: chart title
    
    If visualization doesn't make sense, return {{"chart_type": "none"}}
    """
    
    try:
        response = chat_with_gpt("Suggest visualization", system_prompt)
        return json.loads(response)
    except:
        return {"chart_type": "none"}