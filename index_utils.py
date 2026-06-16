"""
Index utilities for RAG Chatbot
Handles loading and creating vector indexes from documents
"""
import os
from pathlib import Path
from llama_index.core import load_index_from_storage, VectorStoreIndex, SimpleDirectoryReader
from llama_index.core import StorageContext
from llama_index.readers.file import UnstructuredReader


def get_supported_file_types():
    """
    Get a list of supported file types with descriptions.
    
    Returns:
        dict: Dictionary mapping categories to supported file extensions
    """
    return {
        "Documents": [".pdf", ".docx", ".doc", ".txt", ".md", ".html", ".htm", ".rtf"],
        "Presentations": [".pptx", ".ppt"],
        "Spreadsheets": [".xlsx", ".xls", ".csv"],
        "Configuration": [".json", ".xml", ".yaml", ".yml", ".conf", ".config", ".ini"],
        "Scripts": [".ps1", ".sh", ".bat", ".cmd", ".py"],
        "Logs": [".log"],
        "Email": [".eml", ".msg"],
        "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff"],
        "OpenDocument": [".odt", ".ods", ".odp"]
    }


def print_supported_file_types():
    """Print a formatted list of supported file types."""
    supported = get_supported_file_types()
    print("\n📄 Supported File Types:")
    print("=" * 50)
    
    for category, extensions in supported.items():
        print(f"\n🔹 {category}:")
        # Group extensions in rows of 6 for better readability
        for i in range(0, len(extensions), 6):
            row = extensions[i:i+6]
            print(f"   {', '.join(row)}")
    
    print("\n💡 Tip: Place your files in the './data' directory")
    print("🔄 Restart the app after adding new files to rebuild the index\n")


class IndexLoadError(Exception):
    """Raised when index loading fails"""
    pass


class DocumentLoadError(Exception):
    """Raised when document loading fails"""
    pass


def setup_file_extractors():
    """
    Set up file extractors for different document types.
    Enhanced for IT documentation with comprehensive file type support.
    Returns a dictionary mapping file extensions to reader classes.
    """
    try:
        # Try to use UnstructuredReader if available
        return {
            # Core document formats
            ".pdf": UnstructuredReader(),      # Manuals, guides, procedures
            ".docx": UnstructuredReader(),     # Procedures, templates, reports
            ".doc": UnstructuredReader(),      # Legacy Word documents
            ".txt": UnstructuredReader(),      # Quick notes, logs, plain text
            ".md": UnstructuredReader(),       # Documentation, README files
            ".html": UnstructuredReader(),     # Web-based docs, exported articles
            ".htm": UnstructuredReader(),      # Legacy HTML files
            
            # Presentation formats
            ".pptx": UnstructuredReader(),     # Training materials, presentations
            ".ppt": UnstructuredReader(),      # Legacy PowerPoint files
            
            # Data and configuration formats
            ".csv": UnstructuredReader(),      # Asset lists, user inventories
            ".json": UnstructuredReader(),     # Config files, API responses
            ".xml": UnstructuredReader(),      # Configuration files, structured data
            ".yaml": UnstructuredReader(),     # Docker, Kubernetes configs
            ".yml": UnstructuredReader(),      # Alternative YAML extension
            
            # Log and system files
            ".log": UnstructuredReader(),      # System logs, application logs
            ".conf": UnstructuredReader(),     # Configuration files
            ".config": UnstructuredReader(),   # Configuration files
            ".ini": UnstructuredReader(),      # Windows-style config files
            
            # Script and code files (for procedure documentation)
            ".ps1": UnstructuredReader(),      # PowerShell scripts
            ".sh": UnstructuredReader(),       # Shell scripts
            ".bat": UnstructuredReader(),      # Batch files
            ".cmd": UnstructuredReader(),      # Command files
            ".py": UnstructuredReader(),       # Python scripts with documentation
            
            # Email and communication
            ".eml": UnstructuredReader(),      # Email files
            ".msg": UnstructuredReader(),      # Outlook message files
            
            # Image formats (for OCR of screenshots, diagrams)
            ".jpg": UnstructuredReader(),      # Screenshots, diagrams
            ".jpeg": UnstructuredReader(),     # JPEG images
            ".png": UnstructuredReader(),      # Screenshots, diagrams
            ".gif": UnstructuredReader(),      # Animated guides
            ".bmp": UnstructuredReader(),      # Bitmap images
            ".tiff": UnstructuredReader(),     # High-quality scans
            
            # Additional office formats
            ".xlsx": UnstructuredReader(),     # Excel spreadsheets
            ".xls": UnstructuredReader(),      # Legacy Excel files
            ".odt": UnstructuredReader(),      # OpenDocument text
            ".ods": UnstructuredReader(),      # OpenDocument spreadsheet
            ".odp": UnstructuredReader(),      # OpenDocument presentation
            ".rtf": UnstructuredReader(),      # Rich Text Format
        }
    except Exception as e:
        # Fall back to default extractors if UnstructuredReader fails
        print(f"Warning: UnstructuredReader not available ({e}), using default extractors")
        print("Supported formats will be limited to: .txt, .md, .pdf, .docx, .csv, .json")
        return None


