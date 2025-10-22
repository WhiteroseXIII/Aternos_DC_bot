import discord
from discord.ext import commands
from python_aternos import Client
from dotenv import load_dotenv
import os
import asyncio
from typing import Optional

# --- Configuration & Environment Variables ---
load_dotenv()
# Get tokens and credentials from environment variables
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
ATERNOS_USER = os.environ.get("ATERNOS_USER")
ATERNOS_PASS = os.environ.get("ATERNOS_PASS")
# NEW: Get the desired output channel ID
OUTPUT_CHANNEL_ID = os.environ.get("OUTPUT_CHANNEL_ID") 

# Set up bot intents and prefix
# FIX 1: Explicitly declare all required intents
intents = discord.Intents.default()
intents.message_content = True  # Required to read command messages
intents.members = True          # Required for Server Member Intent (must be enabled in Portal)
intents.presences = True        # Required for Presence Intent (must be enabled in Portal)
bot = commands.Bot(command_prefix='!', intents=intents)

# Aternos Client and Server variables
aternos_client: Optional[Client] = None
aternos_server = None
# NEW: Global variable to hold the actual Discord Channel object
output_channel: Optional[discord.TextChannel] = None

@bot.event
async def on_ready():
    global output_channel
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    await bot.change_presence(activity=discord.Game(name="Aternos Management"))

    # --- NEW: Get the output channel object ---
    try:
        if OUTPUT_CHANNEL_ID:
            # Note: bot.get_channel() only works AFTER on_ready
            channel_id = int(OUTPUT_CHANNEL_ID)
            output_channel = bot.get_channel(channel_id)
            if output_channel:
                print(f"Output channel set to: #{output_channel.name}")
                await output_channel.send("Aternos Bot is online and ready! Use `!help`.")
            else:
                print(f"WARNING: Could not find channel with ID {OUTPUT_CHANNEL_ID}")
        else:
            print("WARNING: OUTPUT_CHANNEL_ID environment variable not set.")
    except ValueError:
        print("ERROR: OUTPUT_CHANNEL_ID is not a valid integer.")
    except Exception as e:
        print(f"ERROR getting channel: {e}")
    # ----------------------------------------

    # Initialize Aternos connection when bot is ready
    await aternos_login()
    print("Aternos Client Initialized.")

# FIX 2 & 3: Correct Aternos login to be fully asynchronous AND use keyword arguments for credentials
async def aternos_login():
    """Logs into Aternos and selects the first server using asyncio.to_thread."""
    global aternos_client, aternos_server
    try:
        # --- CRITICAL FIX ---
        # Run the synchronous Client() constructor in a separate thread,
        # using 'user' and 'password' as keyword arguments to satisfy the API.
        aternos_client = await asyncio.to_thread(
            Client, 
            user=ATERNOS_USER, 
            password=ATERNOS_PASS
        )
        # --------------------
        
        # Run list_servers() in a separate thread as well
        servers = await asyncio.to_thread(aternos_client.list_servers)
        
        if servers:
            aternos_server = servers[0]
            print(f"Selected Aternos Server: {aternos_server.address}")
            # Success message
            if output_channel:
                await output_channel.send(f"Aternos Login successful! Server set to: `{aternos_server.address}`")
        else:
            print("No Aternos servers found!")
            aternos_server = None
    except Exception as e:
        print(f"Failed to log into Aternos or find server: {e}")
        aternos_client = None
        aternos_server = None
        # Send error to the designated channel on login failure
        if output_channel:
            await output_channel.send(f"FATAL ERROR: Failed to log into Aternos. Check credentials and Aternos status. **Details:** `{e}`")

# --- Discord Commands ---

# Helper function to send messages to the correct channel
async def send_output(ctx: commands.Context, message: str):
    """Sends the message to the designated output channel, or falls back to ctx.send()"""
    if output_channel:
        # Check if ctx is defined before attempting to respond to it.
        # This function is now simplified to assume ctx is passed from a command
        await output_channel.send(message)
    else:
        # Fallback to sending in the command channel
        await ctx.send(message)


