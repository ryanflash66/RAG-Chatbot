#!/usr/bin/env python3
"""
Minimal test for chat history - no external dependencies
"""

def test_minimal():
    """Test basic Python functionality"""
    import os
    import json
    from pathlib import Path
    from datetime import datetime
    
    print("✅ Basic imports working")
    
    # Test chat storage directory creation
    chat_dir = Path("./test_chat_history")
    chat_dir.mkdir(exist_ok=True)
    print(f"✅ Created test directory: {chat_dir}")
    
    # Test JSON operations
    test_data = {
        "session_id": "test-123",
        "title": "Test Chat",
        "timestamp": datetime.now().isoformat(),
        "messages": [
            {"type": "user_message", "content": "Hello", "timestamp": datetime.now().isoformat()}
        ]
    }
    
    test_file = chat_dir / "test_session.json"
    with open(test_file, 'w') as f:
        json.dump(test_data, f, indent=2)
    
    # Read it back
    with open(test_file, 'r') as f:
        loaded_data = json.load(f)
    
    print(f"✅ JSON operations working: {loaded_data['title']}")
    
    # Cleanup
    test_file.unlink()
    chat_dir.rmdir()
    print("✅ Cleanup completed")
    
    return True

if __name__ == "__main__":
    print("🔬 Minimal Chat History Test")
    print("=" * 30)
    
    try:
        result = test_minimal()
        if result:
            print("🎉 Basic functionality working!")
        else:
            print("❌ Basic test failed")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
