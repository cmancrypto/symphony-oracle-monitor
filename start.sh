#!/bin/bash

# Symphony Oracle Monitor Bot - Quick Start Script

echo "🔍 Symphony Oracle Monitor Bot Setup"
echo "===================================="

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Creating from template..."
    cp env.example .env
    echo "✅ Created .env file from template"
    echo ""
    echo "❗ IMPORTANT: Please edit .env file with your Discord bot token and channel ID"
    echo "   DISCORD_BOT_TOKEN=your_discord_bot_token_here"
    echo "   DISCORD_CHANNEL_ID=your_discord_channel_id_here"
    echo ""
    echo "📖 See README.md for detailed setup instructions"
    exit 1
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

echo "🐳 Starting Symphony Oracle Monitor Bot with Docker Compose..."
echo ""

# Build and start
docker-compose up -d

echo "✅ Bot started successfully!"
echo ""
echo "📋 Useful commands:"
echo "   View logs:    docker-compose logs -f"
echo "   Stop bot:     docker-compose down"
echo "   Restart bot:  docker-compose restart"
echo ""
echo "🔍 The bot will start monitoring validators and send reports every 5 minutes."
echo "📱 Check your Discord channel for the first report!" 