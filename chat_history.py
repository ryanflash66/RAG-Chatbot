"""
Chat History Management for RAG Chatbot
Handles saving, loading, and managing chat sessions
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import chainlit as cl
from config import get_chat_storage_dir, get_max_chat_history


class ChatHistoryManager:
    """Manages chat history persistence and retrieval."""
    
    def __init__(self):
        self.storage_dir = Path(get_chat_storage_dir())
        self.storage_dir.mkdir(exist_ok=True)
        self.max_history = get_max_chat_history()
    
    def save_chat_session(self, session_id: str, messages: List[Dict], title: str = None) -> None:
        """
        Save a chat session to storage.
        
        Args:
            session_id (str): Unique session identifier
            messages (List[Dict]): List of messages in the chat
            title (str, optional): Custom title for the chat
        """
        if not title:
            # Generate title from first user message or use timestamp
            title = self._generate_title(messages)
        
        session_data = {
            "session_id": session_id,
            "title": title,
            "timestamp": datetime.now().isoformat(),
            "messages": messages,
            "message_count": len([m for m in messages if m.get("type") == "user_message"])
        }
        
        file_path = self.storage_dir / f"{session_id}.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)
        
        # Clean up old sessions if we exceed max_history
        self._cleanup_old_sessions()
    
    def load_chat_session(self, session_id: str) -> Optional[Dict]:
        """
        Load a chat session from storage.
        
        Args:
            session_id (str): Session identifier to load
            
        Returns:
            Optional[Dict]: Session data or None if not found
        """
        file_path = self.storage_dir / f"{session_id}.json"
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    
    def get_chat_history(self) -> List[Dict]:
        """
        Get list of all chat sessions ordered by timestamp (newest first).
        
        Returns:
            List[Dict]: List of session metadata
        """
        sessions = []
        
        for file_path in self.storage_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)
                    # Only include metadata for the sidebar
                    sessions.append({
                        "session_id": session_data["session_id"],
                        "title": session_data["title"],
                        "timestamp": session_data["timestamp"],
                        "message_count": session_data.get("message_count", 0)
                    })
            except (json.JSONDecodeError, IOError):
                continue
        
        # Sort by timestamp (newest first)
        sessions.sort(key=lambda x: x["timestamp"], reverse=True)
        return sessions
    
    def delete_chat_session(self, session_id: str) -> bool:
        """
        Delete a chat session.
        
        Args:
            session_id (str): Session to delete
            
        Returns:
            bool: True if deleted successfully
        """
        file_path = self.storage_dir / f"{session_id}.json"
        if file_path.exists():
            try:
                file_path.unlink()
                return True
            except OSError:
                return False
        return False
    
    def _generate_title(self, messages: List[Dict]) -> str:
        """Generate a title from the first user message or timestamp."""
        for message in messages:
            if message.get("type") == "user_message" and message.get("content"):
                content = message["content"].strip()
                # Take first 50 characters and add ellipsis if longer
                if len(content) > 50:
                    return content[:47] + "..."
                return content
        
        # Fallback to timestamp
        return f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    def _cleanup_old_sessions(self) -> None:
        """Remove oldest sessions if we exceed max_history limit."""
        sessions = self.get_chat_history()
        if len(sessions) > self.max_history:
            # Delete oldest sessions
            for session in sessions[self.max_history:]:
                self.delete_chat_session(session["session_id"])


# Global instance
chat_history_manager = ChatHistoryManager()
