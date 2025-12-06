#!/usr/bin/env python3
"""Generate a Matrix access token from credentials in the config file.

This script logs into Matrix using the username and password from the config file,
retrieves an access token, and optionally updates the config file with it.
"""
import asyncio
import json
import sys
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nio import AsyncClient, LoginResponse
from tool_bot.config import Config


async def generate_token(config: Config, update_config: bool = False) -> str:
    """Generate a Matrix access token using credentials from config.
    
    Args:
        config: Configuration object containing Matrix credentials
        update_config: If True, update the config file with the new token
        
    Returns:
        The generated access token
        
    Raises:
        RuntimeError: If login fails or credentials are missing
    """
    if not config.matrix_user:
        raise RuntimeError("matrix_user is required in config")
    
    if not config.matrix_password:
        raise RuntimeError("matrix_password is required in config")
    
    print(f"Connecting to {config.matrix_homeserver}...")
    client = AsyncClient(
        homeserver=config.matrix_homeserver,
        user=config.matrix_user,
    )
    
    try:
        print(f"Logging in as {config.matrix_user}...")
        response = await client.login(config.matrix_password)
        
        if isinstance(response, LoginResponse):
            access_token = response.access_token
            device_id = response.device_id
            user_id = response.user_id
            
            print(f"\n✓ Login successful!")
            print(f"  User ID: {user_id}")
            print(f"  Device ID: {device_id}")
            print(f"  Access Token: {access_token}")
            
            if update_config:
                await update_config_file(access_token)
            
            return access_token
        else:
            raise RuntimeError(f"Login failed: {response}")
    
    finally:
        await client.close()


async def update_config_file(access_token: str) -> None:
    """Update the config file with the new access token.
    
    Args:
        access_token: The access token to save
    """
    import os
    config_path = os.environ.get("CONFIG_PATH", "config/config.json")
    config_file = Path(config_path)
    
    if not config_file.exists():
        print(f"\n⚠ Config file not found at {config_path}")
        return
    
    try:
        with open(config_file, "r") as f:
            data = json.load(f)
        
        data["matrix_access_token"] = access_token
        
        with open(config_file, "w") as f:
            json.dump(data, f, indent=2)
        
        print(f"\n✓ Updated config file: {config_path}")
        print("  Set matrix_access_token to the new token")
    except Exception as e:
        print(f"\n✗ Failed to update config file: {e}")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate a Matrix access token from config credentials"
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update the config file with the generated token",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config file (default: from CONFIG_PATH env or config/config.json)",
    )
    
    args = parser.parse_args()
    
    # Set config path if provided
    if args.config:
        import os
        os.environ["CONFIG_PATH"] = args.config
    
    try:
        # Load config
        config = Config.load()
        
        # Generate token
        token = asyncio.run(generate_token(config, update_config=args.update))
        
        if not args.update:
            print("\nTo use this token, either:")
            print("  1. Run this script with --update to automatically update config.json")
            print("  2. Manually set 'matrix_access_token' in your config file")
        
        return 0
    
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
