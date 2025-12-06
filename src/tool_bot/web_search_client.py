"""Web search client using DuckDuckGo."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


class WebSearchClient:
    """Client for performing web searches using DuckDuckGo."""

    def __init__(self):
        self.timeout = 10.0

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search the web using DuckDuckGo.

        Args:
            query: Search query string
            max_results: Maximum number of results to return (1-10)

        Returns:
            List of search results with title, body, and href

        Raises:
            RuntimeError: If the search operation fails
        """
        try:
            with DDGS() as ddgs:
                results = ddgs.text(keywords=query, max_results=max_results)

                formatted_results = []
                for result in results:
                    formatted_results.append(
                        {
                            "title": result.get("title", ""),
                            "body": result.get("body", ""),
                            "href": result.get("href", ""),
                        }
                    )

                logger.info(
                    f"Web search for '{query}' returned {len(formatted_results)} results"
                )
                return formatted_results

        except Exception as e:
            logger.error(f"Web search failed: {e}")
            raise RuntimeError(f"Failed to perform web search: {str(e)}") from e

    async def fetch_webpage_content(self, url: str) -> str:
        """
        Fetch content from a webpage.

        Args:
            url: URL of the webpage to fetch

        Returns:
            Text content of the webpage (limited to first 10000 characters)

        Raises:
            RuntimeError: If fetching fails
        """
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    raise RuntimeError(f"Unsupported content type: {content_type}")

                text_content = response.text[:10000]

                logger.info(f"Fetched {len(text_content)} characters from {url}")
                return text_content

        except Exception as e:
            logger.error(f"Failed to fetch webpage {url}: {e}")
            raise RuntimeError(f"Failed to fetch webpage: {str(e)}") from e
