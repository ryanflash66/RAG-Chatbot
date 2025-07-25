#!/usr/bin/env python3
"""
Test script to verify chat history authentication setup.
"""

import os
from pathlib import Path

def test_authentication_setup():
    """Test that authentication is properly configured."""
    print("🧪 Testing Authentication Setup")
    print("=" * 40)
    
    # Load environment variables manually
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        os.environ[key] = value
    
    # Check if CHAINLIT_AUTH_SECRET is set
    auth_secret = os.getenv("CHAINLIT_AUTH_SECRET")
    if auth_secret:
        print(f"✅ CHAINLIT_AUTH_SECRET is set (length: {len(auth_secret)})")
    else:
        print("❌ CHAINLIT_AUTH_SECRET is missing!")
        return False
    
    # Check if .env file exists
    env_file = Path(".env")
    if env_file.exists():
        print("✅ .env file exists")
    else:
        print("❌ .env file missing!")
        return False
    
    # Check if chat_history directory exists
    chat_dir = Path("./chat_history")
    if chat_dir.exists():
        print("✅ Chat history directory exists")
        session_count = len(list(chat_dir.glob("*.json")))
        print(f"📁 Found {session_count} saved chat sessions")
    else:
        print("⚠️  Chat history directory will be created on first use")
    
    # Check config file
    config_file = Path(".chainlit/config.toml")
    if config_file.exists():
        with open(config_file, 'r') as f:
            content = f.read()
            if "[features.chat_history]" in content and "enabled = true" in content:
                print("✅ Chainlit config has chat history enabled")
            else:
                print("⚠️  Chat history may not be enabled in config")
    else:
        print("❌ Chainlit config file missing!")
    
    # Test imports (optional since chainlit might not be in current env)
    try:
        from chat_history import chat_history_manager
        print("✅ Chat history manager imports successfully")
    except ImportError as e:
        print(f"⚠️  Import warning (chainlit env): {e}")
        print("   This is normal if not running in the chainlit environment")
    
    print("\n🎯 Authentication Setup Summary:")
    print("- Use browser to go to: http://localhost:8000")
    print("- Login with: admin / password")
    print("- Chat history sidebar should appear after login")
    print("- Start chatting to test session saving!")
    
    return True

if __name__ == "__main__":
    success = test_authentication_setup()
    if success:
        print("\n🎉 Authentication setup looks good!")
        print("🚀 Start the app with: chainlit run app.py --port 8000")
    else:
        print("\n❌ Some issues found - check the setup!")
        exit(1)