def load_documents_from_directory(data_dir: str):
    """
    Load documents from the specified directory.
    
    Args:
        data_dir (str): Path to the directory containing documents
        
    Returns:
        list: List of loaded documents
        
    Raises:
        DocumentLoadError: If document loading fails
    """
    if not os.path.exists(data_dir):
        raise DocumentLoadError(f"Data directory not found: {data_dir}")
    
    try:
        file_extractors = setup_file_extractors()
        
        if file_extractors:
            # Use custom file extractors
            dir_reader = SimpleDirectoryReader(
                data_dir, 
                file_extractor=file_extractors
            )
        else:
            # Use default extractors
            dir_reader = SimpleDirectoryReader(data_dir)
        
        documents = dir_reader.load_data()
        
        if not documents:
            raise DocumentLoadError(f"No documents found in {data_dir}")
            
        print(f"✅ Loaded {len(documents)} documents from {data_dir}")
        return documents
        
    except Exception as e:
        raise DocumentLoadError(f"Failed to load documents from {data_dir}: {str(e)}")


def load_index_from_storage_safe(storage_dir: str):
    """
    Safely load index from storage with specific exception handling.
    
    Args:
        storage_dir (str): Path to the storage directory
        
    Returns:
        VectorStoreIndex: The loaded index
        
    Raises:
        IndexLoadError: If index loading fails
    """
    if not os.path.exists(storage_dir):
        raise IndexLoadError(f"Storage directory not found: {storage_dir}")
    
    try:
        storage_context = StorageContext.from_defaults(persist_dir=storage_dir)
        index = load_index_from_storage(storage_context)
        print(f"📚 Loaded existing index from {storage_dir}")
        return index
        
    except Exception as e:
        raise IndexLoadError(f"Failed to load index from {storage_dir}: {str(e)}")


def create_new_index(data_dir: str, storage_dir: str):
    """
    Create a new vector index from documents and persist it.
    
    Args:
        data_dir (str): Path to the directory containing documents
        storage_dir (str): Path to save the index storage
        
    Returns:
        VectorStoreIndex: The created index
        
    Raises:
        DocumentLoadError: If document loading fails
    """
    print(f"🔨 Creating new index from documents in {data_dir}...")
    
    documents = load_documents_from_directory(data_dir)
    
    # Create the index
    index = VectorStoreIndex.from_documents(documents)
    
    # Ensure storage directory exists
    Path(storage_dir).mkdir(parents=True, exist_ok=True)
    
    # Persist the index
    index.storage_context.persist(persist_dir=storage_dir)
    print(f"💾 Index created and saved to {storage_dir}")
    
    return index


def load_or_create_index(storage_dir: str, data_dir: str):
    """
    Load existing index or create a new one from documents.
    
    Args:
        storage_dir (str): Path to the storage directory
        data_dir (str): Path to the directory containing documents
        
    Returns:
        VectorStoreIndex: The loaded or created index
        
    Raises:
        DocumentLoadError: If document loading fails during index creation
    """
    try:
        # Try to load existing index
        return load_index_from_storage_safe(storage_dir)
        
    except IndexLoadError as e:
        print(f"Index loading failed: {e}")
        # Create new index if loading fails
        return create_new_index(data_dir, storage_dir)
