docker run -d \
  --name tool-bot \
  -v "./config/config.json:/app/config/config.json:ro" \
  -v "./cache:/app/cache" \
  --restart unless-stopped \
  tool-bot:latest