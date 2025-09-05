import discord
import asyncio
import aiohttp
import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from dotenv import load_dotenv
import logging
from pathlib import Path

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ValidatorMonitor:
    def __init__(self):
        self.bot_token = os.getenv('DISCORD_BOT_TOKEN')
        self.channel_id = int(os.getenv('DISCORD_CHANNEL_ID'))
        self.api_base = os.getenv('SYMPHONY_API_BASE', 'https://rest.cosmos.directory/symphony')
        self.monitoring_interval = int(os.getenv('MONITORING_INTERVAL', '300'))  # 5 minutes
        
        # Data persistence
        self.data_dir = Path('data')
        self.data_dir.mkdir(exist_ok=True)
        self.data_file = self.data_dir / 'validator_data.json'
        
        # Discord bot setup - use minimal intents to avoid privileged intent requirements
        intents = discord.Intents.none()
        intents.guilds = True  # Required to access guild channels
        self.bot = discord.Client(intents=intents)
        
        # Data storage
        self.validators_data: Dict[str, Dict] = {}
        self.previous_misses: Dict[str, int] = {}
        self.current_misses: Dict[str, int] = {}
        
        # Load persisted data
        self.load_data()
        
        # Setup bot events
        self.setup_bot_events()
    
    def setup_bot_events(self):
        @self.bot.event
        async def on_ready():
            logger.info(f'{self.bot.user} has connected to Discord!')
            # Start monitoring loop
            self.bot.loop.create_task(self.monitoring_loop())
    
    async def fetch_validators(self) -> List[Dict]:
        """Fetch bonded validators from Symphony API"""
        url = f"{self.api_base}/cosmos/staking/v1beta1/validators?status=BOND_STATUS_BONDED"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('validators', [])
                    else:
                        logger.error(f"Failed to fetch validators: {response.status}")
                        return []
            except Exception as e:
                logger.error(f"Error fetching validators: {e}")
                return []
    
    async def fetch_validator_misses(self, validator_addr: str) -> Optional[int]:
        """Fetch miss counter for a specific validator"""
        url = f"{self.api_base}/symphony/oracle/v1beta1/validators/{validator_addr}/miss"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return int(data.get('miss_counter', '0'))
                    else:
                        logger.warning(f"Failed to fetch misses for {validator_addr}: {response.status}")
                        return None
            except Exception as e:
                logger.error(f"Error fetching misses for {validator_addr}: {e}")
                return None
    
    async def update_validator_data(self):
        """Update validator data and miss counters"""
        logger.info("Updating validator data...")
        
        # Fetch current validators
        validators = await self.fetch_validators()
        
        if not validators:
            logger.warning("No validators fetched")
            return
        
        # Store previous misses
        self.previous_misses = self.current_misses.copy()
        self.current_misses = {}
        
        # Update validator data and fetch miss counters
        for validator in validators:
            operator_addr = validator.get('operator_address')
            moniker = validator.get('description', {}).get('moniker', 'Unknown')
            
            if operator_addr:
                # Store validator info
                self.validators_data[operator_addr] = {
                    'moniker': moniker,
                    'operator_address': operator_addr
                }
                
                # Fetch miss counter
                misses = await self.fetch_validator_misses(operator_addr)
                if misses is not None:
                    self.current_misses[operator_addr] = misses
                
                # Small delay to avoid overwhelming the API
                await asyncio.sleep(0.1)
        
        logger.info(f"Updated data for {len(self.current_misses)} validators")
        
        # Save data to disk
        self.save_data()
    
    async def analyze_and_report(self):
        """Analyze miss changes and send Discord report"""
        if not self.previous_misses:
            logger.info("No previous data to compare, skipping report")
            return
        
        increased_misses = []
        stable_validators = []
        
        for validator_addr, current_miss_count in self.current_misses.items():
            previous_miss_count = self.previous_misses.get(validator_addr, 0)
            validator_info = self.validators_data.get(validator_addr, {})
            moniker = validator_info.get('moniker', 'Unknown')
            
            if current_miss_count > previous_miss_count:
                miss_increase = current_miss_count - previous_miss_count
                increased_misses.append({
                    'moniker': moniker,
                    'operator_address': validator_addr,
                    'previous_misses': previous_miss_count,
                    'current_misses': current_miss_count,
                    'increase': miss_increase
                })
            else:
                stable_validators.append({
                    'moniker': moniker,
                    'operator_address': validator_addr,
                    'current_misses': current_miss_count
                })
        
        # Send Discord report
        await self.send_discord_report(increased_misses, stable_validators)
    
    async def send_discord_report(self, increased_misses: List[Dict], stable_validators: List[Dict]):
        """Send monitoring report to Discord"""
        try:
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                logger.error(f"Could not find Discord channel with ID: {self.channel_id}")
                return
            
            # Create embed for the report
            embed = discord.Embed(
                title="🔍 Symphony Oracle Validator Monitor Report",
                color=0x00ff00 if not increased_misses else 0xff6b6b,
                timestamp=datetime.utcnow()
            )
            
            # Add validators with increased misses
            if increased_misses:
                increased_text = ""
                for validator in increased_misses[:10]:  # Limit to avoid message length issues
                    increased_text += f"• **{validator['moniker']}**\n"
                    increased_text += f"  Misses: {validator['previous_misses']} → {validator['current_misses']} (+{validator['increase']})\n"
                
                embed.add_field(
                    name="❌ Validators with Increased Misses",
                    value=increased_text or "None",
                    inline=False
                )
            
            # Add stable validators (show count)
            stable_count = len(stable_validators)
            embed.add_field(
                name="✅ Stable Validators",
                value=f"{stable_count} validators with no new misses",
                inline=False
            )
            
            # Add summary
            total_validators = len(self.current_misses)
            embed.add_field(
                name="📊 Summary",
                value=f"Total Validators: {total_validators}\nMonitored: {len(increased_misses + stable_validators)}",
                inline=False
            )
            
            await channel.send(embed=embed)
            logger.info(f"Sent report: {len(increased_misses)} validators with increased misses, {stable_count} stable")
            
        except Exception as e:
            logger.error(f"Error sending Discord report: {e}")
    
    async def monitoring_loop(self):
        """Main monitoring loop"""
        logger.info(f"Starting monitoring loop (interval: {self.monitoring_interval} seconds)")
        
        # Initial data fetch
        await self.update_validator_data()
        
        while True:
            try:
                await asyncio.sleep(self.monitoring_interval)
                await self.update_validator_data()
                await self.analyze_and_report()
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying
    
    def save_data(self):
        """Save current data to disk"""
        try:
            data = {
                'validators_data': self.validators_data,
                'current_misses': self.current_misses,
                'timestamp': datetime.utcnow().isoformat()
            }
            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving data: {e}")
    
    def load_data(self):
        """Load data from disk"""
        try:
            if self.data_file.exists():
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                
                self.validators_data = data.get('validators_data', {})
                self.current_misses = data.get('current_misses', {})
                
                logger.info(f"Loaded data for {len(self.validators_data)} validators from disk")
            else:
                logger.info("No previous data found, starting fresh")
        except Exception as e:
            logger.error(f"Error loading data: {e}")
    
    def run(self):
        """Start the bot"""
        if not self.bot_token:
            logger.error("DISCORD_BOT_TOKEN not found in environment variables")
            return
        
        logger.info("Starting Symphony Oracle Monitor Bot...")
        self.bot.run(self.bot_token)

if __name__ == "__main__":
    monitor = ValidatorMonitor()
    monitor.run() 