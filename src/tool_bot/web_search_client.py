"""Web search client using DuckDuckGo."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class WebSearchClient:
    """Client for performing web searches using DuckDuckGo."""

    def __init__(self):
        pass

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
        """
        try:
            from duckduckgo_search import DDGS

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
            raise Exception(f"Failed to perform web search: {str(e)}")
