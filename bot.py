import discord
import asyncio
import aiohttp
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple
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
        self.low_balance_threshold = 1e6  # 1 million note tokens
        
        # Data persistence
        self.data_dir = Path('data')
        self.data_dir.mkdir(exist_ok=True)
        self.data_file = self.data_dir / 'validator_data.json'
        
        # Discord bot setup
        intents = discord.Intents.default()
        # Remove privileged intents that aren't needed for this bot
        intents.message_content = False
        intents.presences = False
        intents.members = False
        self.bot = discord.Client(intents=intents)
        
        # Data storage
        self.validators_data: Dict[str, Dict] = {}
        self.previous_misses: Dict[str, int] = {}
        self.current_misses: Dict[str, int] = {}
        self.feeder_addresses: Dict[str, str] = {}  # validator_addr -> feeder_addr
        self.feeder_balances: Dict[str, int] = {}  # feeder_addr -> balance
        self.exchange_rates: Dict[str, str] = {}  # denom -> rate
        self.validators_without_feeder: List[str] = []  # validator addresses without feeders
        
        # Load persisted data
        self.load_data()
        
        # Setup bot events
        self.setup_bot_events()
    
    def format_tokens_as_mld(self, tokens: int) -> str:
        """Format token amounts as MLD (millions) for display"""
        mld_amount = tokens / 1e6
        if mld_amount >= 1000:
            return f"{mld_amount:,.0f} MLD"
        elif mld_amount >= 100:
            return f"{mld_amount:,.1f} MLD"
        else:
            return f"{mld_amount:,.2f} MLD"
    
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
    
    async def fetch_validator_feeder(self, validator_addr: str) -> Optional[str]:
        """Fetch feeder address for a specific validator"""
        url = f"{self.api_base}/symphony/oracle/v1beta1/validators/{validator_addr}/feeder"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('feeder_addr')
                    else:
                        # Check if it's a "feeder not found" error for both 400 and 500 status codes
                        try:
                            error_data = await response.json()
                            error_message = error_data.get('message', '')
                            if "could not found feeder by validator" in error_message:
                                logger.info(f"No feeder found for validator {validator_addr}")
                                return "NO_FEEDER"
                        except:
                            # If we can't parse the JSON response, continue with the warning
                            pass
                        
                        logger.warning(f"Failed to fetch feeder for {validator_addr}: {response.status}")
                        return None
            except Exception as e:
                logger.error(f"Error fetching feeder for {validator_addr}: {e}")
                return None
    
    async def fetch_feeder_balance(self, feeder_addr: str) -> Optional[int]:
        """Fetch NOTE balance for a feeder address"""
        url = f"{self.api_base}/cosmos/bank/v1beta1/balances/{feeder_addr}"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        balances = data.get('balances', [])
                        
                        # Find NOTE balance
                        for balance in balances:
                            if balance.get('denom') == 'note':
                                return int(balance.get('amount', '0'))
                        
                        # If no NOTE balance found, return 0
                        return 0
                    else:
                        logger.warning(f"Failed to fetch balance for {feeder_addr}: {response.status}")
                        return None
            except Exception as e:
                logger.error(f"Error fetching balance for {feeder_addr}: {e}")
                return None
    
    async def fetch_exchange_rates(self) -> Dict[str, str]:
        """Fetch current exchange rates"""
        url = f"{self.api_base}/symphony/oracle/v1beta1/denoms/exchange_rates"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        rates = {}
                        for rate_data in data.get('exchange_rates', []):
                            denom = rate_data.get('denom')
                            amount = rate_data.get('amount')
                            if denom and amount:
                                rates[denom] = amount
                        return rates
                    else:
                        logger.warning(f"Failed to fetch exchange rates: {response.status}")
                        return {}
            except Exception as e:
                logger.error(f"Error fetching exchange rates: {e}")
                return {}
    
    async def update_validator_data(self):
        """Update validator data, miss counters, feeder addresses, and balances"""
        logger.info("Updating validator data...")
        
        # Fetch current validators
        validators = await self.fetch_validators()
        
        if not validators:
            logger.warning("No validators fetched")
            return
        
        # Store previous misses
        self.previous_misses = self.current_misses.copy()
        self.current_misses = {}
        self.feeder_addresses = {}
        self.feeder_balances = {}
        self.validators_without_feeder = []
        
        # Fetch exchange rates (once per update cycle)
        self.exchange_rates = await self.fetch_exchange_rates()
        
        # Update validator data and fetch miss counters, feeder addresses, and balances
        for validator in validators:
            operator_addr = validator.get('operator_address')
            moniker = validator.get('description', {}).get('moniker', 'Unknown')
            tokens = int(validator.get('tokens', '0'))  # Extract vote power tokens
            
            if operator_addr:
                # Store validator info including tokens
                self.validators_data[operator_addr] = {
                    'moniker': moniker,
                    'operator_address': operator_addr,
                    'tokens': tokens
                }
                
                # Fetch miss counter
                misses = await self.fetch_validator_misses(operator_addr)
                if misses is not None:
                    self.current_misses[operator_addr] = misses
                
                # Fetch feeder address
                feeder_addr = await self.fetch_validator_feeder(operator_addr)
                if feeder_addr == "NO_FEEDER":
                    self.validators_without_feeder.append(operator_addr)
                elif feeder_addr:
                    self.feeder_addresses[operator_addr] = feeder_addr
                    
                    # Fetch feeder balance
                    balance = await self.fetch_feeder_balance(feeder_addr)
                    if balance is not None:
                        self.feeder_balances[feeder_addr] = balance
                
                # Small delay to avoid overwhelming the API
                await asyncio.sleep(0.1)
        
        logger.info(f"Updated data for {len(self.current_misses)} validators, {len(self.feeder_addresses)} feeders, {len(self.validators_without_feeder)} without feeders")
        
        # Save data to disk
        self.save_data()
    
    def calculate_vote_power_stats(self, increased_misses: List[Dict], stable_validators: List[Dict]) -> Dict:
        """Calculate vote power statistics"""
        total_tokens = 0
        increased_misses_tokens = 0
        stable_tokens = 0
        no_feeder_tokens = 0
        
        # Calculate total tokens across all validators
        for validator_data in self.validators_data.values():
            total_tokens += validator_data.get('tokens', 0)
        
        # Calculate tokens for validators with increased misses
        for validator in increased_misses:
            validator_addr = validator['operator_address']
            validator_data = self.validators_data.get(validator_addr, {})
            increased_misses_tokens += validator_data.get('tokens', 0)
        
        # Calculate tokens for stable validators
        for validator in stable_validators:
            validator_addr = validator['operator_address']
            validator_data = self.validators_data.get(validator_addr, {})
            stable_tokens += validator_data.get('tokens', 0)
        
        # Calculate tokens for validators without feeders
        for validator_addr in self.validators_without_feeder:
            validator_data = self.validators_data.get(validator_addr, {})
            no_feeder_tokens += validator_data.get('tokens', 0)
        
        # Calculate percentages
        if total_tokens > 0:
            increased_misses_pct = (increased_misses_tokens / total_tokens) * 100
            stable_pct = (stable_tokens / total_tokens) * 100
            no_feeder_pct = (no_feeder_tokens / total_tokens) * 100
        else:
            increased_misses_pct = stable_pct = no_feeder_pct = 0
        
        return {
            'total_tokens': total_tokens,
            'increased_misses_tokens': increased_misses_tokens,
            'stable_tokens': stable_tokens,
            'no_feeder_tokens': no_feeder_tokens,
            'increased_misses_pct': increased_misses_pct,
            'stable_pct': stable_pct,
            'no_feeder_pct': no_feeder_pct
        }
    
    async def analyze_and_report(self):
        """Analyze miss changes and send Discord report"""
        if not self.previous_misses:
            logger.info("No previous data to compare, skipping report")
            return
        
        increased_misses = []
        stable_validators = []
        low_balance_validators = []
        validators_without_feeder = []
        
        for validator_addr, current_miss_count in self.current_misses.items():
            previous_miss_count = self.previous_misses.get(validator_addr, 0)
            validator_info = self.validators_data.get(validator_addr, {})
            moniker = validator_info.get('moniker', 'Unknown')
            tokens = validator_info.get('tokens', 0)
            
            if current_miss_count > previous_miss_count:
                miss_increase = current_miss_count - previous_miss_count
                increased_misses.append({
                    'moniker': moniker,
                    'operator_address': validator_addr,
                    'previous_misses': previous_miss_count,
                    'current_misses': current_miss_count,
                    'increase': miss_increase,
                    'tokens': tokens
                })
            else:
                stable_validators.append({
                    'moniker': moniker,
                    'operator_address': validator_addr,
                    'current_misses': current_miss_count,
                    'tokens': tokens
                })
            
            # Check feeder balance
            feeder_addr = self.feeder_addresses.get(validator_addr)
            if feeder_addr:
                balance = self.feeder_balances.get(feeder_addr, 0)
                if balance < self.low_balance_threshold:
                    low_balance_validators.append({
                        'moniker': moniker,
                        'operator_address': validator_addr,
                        'feeder_addr': feeder_addr,
                        'balance': balance,
                        'tokens': tokens
                    })
        
        # Add validators without feeders
        for validator_addr in self.validators_without_feeder:
            validator_info = self.validators_data.get(validator_addr, {})
            validators_without_feeder.append({
                'moniker': validator_info.get('moniker', 'Unknown'),
                'operator_address': validator_addr,
                'tokens': validator_info.get('tokens', 0)
            })
        
        # Calculate vote power statistics
        vote_power_stats = self.calculate_vote_power_stats(increased_misses, stable_validators)
        
        # Send Discord report
        await self.send_discord_report(increased_misses, stable_validators, low_balance_validators, validators_without_feeder, vote_power_stats)
    
    async def send_discord_report(self, increased_misses: List[Dict], stable_validators: List[Dict], 
                                low_balance_validators: List[Dict], validators_without_feeder: List[Dict], 
                                vote_power_stats: Dict):
        """Send monitoring report to Discord"""
        try:
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                logger.error(f"Could not find Discord channel with ID: {self.channel_id}")
                return
            
            # Create embed for the report
            has_issues = increased_misses or low_balance_validators or validators_without_feeder
            embed = discord.Embed(
                title="🔍 Symphony Oracle Validator Monitor Report",
                color=0x00ff00 if not has_issues else 0xff6b6b,
                timestamp=datetime.utcnow()
            )
            
            # Add validators with increased misses
            if increased_misses:
                increased_text = ""
                for validator in increased_misses[:10]:  # Limit to avoid message length issues
                    tokens_formatted = self.format_tokens_as_mld(validator['tokens'])
                    increased_text += f"• **{validator['moniker']}**\n"
                    increased_text += f"  Misses: {validator['previous_misses']} → {validator['current_misses']} (+{validator['increase']}) | Vote Power: {tokens_formatted}\n"
                
                embed.add_field(
                    name="❌ Validators with Increased Misses",
                    value=increased_text or "None",
                    inline=False
                )
            
            # Add validators with low feeder balance
            if low_balance_validators:
                low_balance_text = ""
                for validator in low_balance_validators[:10]:  # Limit to avoid message length issues
                    balance_formatted = self.format_tokens_as_mld(validator['balance'])
                    tokens_formatted = self.format_tokens_as_mld(validator['tokens'])
                    feeder_addr = validator['feeder_addr']
                    low_balance_text += f"• **{validator['moniker']}**\n"
                    low_balance_text += f"  Balance: {balance_formatted} | Vote Power: {tokens_formatted}\n"
                    low_balance_text += f"  Feeder: `{feeder_addr}`\n"
                
                embed.add_field(
                    name="⚠️ Validators with Low Feeder Balance (<1 MLD)",
                    value=low_balance_text,
                    inline=False
                )
            
            # Add validators without feeders
            if validators_without_feeder:
                no_feeder_text = ""
                for validator in validators_without_feeder[:10]:  # Limit to avoid message length issues
                    tokens_formatted = self.format_tokens_as_mld(validator['tokens'])
                    no_feeder_text += f"• **{validator['moniker']}**\n"
                    no_feeder_text += f"  Vote Power: {tokens_formatted}\n"
                
                embed.add_field(
                    name="🚫 Validators without Feeders",
                    value=no_feeder_text,
                    inline=False
                )
            
            # Add stable validators (show count)
            stable_count = len(stable_validators)
            embed.add_field(
                name="✅ Stable Validators",
                value=f"{stable_count} validators with no new misses",
                inline=False
            )
            
            # Add exchange rates
            if self.exchange_rates:
                rates_text = ""
                for denom, rate in self.exchange_rates.items():
                    # Format the rate to show fewer decimal places
                    rate_float = float(rate)
                    if rate_float > 1000:
                        rates_text += f"• {denom.upper()}: {rate_float:,.2f}\n"
                    else:
                        rates_text += f"• {denom.upper()}: {rate_float:.6f}\n"
                
                embed.add_field(
                    name="💱 Current Exchange Rates",
                    value=rates_text,
                    inline=False
                )
            
            # Add vote power statistics
            vote_power_text = f"**Total Network Vote Power:** {self.format_tokens_as_mld(vote_power_stats['total_tokens'])}\n"
            vote_power_text += f"**Stable Vote Power:** {vote_power_stats['stable_pct']:.2f}% ({self.format_tokens_as_mld(vote_power_stats['stable_tokens'])})\n"
            if vote_power_stats['increased_misses_tokens'] > 0:
                vote_power_text += f"**Increased Misses Vote Power:** {vote_power_stats['increased_misses_pct']:.2f}% ({self.format_tokens_as_mld(vote_power_stats['increased_misses_tokens'])})\n"
            if vote_power_stats['no_feeder_tokens'] > 0:
                vote_power_text += f"**No Feeder Vote Power:** {vote_power_stats['no_feeder_pct']:.2f}% ({self.format_tokens_as_mld(vote_power_stats['no_feeder_tokens'])})\n"
            
            embed.add_field(
                name="🗳️ Vote Power Analysis",
                value=vote_power_text,
                inline=False
            )
            
            # Add summary
            total_validators = len(self.current_misses)
            monitored_feeders = len(self.feeder_addresses)
            embed.add_field(
                name="📊 Summary",
                value=f"Total Validators: {total_validators}\nMonitored: {len(increased_misses + stable_validators)}\nFeeders Tracked: {monitored_feeders}\nLow Balance: {len(low_balance_validators)}\nNo Feeder: {len(validators_without_feeder)}",
                inline=False
            )
            
            await channel.send(embed=embed)
            logger.info(f"Sent report: {len(increased_misses)} increased misses, {stable_count} stable, {len(low_balance_validators)} low balance, {len(validators_without_feeder)} no feeder")
            
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
                'feeder_addresses': self.feeder_addresses,
                'feeder_balances': self.feeder_balances,
                'exchange_rates': self.exchange_rates,
                'validators_without_feeder': self.validators_without_feeder,
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
                self.feeder_addresses = data.get('feeder_addresses', {})
                self.feeder_balances = data.get('feeder_balances', {})
                self.exchange_rates = data.get('exchange_rates', {})
                self.validators_without_feeder = data.get('validators_without_feeder', [])
                
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