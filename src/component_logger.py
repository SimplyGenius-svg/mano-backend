import os
import time
import json
from datetime import datetime
from functools import wraps

class ComponentLogger:
    """Logs usage of different components in the system."""
    
    def __init__(self, log_file="component_usage.log", analytics_file="component_analytics.json"):
        self.log_file = log_file
        self.analytics_file = analytics_file
        self.analytics = self._load_analytics()
    
    def log_usage(self, component_name, action="used", metadata=None):
        """Log a component usage event"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp} | {component_name} | {action}"
        if metadata:
            log_entry += f" | {json.dumps(metadata)}"
        
        # Write to log file
        with open(self.log_file, "a") as f:
            f.write(log_entry + "\n")
        
        # Update analytics
        if component_name not in self.analytics:
            self.analytics[component_name] = {"usage_count": 0, "first_used": timestamp, "last_used": timestamp}
        
        self.analytics[component_name]["usage_count"] += 1
        self.analytics[component_name]["last_used"] = timestamp
        
        # Save analytics
        self._save_analytics()
        
        return True
    
    def _load_analytics(self):
        """Load component usage analytics"""
        if os.path.exists(self.analytics_file):
            try:
                with open(self.analytics_file, "r") as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_analytics(self):
        """Save component usage analytics"""
        with open(self.analytics_file, "w") as f:
            json.dump(self.analytics, f, indent=2)
    
    def get_analytics(self):
        """Get component usage analytics"""
        return self.analytics

# Create a singleton instance
component_logger = ComponentLogger()

# Decorator for easy logging of function calls
def log_component(component_name):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Log the component usage
            component_logger.log_usage(
                component_name, 
                action=f"called_{func.__name__}",
                metadata={"args_count": len(args), "kwargs": list(kwargs.keys())}
            )
            
            # Call the original function
            return func(*args, **kwargs)
        return wrapper
    return decorator