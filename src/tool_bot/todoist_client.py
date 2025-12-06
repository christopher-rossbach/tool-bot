"""Todoist API client for creating todos."""
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)


class TodoistClient:
    """Client for interacting with Todoist API."""
    
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://api.todoist.com/rest/v2"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    
    async def create_task(
        self,
        content: str,
        due_string: Optional[str] = None,
        priority: int = 1,
        labels: List[str] = None,
        project_id: Optional[str] = None,
    ) -> dict:
        """
        Create a task in Todoist.
        
        Returns:
            Task data
        """
        payload = {
            "content": content,
            "priority": priority,
        }
        
        if due_string:
            payload["due_string"] = due_string
        
        if labels:
            payload["labels"] = labels
        
        if project_id:
            payload["project_id"] = project_id
        
        # Add idempotency header
        request_id = str(uuid4())
        headers = {**self.headers, "X-Request-Id": request_id}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/tasks",
                    json=payload,
                    headers=headers,
                    timeout=10.0,
                )
                response.raise_for_status()
                task_data = response.json()
                logger.info(f"Created task: {task_data['id']} - {content}")
                return task_data
            except Exception as e:
                logger.error(f"Failed to create task: {e}")
                raise
    
    async def get_projects(self) -> List[dict]:
        """Get all projects."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/projects",
                    headers=self.headers,
                    timeout=10.0,
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.error(f"Failed to get projects: {e}")
                raise
    
    async def create_project(self, name: str) -> dict:
        """Create a project."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/projects",
                    json={"name": name},
                    headers=self.headers,
                    timeout=10.0,
                )
                response.raise_for_status()
                project_data = response.json()
                logger.info(f"Created project: {project_data['id']} - {name}")
                return project_data
            except Exception as e:
                logger.error(f"Failed to create project: {e}")
                raise
    
    async def get_or_create_project(self, name: str) -> str:
        """Get project ID by name, create if doesn't exist."""
        projects = await self.get_projects()
        
        for project in projects:
            if project["name"] == name:
                return project["id"]
        
        # Create if not found
        project = await self.create_project(name)
        return project["id"]