@bot.command(name='startserver', help='Starts the Aternos Minecraft server.')
async def start_server(ctx):
    # Only allow command if it comes from the designated channel (optional)
    if output_channel and ctx.channel.id != output_channel.id:
        return await ctx.send(f"Please use the dedicated channel: {output_channel.mention}")

    if not aternos_server:
        # Use ctx.send() for immediate feedback/errors
        return await ctx.send("Aternos server is not configured or failed to log in.")

    # Use the designated output channel
    await send_output(ctx, f"Attempting to **START** Aternos server: `{aternos_server.address}`...")

    try:
        # Fetch status in a thread
        status = await asyncio.to_thread(getattr, aternos_server, 'status')
        
        if status == 'online':
            return await send_output(ctx, "Server is already **ONLINE**.")

        # Run start command in a thread
        await asyncio.to_thread(aternos_server.start)

        if status == 'pending':
            await send_output(ctx, "Server is in the **STARTING QUEUE**. Awaiting confirmation...")
            
            # Run confirm command in a thread
            await asyncio.to_thread(aternos_server.confirm)
            await send_output(ctx, "Start confirmed. Waiting for server to go **ONLINE**.")

        await send_output(ctx, "Start command sent. Use `!status` to track progress.")

    except Exception as e:
        await send_output(ctx, f"Error starting server: {e}")

# IMPORTANT: Repeat the same pattern for check_status and stop_server
@bot.command(name='status', help='Checks the current status of the Aternos server.')
async def check_status(ctx):
    # Only allow command if it comes from the designated channel (optional)
    if output_channel and ctx.channel.id != output_channel.id:
        return await ctx.send(f"Please use the dedicated channel: {output_channel.mention}")
        
    if not aternos_server:
        return await ctx.send("Aternos server is not configured or failed to log in.")
    
    try:
        # Run fetch and attribute access in threads
        await asyncio.to_thread(aternos_server.fetch)
        status = await asyncio.to_thread(getattr, aternos_server, 'status')
        players = await asyncio.to_thread(getattr, aternos_server, 'players_count')
        max_players = await asyncio.to_thread(getattr, aternos_server, 'slots')
        
        if status == 'online':
            message = (
                f"Status: **ONLINE** ✅\n"
                f"Players: **{players}/{max_players}**\n"
                f"Address: `{aternos_server.address}`"
            )
        elif status == 'offline':
            message = "Status: **OFFLINE** 🛑"
        elif status == 'starting':
            message = "Status: **STARTING** 🟡"
        elif status == 'pending':
            message = "Status: **IN QUEUE** ⏳ (Use `!startserver` to try to confirm)"
        else:
            message = f"Status: **{status.upper()}** (Unknown)"

        await send_output(ctx, message) 
        
    except Exception as e:
        await send_output(ctx, f"Error checking status: {e}")

@bot.command(name='stopserver', help='Stops the Aternos Minecraft server.')
async def stop_server(ctx):
    # Only allow command if it comes from the designated channel (optional)
    if output_channel and ctx.channel.id != output_channel.id:
        return await ctx.send(f"Please use the dedicated channel: {output_channel.mention}")

    if not aternos_server:
        return await ctx.send("Aternos server is not configured or failed to log in.")

    await send_output(ctx, f"Attempting to **STOP** Aternos server: `{aternos_server.address}`...")

    try:
        # Run status check in a thread
        status = await asyncio.to_thread(getattr, aternos_server, 'status')
        
        if status == 'offline':
            return await send_output(ctx, "Server is already **OFFLINE**.")

        # Run stop command in a thread
        await asyncio.to_thread(aternos_server.stop)
        await send_output(ctx, "Stop command sent. Server should be shutting down.")

    except Exception as e:
        await send_output(ctx, f"Error stopping server: {e}")


# --- Run Bot ---
if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)
else:
    print("FATAL: DISCORD_TOKEN environment variable not set.")