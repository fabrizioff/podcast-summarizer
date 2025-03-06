import os
import discord
import asyncio
import aiohttp
import re
from discord.ext import commands
from youtube_transcript_api import YouTubeTranscriptApi
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv
from datetime import datetime, timedelta
import json
from typing import Dict, Optional
import tempfile
import logging
import sys
import time
from discord.errors import ConnectionClosed, GatewayNotFound, HTTPException
from aiohttp import web
import threading

# Load environment variables
load_dotenv()

# Constants and Configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
GOOGLE_CREDENTIALS_FILE = 'credentials.json'

# Voice configuration - Dorothy's voice (female American voice)
VOICE_ID = "ThT5KcBeYPX3keUQqHPh"  # Dorothy voice ID
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"

# Rate limiting configuration
MAX_REQUESTS_PER_MINUTE = 50
REQUEST_WINDOW = 60  # seconds
request_timestamps = []

# Cache configuration
CACHE_FILE = 'summary_cache.json'
cache: Dict[str, dict] = {}

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('bot')

class ProcessStatus:
    def __init__(self, ctx, with_audio=False):
        self.ctx = ctx
        self.status_message = None
        self.steps = {
            'transcript': '⏳ Getting transcript...',
            'summary': '⏳ Generating summary...',
            'doc': '⏳ Creating Google Doc...'
        }
        if with_audio:
            self.steps['audio'] = '⏳ Generating audio...'
        
    async def create_status_message(self):
        """Create initial status message"""
        status_text = '\n'.join(self.steps.values())
        self.status_message = await self.ctx.send(f"```\nProcess Status:\n{status_text}\n```")
        
    async def update_step(self, step: str, status: str = '✅'):
        """Update status of a specific step"""
        if self.status_message and step in self.steps:
            self.steps[step] = f"{status} {self.steps[step].split(' ', 1)[1]}"
            status_text = '\n'.join(self.steps.values())
            await self.status_message.edit(content=f"```\nProcess Status:\n{status_text}\n```")

class RateLimiter:
    def __init__(self, max_requests: int, window: int):
        self.max_requests = max_requests
        self.window = window
        self.timestamps = []

    async def acquire(self):
        """Check if request can be made within rate limits"""
        now = datetime.now()
        self.timestamps = [ts for ts in self.timestamps 
                         if now - ts < timedelta(seconds=self.window)]
        
        if len(self.timestamps) >= self.max_requests:
            wait_time = (self.timestamps[0] + timedelta(seconds=self.window) - now).total_seconds()
            if wait_time > 0:
                await asyncio.sleep(wait_time)
        
        self.timestamps.append(now)

class SummaryCache:
    def __init__(self, cache_file: str):
        self.cache_file = cache_file
        self.cache = self.load_cache()
        
    def load_cache(self) -> dict:
        """Load cache from file"""
        try:
            with open(self.cache_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
            
    def save_cache(self):
        """Save cache to file"""
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f)
            
    def get(self, key: str, style: str) -> Optional[str]:
        """Get cached summary"""
        if key in self.cache and style in self.cache[key]:
            return self.cache[key][style]
        return None
        
    def set(self, key: str, style: str, summary: str):
        """Cache new summary"""
        if key not in self.cache:
            self.cache[key] = {}
        self.cache[key][style] = summary
        self.save_cache()

# Initialize rate limiter and cache
rate_limiter = RateLimiter(MAX_REQUESTS_PER_MINUTE, REQUEST_WINDOW)
summary_cache = SummaryCache(CACHE_FILE)

def chunk_text(text: str, max_chunk_size: int = 2500) -> list:
    """Split text into chunks for TTS processing"""
    paragraphs = text.split('\n\n')
    chunks = []
    current_chunk = ""
    
    for paragraph in paragraphs:
        if len(paragraph) > max_chunk_size:
            sentences = re.split(r'(?<=[.!?])\s+', paragraph)
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 1 <= max_chunk_size:
                    current_chunk += " " + sentence if current_chunk else sentence
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = sentence
        else:
            if len(current_chunk) + len(paragraph) + 2 <= max_chunk_size:
                current_chunk += "\n\n" + paragraph if current_chunk else paragraph
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = paragraph
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks

