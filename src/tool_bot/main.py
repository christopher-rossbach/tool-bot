import asyncio
import logging

from tool_bot.config import Config
from tool_bot.matrix_client import MatrixBot


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    cfg = Config.load()
    logging.info("Starting Matrix Tool Bot")
    logging.info("Homeserver: %s", cfg.matrix_homeserver)
    
    bot = MatrixBot(cfg)
    try:
        await bot.start()
    finally:
        await bot.stop()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logging.info("Shutting down...")
        pass


if __name__ == "__main__":
    main()
