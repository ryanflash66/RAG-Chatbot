#!/usr/bin/env python3
"""
Test script to debug chat history functionality
"""

def test_config():
    """Test config functions"""
    try:
        from config import get_chat_history_enabled, get_max_chat_history, get_chat_storage_dir
        print("✅ Config imports successful")
        print(f"Chat history enabled: {get_chat_history_enabled()}")
        print(f"Max history: {get_max_chat_history()}")
        print(f"Storage dir: {get_chat_storage_dir()}")
        return True
    except Exception as e:
        print(f"❌ Config error: {e}")
        return False

def test_chat_history_manager():
    """Test chat history manager"""
    try:
        from chat_history import chat_history_manager
        print("✅ Chat history manager imported")
        print(f"Storage directory: {chat_history_manager.storage_dir}")
        print(f"Max history: {chat_history_manager.max_history}")
        
        # Test basic functionality
        sessions = chat_history_manager.get_chat_history()
        print(f"Current sessions: {len(sessions)}")
        return True
    except Exception as e:
        print(f"❌ Chat history manager error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_app_imports():
    """Test app imports"""
    try:
        import uuid
        from datetime import datetime
        print("✅ Standard library imports successful")
        
        # Test our modules
        from config import init_env, get_chat_history_enabled
        from index_utils import print_supported_file_types
        from chat_history import chat_history_manager
        
        print("✅ All app imports successful")
        return True
    except Exception as e:
        print(f"❌ App import error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Testing Chat History Implementation")
    print("=" * 50)
    
    tests = [
        ("Config Functions", test_config),
        ("Chat History Manager", test_chat_history_manager),
        ("App Imports", test_app_imports)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n🔍 Testing {test_name}:")
        result = test_func()
        results.append(result)
        print(f"{'✅' if result else '❌'} {test_name}: {'PASSED' if result else 'FAILED'}")
    
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if all(results):
        print("🎉 All tests passed! Chat history implementation looks good.")
    else:
        print("⚠️ Some tests failed. Check the errors above.")