async def text_to_speech(text: str, status: ProcessStatus) -> Optional[bytes]:
    try:
        await rate_limiter.acquire()
        
        text_chunks = chunk_text(text)
        all_audio_data = []
        
        for chunk in text_chunks:
            url = f"{ELEVENLABS_API_URL}/text-to-speech/{VOICE_ID}/stream"
            
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": ELEVENLABS_API_KEY
            }
            
            data = {
                "text": chunk,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as response:
                    if response.status == 200:
                        audio_chunk = await response.read()
                        all_audio_data.append(audio_chunk)
                    else:
                        error_text = await response.text()
                        raise Exception(f"ElevenLabs API error: {error_text}")
        
        final_audio = b''.join(all_audio_data)
        await status.update_step('audio')
        return final_audio
                    
    except Exception as e:
        await status.update_step('audio', '❌')
        raise Exception(f"Error in text-to-speech conversion: {str(e)}")

async def extract_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from URL"""
    try:
        if 'youtu.be' in url:
            return url.split('/')[-1]
        elif 'youtube.com' in url:
            return url.split('v=')[1].split('&')[0]
    except Exception:
        return None
    return None

async def get_transcript(video_id: str, status: ProcessStatus) -> Optional[str]:
    """Get transcript from YouTube video"""
    try:
        await rate_limiter.acquire()

        proxy = {
            'http': 'http://127.0.0.1:8080',
            'https': 'http://127.0.0.1:8080'
        }
        
        try:
            transcript_list = await asyncio.to_thread(
                YouTubeTranscriptApi.get_transcript, 
                video_id,
                languages=['en'],
                proxies=proxy
            )
        except:
            transcript_list = await asyncio.to_thread(
                YouTubeTranscriptApi.get_transcript, 
                video_id,
                languages=['en-US', 'en-GB', 'en'],
                proxies=proxy
            )
        
        processed_texts = []
        current_minute = -1
        
        for entry in transcript_list:
            minute = int(entry['start'] // 60)
            if minute != current_minute:
                current_minute = minute
                processed_texts.append(f"[{minute}:00] ")
            
            processed_texts.append(entry['text'])
        
        transcript = ' '.join(processed_texts)
        await status.update_step('transcript')
        return transcript
        
    except Exception as e:
        await status.update_step('transcript', '❌')
        if 'TranscriptsDisabled' in str(e):
            raise Exception("This video doesn't have captions enabled")
        elif 'NoTranscriptFound' in str(e):
            raise Exception("No English transcript found for this video")
        else:
            raise Exception(f"Error getting transcript: {str(e)}")

async def summarize_text(text: str, status: ProcessStatus) -> Optional[str]:
    """Summarize text using DeepSeek R1 via OpenRouter"""
    try:
        await rate_limiter.acquire()

        prompt = """
Please analyze this transcript and create a detailed summary in exactly this format. What we are preparing is Podcast Insights, I will be using this only for podcasts:

Key Takeaways:
[List 6-7 main points, each with a bullet point (•) followed by bold title and explanation]
• Title: Detailed explanation of the key point...
• Title: Detailed explanation of the key point...

Then provide in-depth breakdowns of key topics, each with its own section:

On [Topic]:
[Detailed analysis and breakdown, with proper paragraphing. Minimum 2-3 paragraphs per section.]

Follow these exact guidelines:
1. Start directly with "Key Takeaways: " without any introduction
2. Make each key takeaway substantive and detailed
3. Include multiple topic sections with "On [Topic]: " headers
4. Maintain minimal spacing between sections
5. Keep paragraph structure but avoid excessive line breaks
6. ***DO NOT USE MARKDOWN FORMATTING (INCLUDING ** FOR BOLD)*** - bold styling is applied programmatically
7. I REPEAT ***DO NOT USE MARKDOWN FORMATTING (INCLUDING ** FOR BOLD)*** - bold styling is applied programmatically

The output should have the below writing style and not use words like highlight, emphasize or any hype terms.

Here's the transcript to analyze:
"""
        
        prompt = f"{prompt} {text}"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:3000",
                    "X-Title": "YouTube Summary Bot"
                },
                json={
                    "model": "deepseek/deepseek-r1:nitro",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 4000,
                    "temperature": 0.7
                }
            ) as response:
                result = await response.json()
                
                if (
                    "choices" not in result
                    or not result["choices"]
                    or "message" not in result["choices"][0]
                    or "content" not in result["choices"][0]["message"]
                ):
                    raise Exception("Invalid response structure from DeepSeek R1")

                summary = result["choices"][0]["message"]["content"].strip()
                formatted_summary = process_summary_format(summary)
                
        await status.update_step('summary')
        return formatted_summary
        
    except Exception as e:
        await status.update_step('summary', '❌')
        raise Exception(f"Error in summarization: {e}")

def process_summary_format(summary: str) -> str:
    """Process the summary to ensure consistent formatting"""
    sections = re.split(r'\n(?=Key Takeaways:|On [^:]+:)', summary)
    
    formatted_sections = []
    for section in sections:
        section = section.strip()
        if section:
            if section.startswith('Key Takeaways:'):
                formatted_sections.append(section)
            elif section.startswith('On '):
                title, content = section.split(':', 1)
                formatted_sections.append(f"{title}:{content.strip()}")
    
    return "\n\n".join(formatted_sections)

async def create_google_doc(summary: str, title: str, status: ProcessStatus) -> Optional[str]:
    """Create a Google Doc with the summary"""
    try:
        await rate_limiter.acquire()
        
        credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_FILE,
            scopes=['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file']
        )
        
        docs_service = build('docs', 'v1', credentials=credentials)
        drive_service = build('drive', 'v3', credentials=credentials)
        
        video_id = title.split('v=')[1] if 'v=' in title else title.split('/')[-1]
        document = {
            'title': f"Podcast Insights - {video_id}"
        }
        
        doc = await asyncio.to_thread(
            docs_service.documents().create(body=document).execute
        )
        doc_id = doc.get('documentId')
        
        requests = [
            {
                'insertText': {
                    'location': {'index': 1},
                    'text': summary
                }
            },
            {
                'updateTextStyle': {
                    'range': {
                        'startIndex': 1,
                        'endIndex': len(summary) + 1
                    },
                    'textStyle': {
                        'fontSize': {'magnitude': 11, 'unit': 'PT'},
                        'weightedFontFamily': {'fontFamily': 'Nunito'}
                    },
                    'fields': 'fontSize,weightedFontFamily'
                }
            }
        ]
        
        titles = re.finditer(r'• ([^:]+):', summary)
        for title in titles:
            requests.append({
                'updateTextStyle': {
                    'range': {
                        'startIndex': title.start(1) + 1,
                        'endIndex': title.end(1) + 1
                    },
                    'textStyle': {'bold': True},
                    'fields': 'bold'
                }
            })
        
        text_patterns = [
            ('Key Takeaways:', 'Key Takeaways:'),
            (r'On [^:]+:', None),
            (r'• [^:]+:', None)
        ]
        
        for pattern, exact_text in text_patterns:
            if exact_text:
                start_index = summary.find(exact_text)
                if start_index != -1:
                    requests.append({
                        'updateTextStyle': {
                            'range': {
                                'startIndex': start_index + 1,
                                'endIndex': start_index + len(exact_text) + 1
                            },
                            'textStyle': {'bold': True},
                            'fields': 'bold'
                        }
                    })
            else:
                matches = list(re.finditer(pattern, summary))
                for match in matches:
                    requests.append({
                        'updateTextStyle': {
                            'range': {
                                'startIndex': match.start() + 1,
                                'endIndex': match.end() + 1
                            },
                            'textStyle': {'bold': True},
                            'fields': 'bold'
                        }
                    })
        
        requests.append({
            'updateParagraphStyle': {
                'range': {
                    'startIndex': 1,
                    'endIndex': len(summary) + 1
                },
                'paragraphStyle': {
                    'lineSpacing': 100,
                    'spaceAbove': {'magnitude': 0, 'unit': 'PT'},
                    'spaceBelow': {'magnitude': 0, 'unit': 'PT'}
                },
                'fields': 'lineSpacing,spaceAbove,spaceBelow'
            }
        })
        
        await asyncio.to_thread(
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={'requests': requests}
            ).execute
        )
        
        permission = {
            'type': 'anyone',
            'role': 'reader',
            'allowFileDiscovery': False
        }
        
        await asyncio.to_thread(
            drive_service.permissions().create(
                fileId=doc_id,
                body=permission,
                supportsAllDrives=True
            ).execute
        )
        
        await status.update_step('doc')
        return f"https://docs.google.com/document/d/{doc_id}/view?usp=sharing"
        
    except Exception as e:
        await status.update_step('doc', '❌')
        try:
            chunks = [summary[i:i+1900] for i in range(0, len(summary), 1900)]
            for chunk in chunks:
                await ctx.send(f"\n{chunk}\n")
            raise Exception(f"Error creating Google Doc (summary sent to Discord): {e}")
        except:
            raise Exception(f"Error creating Google Doc: {e}")
        
@bot.command(name='clearcache')
async def clear_cache(ctx, video_url: str = None):
    """
    Command to clear summary cache
    Usage: 
        !clearcache <youtube_url> - Clears cache for specific video
    """
    try:
        if video_url:
            # Clear cache for specific video
            video_id = await extract_video_id(video_url)
            if not video_id:
                raise ValueError("Invalid YouTube URL")
            
            if video_id in summary_cache.cache:
                del summary_cache.cache[video_id]
                summary_cache.save_cache()
                await ctx.send(f"Cache cleared for video: {video_url}")
            else:
                await ctx.send(f"No cache found for video: {video_url}")
        else:
            # Clear entire cache
            summary_cache.cache.clear()
            summary_cache.save_cache()
            await ctx.send("Entire cache has been cleared")
            
    except Exception as e:
        await ctx.send(f"Error clearing cache: {str(e)}")

@bot.command(name='summarize')
async def summarize(ctx, url: str):
    """
    Command to summarize YouTube video (Google Doc only)
    Usage: !summarize <youtube_url>
    """
    status = ProcessStatus(ctx, with_audio=False)
    await status.create_status_message()
    
    try:
        # Extract video ID
        video_id = await extract_video_id(url)
        if not video_id:
            raise ValueError("Invalid YouTube URL")
        
        # Check cache
        cached_summary = summary_cache.get(video_id, 'default')
        if cached_summary:
            await status.update_step('transcript')
            await status.update_step('summary')
            doc_url = await create_google_doc(cached_summary, f"Summary - {url}", status)
            await ctx.send(f"Summary created: {doc_url}")
            return
        
        # Get transcript
        transcript = await get_transcript(video_id, status)
        if not transcript:
            raise Exception("Couldn't get transcript for this video")
        
        # Get summary
        summary = await summarize_text(transcript, status)
        if not summary:
            raise Exception("Error generating summary")
        
        # Cache the summary
        summary_cache.set(video_id, 'default', summary)
        
        # Create Google Doc
        doc_url = await create_google_doc(summary, f"Summary - {url}", status)
        if not doc_url:
            raise Exception("Error creating Google Doc")
        
        await ctx.send(f"Summary created: {doc_url}")
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='summarize_audio')
async def summarize_audio(ctx, url: str):
    """
    Command to summarize YouTube video and create audio
    Usage: !summarize_audio <youtube_url>
    """
    status = ProcessStatus(ctx, with_audio=True)
    await status.create_status_message()
    
    try:
        # Extract video ID
        video_id = await extract_video_id(url)
        if not video_id:
            raise ValueError("Invalid YouTube URL")
        
        # Check cache
        cached_summary = summary_cache.get(video_id, 'default')
        if cached_summary:
            await status.update_step('transcript')
            await status.update_step('summary')
            doc_url = await create_google_doc(cached_summary, f"Summary - {url}", status)
            
            # Generate audio from cached summary
            audio_data = await text_to_speech(cached_summary, status)
            
            # Save audio to temporary file
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_file_path = temp_file.name
            
            # Send both summary link and audio file
            await ctx.send(
                f"Summary created: {doc_url}",
                file=discord.File(temp_file_path, filename="summary.mp3")
            )
            
            # Clean up temporary file
            os.unlink(temp_file_path)
            return
        
        # Get transcript
        transcript = await get_transcript(video_id, status)
        if not transcript:
            raise Exception("Couldn't get transcript for this video")
        
        # Get summary
        summary = await summarize_text(transcript, status)
        if not summary:
            raise Exception("Error generating summary")
        
        # Cache the summary
        summary_cache.set(video_id, 'default', summary)
        
        # Create Google Doc
        doc_url = await create_google_doc(summary, f"Summary - {url}", status)
        if not doc_url:
            raise Exception("Error creating Google Doc")
        
        # Generate audio
        audio_data = await text_to_speech(summary, status)
        
        # Save audio to temporary file
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
            temp_file.write(audio_data)
            temp_file_path = temp_file.name
        
        # Send both summary link and audio file
        await ctx.send(
            f"Summary created: {doc_url}",
            file=discord.File(temp_file_path, filename="summary.mp3")
        )
        
        # Clean up temporary file
        os.unlink(temp_file_path)
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='podcast_topics')
async def podcast_topics(ctx):
    """
    Command to generate concise podcast topics from cached summaries
    Usage: !podcast_topics
    """
    try:
        if not summary_cache.cache:
            await ctx.send("No podcast summaries found in cache!")
            return
            
        # Process cached summaries for key topics and events
        topics = []
        
        for video_id, styles in summary_cache.cache.items():
            for summary in styles.values():
                # Extract topics and their content
                topic_matches = re.finditer(r'On ([^:]+):(.*?)(?=(?:On [^:]+:|$))', summary, re.DOTALL)
                
                for match in topic_matches:
                    topic = match.group(1).strip()
                    content = match.group(2).strip()
                    
                    # Look for key metrics, numbers, and events
                    numbers = re.findall(r'\$?\d+(?:,\d+)*(?:\.\d+)?(?:k|m|b|M|B|K)?%?', content)
                    has_metrics = len(numbers) > 0
                    
                    # Look for price movements or market events
                    has_market_event = any(word in content.lower() for word in 
                        ['price', 'crash', 'dump', 'pump', 'surge', 'drop', 'fall', 'rise', 
                         'liquidation', 'market', 'trading'])
                    
                    # Look for significant developments
                    has_development = any(word in content.lower() for word in 
                        ['announce', 'launch', 'release', 'update', 'change', 'proposal', 
                         'regulation', 'policy'])
                    
                    # If content is significant, add to topics
                    if has_metrics or has_market_event or has_development:
                        # Extract key details and format concisely
                        paragraphs = content.split('\n\n')
                        key_details = []
                        
                        for para in paragraphs:
                            # Extract specific numbers, dates, and events
                            details = para.strip()
                            if details:
                                key_details.append(details)
                        
                        # Create concise topic summary
                        if key_details:
                            topic_summary = {
                                'title': topic,
                                'content': ' '.join(key_details)
                            }
                            topics.append(topic_summary)
        
        # Sort topics by relevance (presence of numbers/metrics first)
        topics.sort(key=lambda x: len(re.findall(r'\$?\d+', x['content'])), reverse=True)
        
        # Generate formatted content
        doc_content = "Topics for Podcast\n\n"
        
        for topic in topics:
            # Format topic and content like the example
            content = topic['content']
            
            # Format lists with asterisks if found
            list_items = re.findall(r'(?:^|\n)[-•] (.+?)(?=\n|$)', content)
            if list_items:
                content = re.sub(r'(?:^|\n)[-•] (.+?)(?=\n|$)', r'\n* \1', content)
            
            # Add topic summary
            doc_content += f"{topic['title']}: {content}\n\n"
        
        # Create Google Doc
        credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_FILE,
            scopes=['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file']
        )
        
        docs_service = build('docs', 'v1', credentials=credentials)
        drive_service = build('drive', 'v3', credentials=credentials)
        
        document = {
            'title': f"Podcast Topics - {datetime.now().strftime('%Y-%m-%d')}"
        }
        
        doc = await asyncio.to_thread(
            docs_service.documents().create(body=document).execute
        )
        doc_id = doc.get('documentId')
        
        requests = [
            {
                'insertText': {
                    'location': {'index': 1},
                    'text': doc_content
                }
            },
            {
                'updateTextStyle': {
                    'range': {
                        'startIndex': 1,
                        'endIndex': len(doc_content) + 1
                    },
                    'textStyle': {
                        'fontSize': {'magnitude': 11, 'unit': 'PT'},
                        'weightedFontFamily': {'fontFamily': 'Nunito'}
                    },
                    'fields': 'fontSize,weightedFontFamily'
                }
            }
        ]
        
        # Bold the main title
        title_end = doc_content.find('\n')
        if title_end != -1:
            requests.append({
                'updateTextStyle': {
                    'range': {
                        'startIndex': 1,
                        'endIndex': title_end + 1
                    },
                    'textStyle': {
                        'bold': True,
                        'fontSize': {'magnitude': 14, 'unit': 'PT'}
                    },
                    'fields': 'bold,fontSize'
                }
            })
        
        # Bold topic titles
        for match in re.finditer(r'^[^:]+:', doc_content, re.MULTILINE):
            requests.append({
                'updateTextStyle': {
                    'range': {
                        'startIndex': match.start() + 1,
                        'endIndex': match.end() + 1
                    },
                    'textStyle': {'bold': True},
                    'fields': 'bold'
                }
            })
        
        await asyncio.to_thread(
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={'requests': requests}
            ).execute
        )
        
        # Set permissions
        permission = {
            'type': 'anyone',
            'role': 'reader',
            'allowFileDiscovery': False
        }
        
        await asyncio.to_thread(
            drive_service.permissions().create(
                fileId=doc_id,
                body=permission,
                supportsAllDrives=True
            ).execute
        )
        
        await ctx.send(f"Podcast topics created: https://docs.google.com/document/d/{doc_id}/view?usp=sharing")
        
    except Exception as e:
        await ctx.send(f"Error generating topics: {str(e)}")

@bot.command(name='commands')
async def show_commands(ctx):
    """
    Display all available bot commands and their usage
    Usage: !commands
    """
    commands_text = """
Podcast Insights Bot Commands

- !summarize <youtube_url>: Creates a detailed summary (Google Doc only)
  Example: !summarize https://youtube.com/watch?v=12345
- !summarize_audio <youtube_url>: Creates both summary and audio version
  Example: !summarize_audio https://youtube.com/watch?v=12345
- !podcast_topics: Generates an overview of all podcast topics in cache
- !clearcache: Clears the entire summary cache
- !clearcache <youtube_url>: Clears cache for specific video
"""
    await ctx.send(f"```\n{commands_text}\n```")

# Add this function before your bot.run() call
async def start_bot():
    retry_count = 0
    max_retries = 10
    base_delay = 5  # Start with 5 seconds delay
    
    while True:
        try:
            logger.info("Attempting to connect to Discord...")
            await bot.start(DISCORD_TOKEN)
        except (ConnectionClosed, GatewayNotFound, HTTPException, 
                aiohttp.ClientConnectorError, aiohttp.ClientConnectorDNSError) as e:
            if retry_count >= max_retries:
                logger.error(f"Failed to connect after {max_retries} retries. Exiting.")
                break
                
            retry_count += 1
            delay = base_delay * (2 ** min(retry_count, 6))  # Exponential backoff capped at 320 seconds
            logger.error(f"Connection error: {str(e)}. Retrying in {delay} seconds... (Attempt {retry_count}/{max_retries})")
            await asyncio.sleep(delay)
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            break

async def health_check(request):
    return web.Response(text="OK")

def run_health_server():
    # Try different ports if the primary one is in use
    ports_to_try = [8080, 8081, 8082, 8083]
    
    for port in ports_to_try:
        try:
            app = web.Application()
            app.add_routes([web.get('/health', health_check)])
            
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            print(f"Starting health server on port {port}")
            loop.run_until_complete(
                web._run_app(app, host='0.0.0.0', port=port, print=None, handle_signals=False)
            )
            break  # If we get here, the server started successfully
        except OSError as e:
            if "address already in use" in str(e).lower():
                print(f"Port {port} is already in use, trying next port...")
                continue
            else:
                print(f"Health server error: {str(e)}")
                break
        except Exception as e:
            print(f"Health server error: {str(e)}")
            break

# Define the health server
health_thread = threading.Thread(target=run_health_server, daemon=True)
health_thread.start()

if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        logger.info("Bot shutdown by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")