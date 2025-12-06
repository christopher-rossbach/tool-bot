"""Anki-Connect client for creating flashcards."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class AnkiConnectClient:
    """Client for interacting with Anki-Connect."""
    
    def __init__(self, url: str = "http://localhost:8765"):
        self.url = url
        self.version = 6
    
    async def _invoke(self, action: str, params: Optional[Dict] = None) -> Any:
        """Invoke an Anki-Connect action."""
        payload = {
            "action": action,
            "version": self.version,
        }
        if params:
            payload["params"] = params
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.url, json=payload, timeout=10.0)
                response.raise_for_status()
                result = response.json()
                
                if result.get("error"):
                    raise RuntimeError(f"Anki-Connect error: {result['error']}")
                
                return result.get("result")
            except Exception as e:
                logger.error(f"Anki-Connect request failed: {e}")
                raise
    
    async def create_deck(self, deck_name: str) -> None:
        """Create a deck if it doesn't exist."""
        try:
            await self._invoke("createDeck", {"deck": deck_name})
            logger.info(f"Ensured deck exists: {deck_name}")
        except Exception as e:
            logger.warning(f"Failed to create deck {deck_name}: {e}")
    
    async def add_note(
        self,
        deck_name: str,
        model_name: str,
        fields: Dict[str, str],
        tags: List[str] = None,
    ) -> int:
        """
        Add a note to Anki.
        
        Returns:
            Note ID
        """
        # Ensure deck exists
        await self.create_deck(deck_name)
        
        params = {
            "note": {
                "deckName": deck_name,
                "modelName": model_name,
                "fields": fields,
                "tags": tags or [],
                "options": {
                    "allowDuplicate": False,
                    "duplicateScope": "deck",
                }
            }
        }
        
        note_id = await self._invoke("addNote", params)
        logger.info(f"Created note {note_id} in deck {deck_name}")
        return note_id
    
    async def add_basic_card(
        self,
        front: str,
        back: str,
        deck: str = "Default",
        tags: List[str] = None,
    ) -> int:
        """Add a basic flashcard."""
        # Ensure deck is under Active::Bot hierarchy
        if not deck.startswith("Active::Bot"):
            deck = f"Active::Bot::{deck}" if deck != "Default" else "Active::Bot"
        return await self.add_note(
            deck_name=deck,
            model_name="Basic",
            fields={"Front": front, "Back": back, "Source": "tool-bot"},
            tags=tags or [],
        )
    
    async def add_basic_reversed_card(
        self,
        front: str,
        back: str,
        deck: str = "Default",
        tags: List[str] = None,
    ) -> int:
        """Add a basic (and reversed) flashcard."""
        # Ensure deck is under Active::Bot hierarchy
        if not deck.startswith("Active::Bot"):
            deck = f"Active::Bot::{deck}" if deck != "Default" else "Active::Bot"
        return await self.add_note(
            deck_name=deck,
            model_name="Basic (and reversed card)",
            fields={"Front": front, "Back": back, "Source": "tool-bot"},
            tags=tags or [],
        )
    
    async def add_cloze_card(
        self,
        text: str,
        deck: str = "Default",
        tags: List[str] = None,
    ) -> int:
        """Add a cloze deletion card."""
        # Ensure deck is under Active::Bot hierarchy
        if not deck.startswith("Active::Bot"):
            deck = f"Active::Bot::{deck}" if deck != "Default" else "Active::Bot"
        return await self.add_note(
            deck_name=deck,
            model_name="Cloze",
            fields={"Text": text, "Back Extra": "", "Source": "tool-bot"},
            tags=tags or [],
        )
    
    async def find_notes(self, query: str) -> List[int]:
        """Find notes matching a query."""
        return await self._invoke("findNotes", {"query": query})
