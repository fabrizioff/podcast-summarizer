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
```

# Docker Setup

If you prefer to run the bot using Docker:

1. Make sure Docker and Docker Compose are installed on your system:
   - [Install Docker](https://docs.docker.com/get-docker/)
   - [Install Docker Compose](https://docs.docker.com/compose/install/)

2. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/podcast-summarizer.git
   cd podcast-summarizer
   ```

3. Create a `.env` file with your tokens:
   ```
   DISCORD_TOKEN=your_discord_token
   OPENROUTER_API_KEY=your_openrouter_key
   ELEVENLABS_API_KEY=your_elevenlabs_key
   ```

4. Place your downloaded `credentials.json` in the project root directory

5. Build and run the container:
   ```bash
   docker-compose up -d
   ```

6. View logs to ensure everything is working:
   ```bash
   docker-compose logs -f
   ```

7. To stop the bot:
   ```bash
   docker-compose down
   ```

The Docker setup uses the host network for simplicity and mounts the current directory as a volume, so your cache and credential files are preserved between container restarts.

## VPS Deployment with Tailscale Exit Node

If you're running the bot on a VPS (such as Hetzner), you might encounter YouTube blocking requests from datacenter IP addresses. Here's how to use Tailscale as a free solution to route your traffic through a residential IP:

### Setting up Tailscale as a workaround

1. **Install Tailscale on your Mac**
   - Download and install from [tailscale.com](https://tailscale.com/download)
   - Sign up or log in to your Tailscale account
   - Connect your Mac to your Tailscale network

2. **Configure your Mac as an exit node**
   - Open Terminal and run:
     ```bash
     sudo tailscale up --advertise-exit-node
     ```
   - Go to Tailscale admin console (https://login.tailscale.com/admin/machines)
   - Find your Mac and enable "Exit node" permission

3. **Install Tailscale on your VPS**
   - SSH into your VPS
   - Install Tailscale:
     ```bash
     curl -fsSL https://tailscale.com/install.sh | sh
     ```
   - Connect to your Tailscale network:
     ```bash
     sudo tailscale up
     ```

4. **Configure your VPS to use Mac as exit node**
   - On your VPS, run:
     ```bash
     sudo tailscale up --exit-node=<your-mac-tailscale-name>
     ```
   - Verify connection with:
     ```bash
     curl ifconfig.me
     # Should show your Mac's public IP, not the VPS IP
     ```

5. **Run the Docker container with host networking**
   - This setup already works with our docker-compose.yml since it uses `network_mode: host`

### Troubleshooting

- **If Tailscale disconnects:**
  ```bash
  # On VPS, restart Tailscale and reconnect to exit node
  sudo tailscale down
  sudo tailscale up --exit-node=<your-mac-tailscale-name>
  ```

- **When installing packages on VPS:**
  ```bash
  # Temporarily disable exit node routing
  sudo tailscale up --exit-node=""
  
  # Install your packages
  apt update && apt install whatever-you-need
  
  # Re-enable exit node routing when done
  sudo tailscale up --exit-node=<your-mac-tailscale-name>
  ```

- **Verifying traffic routing:**
  ```bash
  # Check current IP (should match your Mac's public IP)
  curl ifconfig.me
  
  # Test YouTube connectivity
  curl -I https://www.youtube.com
  ```

Note: Keep your Mac online while the bot is running, or set up another device as a backup exit node.
