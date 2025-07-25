#!/usr/bin/env python3
"""
Test script to verify file type support in the RAG chatbot.
"""

from index_utils import get_supported_file_types, setup_file_extractors

def test_file_type_support():
    """Test that all declared file types have extractors."""
    print("🧪 Testing File Type Support")
    print("=" * 40)
    
    # Get our declared supported types
    supported_types = get_supported_file_types()
    all_extensions = []
    for category, extensions in supported_types.items():
        all_extensions.extend(extensions)
    
    # Get the actual extractors
    extractors = setup_file_extractors()
    
    print(f"📋 Declared supported extensions: {len(all_extensions)}")
    
    if extractors:
        print(f"🔧 Available extractors: {len(extractors)}")
        
        # Check coverage
        missing_extractors = []
        for ext in all_extensions:
            if ext not in extractors:
                missing_extractors.append(ext)
        
        if missing_extractors:
            print(f"⚠️  Missing extractors for: {missing_extractors}")
        else:
            print("✅ All declared file types have extractors!")
        
        # Show some examples
        print("\n📄 Example extractor mappings:")
        for ext in [".pdf", ".docx", ".json", ".log", ".py"]:
            if ext in extractors:
                extractor_name = extractors[ext].__class__.__name__
                print(f"   {ext} → {extractor_name}")
        
        return len(missing_extractors) == 0
    else:
        print("❌ No extractors found!")
        return False

if __name__ == "__main__":
    success = test_file_type_support()
    if success:
        print("\n🎉 All tests passed!")
    else:
        print("\n❌ Some tests failed!")
        exit(1)
