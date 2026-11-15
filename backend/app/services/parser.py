import os
import asyncio
from typing import List, Dict, Any
from app.services.extractors import SUPPORTED_EXTS, ParseError, extract, sniff_problem
from app.core.config import settings
from app.core.logging import logger

class DocumentParser:
    def __init__(self):
        self.api_key = settings.LLAMAPARSE_API_KEY
        if self.api_key:
            logger.info("LlamaParse API Key found. Using LlamaParse for document parsing.")
        else:
            logger.warning("LlamaParse API Key not found. Falling back to local/standard parsers.")

    def get_parser(self):
        if not self.api_key:
            return None
        from llama_parse import LlamaParse
        # Create a fresh parser instance to ensure it binds to the current event loop in worker processes
        return LlamaParse(
            api_key=self.api_key,
            result_type="markdown",  # markdown preserves formatting, tables, etc.
            num_workers=4,
            verbose=True,
            language="en"
        )

    # LlamaParse reads layout (multi-column pages, borderless tables) better
    # than the local readers for these formats. Spreadsheets, CSV and text
    # are read locally either way: that is exact and costs no quota.
    LLAMAPARSE_EXTS = {".pdf", ".docx", ".pptx"}

    async def parse_file(self, file_path: str, filename: str) -> List[Dict[str, Any]]:
        """Read a file into pages: [{"content", "page_number", "metadata"}].

        Raises ParseError (a message meant for the user) when the file cannot
        be read or contains no text.
        """
        ext = os.path.splitext(filename)[1].lower()
        problem = sniff_problem(file_path, ext) if ext in SUPPORTED_EXTS else None
        if problem:
            raise ParseError(problem)

        parser = self.get_parser() if ext in self.LLAMAPARSE_EXTS else None
        if parser:
            try:
                logger.info(f"Parsing {filename} with LlamaParse...")
                documents = await asyncio.wait_for(asyncio.to_thread(parser.load_data, file_path),
                                                   timeout=settings.PARSE_TIMEOUT_SECONDS)
                pages = []
                for idx, doc in enumerate(documents or []):
                    page_num = int(doc.metadata.get("page_number", idx + 1))
                    if (doc.text or "").strip():
                        pages.append({"content": doc.text, "page_number": page_num,
                                      "metadata": {"filename": filename, "page": page_num, "source": filename,
                                                   "parser": "llamaparse"}})
                if pages:
                    return pages
                logger.warning(f"LlamaParse returned no text for {filename}; reading it locally.")
            except Exception as e:
                logger.error(f"LlamaParse error for {filename}: {e}. Reading it locally.")

        return await self._local_parse(file_path, filename, ext)

    async def _local_parse(self, file_path: str, filename: str, ext: str) -> List[Dict[str, Any]]:
        logger.info(f"Locally parsing {filename} ({ext})...")
        try:
            # Off the event loop: big PDFs and spreadsheets take seconds of CPU,
            # and in in-process mode the loop is also serving requests.
            pages = await asyncio.wait_for(asyncio.to_thread(extract, file_path, filename, ext),
                                           timeout=settings.PARSE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            raise ParseError(f"Reading this file took longer than {settings.PARSE_TIMEOUT_SECONDS // 60} minutes. "
                             "Try splitting it into smaller files.")
        except ParseError:
            raise
        except MemoryError:
            raise ParseError("This file is too large to read on this server. Try splitting it into smaller files.")
        except Exception as e:
            logger.exception(f"Failed to parse {filename}")
            raise ParseError(f"This file could not be read ({type(e).__name__}: {str(e)[:200]}).")
        tables = sum(p["content"].count("\n|---") for p in pages)
        logger.info(f"Parsed {filename}: {len(pages)} page(s), {tables} table(s).")
        return pages

document_parser = DocumentParser()
