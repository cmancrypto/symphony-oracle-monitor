# Symphony Oracle Validator Monitor Discord Bot

A Discord bot that monitors Symphony blockchain validators for oracle miss counters and reports changes every 5 minutes.

## Features

- 🔍 **Validator Monitoring**: Tracks all bonded validators on Symphony blockchain
- 📊 **Miss Counter Tracking**: Monitors oracle miss counters for each validator
- 🚨 **Change Detection**: Compares miss counts every 5 minutes and reports changes
- 💬 **Discord Integration**: Sends formatted reports to Discord channels
- 🐳 **Docker Support**: Easy deployment with Docker and Docker Compose
- ⚡ **Async Operations**: Efficient async HTTP requests and Discord integration

## How It Works

1. **Fetches Validators**: Queries `/cosmos/staking/v1beta1/validators?status=BOND_STATUS_BONDED` to get all bonded validators
2. **Tracks Miss Counters**: For each validator, queries `/symphony/oracle/v1beta1/validators/{validator_addr}/miss`
3. **Compares Data**: Every 5 minutes, compares current miss counts with previous ones
4. **Reports Changes**: Sends Discord messages showing which validators had increased misses and which remained stable

## Setup Instructions

### Prerequisites

- Docker and Docker Compose installed
- A Discord application and bot token
- Access to a Discord server where you can add the bot

### 1. Create Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to the "Bot" section
4. Click "Add Bot"
5. Copy the bot token (you'll need this later)
6. Under "Privileged Gateway Intents", enable:
   - Message Content Intent (if you plan to add commands later)

### 2. Add Bot to Discord Server

1. In the Discord Developer Portal, go to "OAuth2" > "URL Generator"
2. Select scopes: `bot`
3. Select bot permissions: `Send Messages`, `Embed Links`
4. Copy the generated URL and open it in your browser
5. Select your Discord server and authorize the bot

### 3. Get Discord Channel ID

1. In Discord, enable Developer Mode (User Settings > Advanced > Developer Mode)
2. Right-click on the channel where you want reports
3. Click "Copy ID"

### 4. Configure Environment

1. Copy the example environment file:
   ```bash
   cp env.example .env
   ```

2. Edit `.env` with your values:
   ```env
   DISCORD_BOT_TOKEN=your_discord_bot_token_here
   DISCORD_CHANNEL_ID=your_discord_channel_id_here
   SYMPHONY_API_BASE=https://rest.cosmos.directory/symphony
   MONITORING_INTERVAL=300
   ```

### 5. Run with Docker Compose

```bash
# Build and start the bot
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the bot
docker-compose down
```

### Alternative: Run with Docker

```bash
# Build the image
docker build -t symphony-oracle-monitor .

# Run the container
docker run -d \
  --name symphony-oracle-monitor \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  symphony-oracle-monitor

# View logs
docker logs -f symphony-oracle-monitor
```

### Alternative: Run with Python

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables (or use .env file)
export DISCORD_BOT_TOKEN="your_token_here"
export DISCORD_CHANNEL_ID="your_channel_id_here"

# Run the bot
python bot.py
```

## Configuration Options

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `DISCORD_BOT_TOKEN` | Required | Your Discord bot token |
| `DISCORD_CHANNEL_ID` | Required | Discord channel ID for reports |
| `SYMPHONY_API_BASE` | `https://rest.cosmos.directory/symphony` | Symphony API base URL |
| `MONITORING_INTERVAL` | `300` | Monitoring interval in seconds (5 minutes) |

## Sample Discord Report

The bot sends formatted Discord embeds that look like this:

```
🔍 Symphony Oracle Validator Monitor Report

❌ Validators with Increased Misses
• ⚛ Chiter in Cosmos
  Misses: 87477 → 87480 (+3)
• Validator Name 2
  Misses: 1234 → 1237 (+3)

✅ Stable Validators
42 validators with no new misses

📊 Summary
Total Validators: 45
Monitored: 45
```

## API Endpoints Used

- **Validators**: `GET /cosmos/staking/v1beta1/validators?status=BOND_STATUS_BONDED`
- **Miss Counter**: `GET /symphony/oracle/v1beta1/validators/{validator_addr}/miss`

## Error Handling

- API failures are logged and retried
- Network timeouts are handled gracefully
- Bot automatically reconnects to Discord if connection is lost
- Invalid responses are logged but don't stop monitoring

## Monitoring and Logs

The bot provides detailed logging for:
- Validator data updates
- API request failures
- Discord connection status
- Report sending status

View logs with:
```bash
docker-compose logs -f symphony-oracle-monitor
```

## Troubleshooting

### Bot Not Responding
- Check that the bot token is correct
- Verify the bot has permissions in the Discord channel
- Check Docker logs for error messages

### No Reports Being Sent
- Verify the Discord channel ID is correct
- Check that the bot has "Send Messages" and "Embed Links" permissions
- Ensure the Symphony API is accessible

### API Errors
- Check if the Symphony API endpoints are accessible
- Verify the API base URL is correct
- Look for rate limiting in the logs

## Development

To modify the bot:

1. Edit `bot.py` for functionality changes
2. Update `requirements.txt` for new dependencies
3. Rebuild the Docker image: `docker-compose build`
4. Restart: `docker-compose down && docker-compose up -d`

## License

This project is open source and available under the MIT License. 