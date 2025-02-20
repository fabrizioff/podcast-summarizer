# Podcast Summarizer Bot

A Discord bot that creates summaries of YouTube videos/podcasts with the following features:
- Creates detailed summaries in Google Docs
- Generates audio versions of summaries using ElevenLabs
- Maintains a cache of summaries
- Generates podcast topic overviews

## Requirements
- Python 3.8+
- Discord Bot Token
- OpenRouter API Key
- ElevenLabs API Key
- Google Service Account Credentials

## API Setup

### 1. Discord Bot Setup
1. Go to https://discord.com/developers/applications
2. Click "New Application" and name your bot
3. Go to "Bot" section and click "Add Bot"
4. Copy the token under "Token" - this is your DISCORD_TOKEN
5. Enable "Message Content Intent" under Privileged Gateway Intents
6. Invite bot to your server using OAuth2 URL Generator (Bot scope + Send Messages permission)

### 2. OpenRouter API Setup
1. Visit https://openrouter.ai/
2. Create an account and get your API key
3. Save this as your OPENROUTER_API_KEY

### 3. ElevenLabs Setup
1. Go to https://elevenlabs.io/
2. Create an account and get the API key from your profile
3. Save this as your ELEVENLABS_API_KEY

### 4. Google Service Account Setup
1. Go to Google Cloud Console (https://console.cloud.google.com/)
2. Create a new project
3. Enable Google Docs API and Google Drive API
4. Go to "IAM & Admin" > "Service Accounts"
5. Create a new service account
6. Under "Keys", add a new key and select JSON
7. Download the JSON file - this is your credentials.json

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/podcast-summarizer.git
cd podcast-summarizer

2. Create and activate virtual environment:
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

3. Create .env file with your tokens:
DISCORD_TOKEN=your_discord_token
OPENROUTER_API_KEY=your_openrouter_key
ELEVENLABS_API_KEY=your_elevenlabs_key

4. Place your downloaded credentials.json in the project root directory

5. Run the bot:
python bot.py

Commands

!summarize <youtube_url>: Creates a detailed summary in Google Docs
!summarize_audio <youtube_url>: Creates both text summary and audio version
!podcast_topics: Generates overview of all podcast topics in cache
!clearcache: Clears the entire summary cache
!clearcache <youtube_url>: Clears cache for specific video

Limitations

Free tier of ElevenLabs has limited characters per month
OpenRouter API has rate limits based on your subscription
Discord bot requires proper permissions in the server
YouTube videos must have English captions available


