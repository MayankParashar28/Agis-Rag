import os
from typing import List, Dict, Any
from fastapi import HTTPException
from app.core.config import settings
from app.core.logging import logger

class DocumentParser:
    def __init__(self):
        self.api_key = settings.LLAMAPARSE_API_KEY
        if self.api_key:
            logger.info("LlamaParse API Key found. Using LlamaParse for document parsing.")
            from llama_parse import LlamaParse
            # Initialize LlamaParse
            self.parser = LlamaParse(
                api_key=self.api_key,
                result_type="markdown",  # markdown preserves formatting, tables, etc.
                num_workers=4,
                verbose=True,
                language="en"
            )
        else:
            logger.warning("LlamaParse API Key not found. Falling back to local/standard parsers.")
            self.parser = None

    async def parse_file(self, file_path: str, filename: str) -> List[Dict[str, Any]]:
        """
        Parses a file and returns a list of dictionaries with content and metadata (e.g. page numbers).
        """
        ext = os.path.splitext(filename)[1].lower()
        
        # If LlamaParse is enabled, use it for PDFs and Word docs
        if self.parser and ext in [".pdf", ".docx"]:
            try:
                logger.info(f"Parsing {filename} with LlamaParse...")
                # LlamaParse parse_documents is synchronous/blocking, run it in a thread if needed
                # For simplicity, we call load_data
                documents = self.parser.load_data(file_path)
                
                parsed_pages = []
                for idx, doc in enumerate(documents):
                    # LlamaParse documents typically contain page information in metadata
                    page_num = doc.metadata.get("page_number", idx + 1)
                    parsed_pages.append({
                        "content": doc.text,
                        "page_number": int(page_num),
                        "metadata": {
                            "filename": filename,
                            "page": int(page_num),
                            "source": filename
                        }
                    })
                return parsed_pages
            except Exception as e:
                logger.error(f"LlamaParse error: {str(e)}. Falling back to local parsing.")
        
        # Local parsing fallback
        return await self._local_parse(file_path, filename, ext)

    async def _local_parse(self, file_path: str, filename: str, ext: str) -> List[Dict[str, Any]]:
        logger.info(f"Locally parsing {filename} with extension {ext}...")
        parsed_pages = []

        if ext == ".txt":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            parsed_pages.append({
                "content": content,
                "page_number": 1,
                "metadata": {"filename": filename, "page": 1, "source": filename}
            })
            
        elif ext == ".csv":
            import csv
            content_lines = []
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                for row in reader:
                    content_lines.append(", ".join(row))
            content = "\n".join(content_lines)
            parsed_pages.append({
                "content": content,
                "page_number": 1,
                "metadata": {"filename": filename, "page": 1, "source": filename}
            })
            
        elif ext == ".pdf":
            try:
                # Use local pdfreader fallback. In python-dependencies we have llama-index which includes fsspec etc.
                # Let's try PyPDF (which is usually bundled or can be imported easily)
                import pypdf
                reader = pypdf.PdfReader(file_path)
                for idx, page in enumerate(reader.pages):
                    text = page.extract_text()
                    parsed_pages.append({
                        "content": text,
                        "page_number": idx + 1,
                        "metadata": {"filename": filename, "page": idx + 1, "source": filename}
                    })
            except ImportError:
                # If pypdf is missing, write a basic placeholder or throw error
                logger.error("pypdf library not found. Please install it or use LlamaParse.")
                raise HTTPException(status_code=500, detail="Local PDF parser dependencies missing.")
            except Exception as e:
                logger.error(f"Failed local PDF parse: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Failed to parse PDF: {str(e)}")
                
        elif ext == ".docx":
            try:
                import docx
                doc = docx.Document(file_path)
                fullText = []
                for para in doc.paragraphs:
                    fullText.append(para.text)
                content = '\n'.join(fullText)
                parsed_pages.append({
                    "content": content,
                    "page_number": 1,
                    "metadata": {"filename": filename, "page": 1, "source": filename}
                })
            except ImportError:
                logger.error("python-docx library not found. Please install it or use LlamaParse.")
                raise HTTPException(status_code=500, detail="Local DOCX parser dependencies missing.")
            except Exception as e:
                logger.error(f"Failed local DOCX parse: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Failed to parse DOCX: {str(e)}")
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

        return parsed_pages

document_parser = DocumentParser()
