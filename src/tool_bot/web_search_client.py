"""Web search client using DuckDuckGo."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx
from ddgs import DDGS

logger = logging.getLogger(__name__)


class WebSearchClient:
    """Client for performing web searches using DuckDuckGo."""

    MAX_CONTENT_LENGTH = 10000
    MAX_EXCERPT_LENGTH = 2000

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

                content_type = response.headers.get("content-type", "").lower()
                if not (
                    content_type.startswith("text/html")
                    or content_type.startswith("text/plain")
                ):
                    raise RuntimeError(f"Unsupported content type: {content_type}")

                text_content = response.text[: self.MAX_CONTENT_LENGTH]

                logger.info(f"Fetched {len(text_content)} characters from {url}")
                return text_content

        except Exception as e:
            logger.error(f"Failed to fetch webpage {url}: {e}")
            raise RuntimeError(f"Failed to fetch webpage: {str(e)}") from e

    async def execute_searches(
        self, search_queries: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Execute multiple web searches and fetch webpage content.

        Args:
            search_queries: List of dicts with 'query' and 'max_results' keys

        Returns:
            List of search results with status and webpages/error messages
        """
        all_search_results = []

        for search_query in search_queries:
            query = search_query.get("query", "")
            max_results = search_query.get("max_results", 3)

            try:
                # Perform web search
                results = await self.search(query=query, max_results=max_results)

                if not results:
                    all_search_results.append(
                        {
                            "query": query,
                            "status": "no_results",
                            "message": f"No search results found for: {query}",
                        }
                    )
                    continue

                # Fetch webpage content for top results
                webpage_contents = []
                for result in results[:max_results]:
                    try:
                        content_text = await self.fetch_webpage_content(result["href"])
                        webpage_contents.append(
                            {
                                "title": result["title"],
                                "url": result["href"],
                                "snippet": result["body"],
                                "content": content_text,
                            }
                        )
                        logger.info(f"Fetched content from {result['href'][:100]}")
                    except Exception as e:
                        logger.warning(
                            f"Failed to fetch content from {result['href']}: {e}"
                        )
                        continue

                if not webpage_contents:
                    all_search_results.append(
                        {
                            "query": query,
                            "status": "fetch_failed",
                            "message": f"Found search results but could not fetch webpage content.",
                        }
                    )
                else:
                    all_search_results.append(
                        {
                            "query": query,
                            "status": "success",
                            "webpages": webpage_contents,
                        }
                    )

            except Exception as e:
                logger.error(f"Web search processing failed for '{query}': {e}")
                all_search_results.append(
                    {
                        "query": query,
                        "status": "error",
                        "message": f"❌ Search failed: {str(e)}",
                    }
                )

        return all_search_results

    def build_extraction_prompt(
        self, all_search_results: List[Dict[str, Any]]
    ) -> tuple[str, Dict[int, Dict[str, str]]]:
        """
        Build LLM extraction prompt from search results.

        Args:
            all_search_results: List of search results from execute_searches

        Returns:
            Tuple of (extraction_prompt, source_map)
        """
        num_queries = len(
            [r for r in all_search_results if r.get("status") == "success"]
        )

        if num_queries == 1:
            extraction_prompt = (
                "The user asked a question that required a web search:\n\n"
            )
        else:
            extraction_prompt = f"The user asked {num_queries} questions that required web searches:\n\n"

        source_counter = 1
        source_map = {}  # Maps source number to page info dict

        for search_result in all_search_results:
            if search_result.get("status") == "success":
                query = search_result["query"]
                webpages = search_result["webpages"]

                extraction_prompt += f"**Query: {query}**\n"
                extraction_prompt += f"Found {len(webpages)} relevant webpages:\n\n"

                for page in webpages:
                    extraction_prompt += (
                        f"### Source {source_counter}: {page['title']}\n"
                    )
                    extraction_prompt += f"URL: {page['url']}\n"
                    extraction_prompt += f"Snippet: {page['snippet']}\n"

                    content_excerpt = page["content"][: self.MAX_EXCERPT_LENGTH]
                    ellipsis = (
                        "..." if len(page["content"]) > self.MAX_EXCERPT_LENGTH else ""
                    )
                    extraction_prompt += (
                        f"Content excerpt: {content_excerpt}{ellipsis}\n\n"
                    )

                    source_map[source_counter] = {
                        "title": page["title"],
                        "url": page["url"],
                    }
                    source_counter += 1

        if num_queries == 1:
            extraction_prompt += (
                "\nPlease extract and synthesize the most relevant information to answer the query. "
                "Cite your sources by mentioning the source number (e.g., 'According to Source 1...')."
            )
        else:
            extraction_prompt += (
                "\nPlease extract and synthesize the most relevant information to answer each query. "
                "Be clear about which query each piece of information addresses. "
                "Cite your sources by mentioning the source number (e.g., 'According to Source 1...')."
            )

        return extraction_prompt, source_map

    def format_search_results(
        self, extracted_text: str, source_map: Dict[int, Dict[str, str]]
    ) -> str:
        """
        Format the final search results message.

        Args:
            extracted_text: LLM-extracted information
            source_map: Mapping of source numbers to page info

        Returns:
            Formatted message body
        """
        final_body = (
            f"📊 **Web Search Results**\n\n{extracted_text}\n\n---\n**Sources:**\n"
        )
        for source_num, page_info in source_map.items():
            final_body += f"{source_num}. [{page_info['title']}]({page_info['url']})\n"
        return final_body
