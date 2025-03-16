import os
import tempfile
import subprocess
import whisper
import requests
from bs4 import BeautifulSoup
import re
import json
import logging
import time
from typing import Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('x_space_to_text')

class XSpaceToText:
    def __init__(self, data_dir: str = None):
        """
        Initialize the X Space to Text converter.
        
        Args:
            data_dir: Directory to store downloaded audio files. If None, uses a temp directory.
        """
        self.data_dir = data_dir or os.path.join(tempfile.gettempdir(), "x_space_to_text")
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Initialize Whisper model (default to base model, can be changed)
        self.model = None
        self.model_name = "base"
    
    def load_model(self, model_name: str = "base"):
        """
        Load the Whisper model.
        
        Args:
            model_name: Name of the Whisper model to use (tiny, base, small, medium, large)
        """
        if self.model is None or self.model_name != model_name:
            logger.info(f"Loading Whisper model: {model_name}")
            self.model = whisper.load_model(model_name)
            self.model_name = model_name
        return self.model
    
    def extract_space_id(self, url: str) -> str:
        """
        Extract Space ID from X post URL.
        
        Args:
            url: URL of the X post containing the Space
            
        Returns:
            Space ID
        """
        try:
            logger.info(f"Extracting Space ID from URL: {url}")
            
            # Check if it's a direct Space URL
            if 'twitter.com/i/spaces/' in url or 'x.com/i/spaces/' in url:
                space_id = url.split('/spaces/')[1].split('?')[0]
                logger.info(f"Found direct Space ID: {space_id}")
                return space_id
            
            # Otherwise, fetch the page with more browser-like headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'max-age=0',
            }
            
            # Try with nitter.net as an alternative frontend
            try:
                # First try with the original URL
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code != 200:
                    # If that fails, try with nitter
                    nitter_url = url.replace('twitter.com', 'nitter.net').replace('x.com', 'nitter.net')
                    logger.info(f"Trying alternative frontend: {nitter_url}")
                    response = requests.get(nitter_url, headers=headers, timeout=10)
            except Exception as e:
                logger.warning(f"Error with primary method: {str(e)}")
                # Try direct approach with space ID in URL
                match = re.search(r'status/(\d+)', url)
                if match:
                    status_id = match.group(1)
                    logger.info(f"Extracted status ID: {status_id}")
                    # For this approach, we'll need to manually provide the Space ID
                    # or use a different method to find it
                    raise ValueError(f"Could not automatically extract Space ID. Please provide the direct Space URL instead.")
                raise
            
            if response.status_code != 200:
                raise ValueError(f"Failed to fetch URL: {url}, status code: {response.status_code}")
            
            # Look for Space ID in the HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Method 1: Look for direct Space links
            space_links = soup.find_all('a', href=re.compile(r'/(i/)?spaces/'))
            for link in space_links:
                href = link.get('href')
                match = re.search(r'spaces/([a-zA-Z0-9]+)', href)
                if match:
                    space_id = match.group(1)
                    logger.info(f"Found Space ID in link: {space_id}")
                    return space_id
            
            # Method 2: Look in meta tags
            for meta in soup.find_all('meta'):
                if meta.get('content') and ('spaces' in meta.get('content') or 'audiospace' in meta.get('content')):
                    content = meta.get('content')
                    match = re.search(r'spaces/([a-zA-Z0-9]+)', content)
                    if match:
                        space_id = match.group(1)
                        logger.info(f"Found Space ID in meta tag: {space_id}")
                        return space_id
            
            # Method 3: Look in script tags
            for script in soup.find_all('script'):
                if script.string and ('spaces' in script.string or 'audiospace' in script.string):
                    match = re.search(r'spaces/([a-zA-Z0-9]+)', script.string)
                    if match:
                        space_id = match.group(1)
                        logger.info(f"Found Space ID in script tag: {space_id}")
                        return space_id
            
            # Method 4: Look for specific patterns in the page
            match = re.search(r'spaces/([a-zA-Z0-9]+)', response.text)
            if match:
                space_id = match.group(1)
                logger.info(f"Found Space ID in page content: {space_id}")
                return space_id
                
            # If we get here, we couldn't find the Space ID
            logger.error(f"Could not extract Space ID from URL: {url}")
            logger.info("Please try using the direct Space URL instead (format: https://twitter.com/i/spaces/SPACE_ID)")
            raise ValueError(f"Could not extract Space ID from URL: {url}")
            
        except Exception as e:
            logger.error(f"Error extracting Space ID: {str(e)}")
            raise
    
    def find_m3u8_url(self, space_id: str) -> str:
        """
        Find the m3u8 URL for a Space.
        
        This is a simplified approach that looks for the m3u8 URL in the page source.
        A more robust approach would use X's API, but that requires authentication.
        
        Args:
            space_id: ID of the X Space
            
        Returns:
            m3u8 URL for the Space audio
        """
        try:
            logger.info(f"Finding m3u8 URL for Space ID: {space_id}")
            
            # Construct the Space URL
            space_url = f"https://twitter.com/i/spaces/{space_id}"
            
            # Fetch the page
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(space_url, headers=headers)
            if response.status_code != 200:
                raise ValueError(f"Failed to fetch Space URL: {space_url}, status code: {response.status_code}")
            
            # Look for m3u8 URL in the page source
            m3u8_pattern = r'https://video\.twimg\.com/amplify_video/\d+/pl/mp4a/\d+/[a-zA-Z0-9_-]+\.m3u8'
            match = re.search(m3u8_pattern, response.text)
            
            if match:
                m3u8_url = match.group(0)
                logger.info(f"Found m3u8 URL: {m3u8_url}")
                return m3u8_url
            
            # Alternative pattern
            alt_pattern = r'https://prod-fastly-[a-z0-9-]+\.video\.pscp\.tv/Transcoding/v1/hls/[a-zA-Z0-9_-]+\.m3u8'
            match = re.search(alt_pattern, response.text)
            
            if match:
                m3u8_url = match.group(0)
                logger.info(f"Found alternative m3u8 URL: {m3u8_url}")
                return m3u8_url
                
            raise ValueError(f"Could not find m3u8 URL for Space ID: {space_id}")
            
        except Exception as e:
            logger.error(f"Error finding m3u8 URL: {str(e)}")
            raise
    
    def download_space_audio(self, space_id: str, m3u8_url: str) -> Tuple[str, str]:
        """
        Download audio from X Space using m3u8 URL.
        
        Args:
            space_id: ID of the X Space
            m3u8_url: URL of the m3u8 playlist
            
        Returns:
            Tuple containing paths to the downloaded audio files (mp3, wav)
        """
        try:
            logger.info(f"Downloading audio from Space ID: {space_id}")
            
            mp3_path = os.path.join(self.data_dir, f"space_{space_id}.mp3")
            wav_path = os.path.join(self.data_dir, f"space_{space_id}.wav")
            
            # Download if file doesn't exist
            if not os.path.exists(mp3_path):
                logger.info(f"Downloading Space audio to: {mp3_path}")
                
                # Use FFmpeg to download and convert the m3u8 stream
                # Note: Using mp4 as intermediate format instead of direct mp3
                temp_mp4_path = os.path.join(self.data_dir, f"space_{space_id}_temp.mp4")
                
                # Escape quotes in URL
                safe_url = m3u8_url.replace('"', '\\"')
                
                try:
                    # First download as MP4 (which works better with HLS streams)
                    logger.info(f"Downloading to temporary MP4: {temp_mp4_path}")
                    process = subprocess.run([
                        "ffmpeg", "-y", "-i", safe_url, 
                        "-c", "copy", temp_mp4_path
                    ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    
                    # Then convert MP4 to MP3
                    logger.info(f"Converting MP4 to MP3: {mp3_path}")
                    subprocess.run([
                        "ffmpeg", "-y", "-i", temp_mp4_path,
                        "-vn", "-acodec", "libmp3lame", "-q:a", "2", mp3_path
                    ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    
                    # Remove temporary MP4 file
                    if os.path.exists(temp_mp4_path):
                        os.remove(temp_mp4_path)
                    
                except subprocess.CalledProcessError as e:
                    logger.error(f"FFmpeg error: {e.stderr}")
                    
                    # Try alternative approach with direct output to MP3
                    logger.info("Trying alternative download approach...")
                    try:
                        subprocess.run([
                            "ffmpeg", "-y", "-i", safe_url, 
                            "-vn", "-acodec", "libmp3lame", "-q:a", "2", mp3_path
                        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    except subprocess.CalledProcessError as e2:
                        logger.error(f"Alternative approach also failed: {e2.stderr}")
                        raise ValueError(f"Failed to download audio: {e2.stderr}")
                
            else:
                logger.info(f"Space audio file already exists: {mp3_path}")
            
            # Convert to WAV for Whisper if needed
            if not os.path.exists(wav_path):
                logger.info(f"Converting MP3 to WAV: {wav_path}")
                subprocess.run([
                    "ffmpeg", "-i", mp3_path, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav_path
                ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            return mp3_path, wav_path
            
        except Exception as e:
            logger.error(f"Error downloading Space audio: {str(e)}")
            raise
    
    def transcribe_audio(self, audio_path: str, model_name: str = None, initial_prompt: str = None) -> str:
        """
        Transcribe audio using Whisper with optional context.
        
        Args:
            audio_path: Path to the audio file
            model_name: Optional model name to use (overrides the default)
            initial_prompt: Text to provide context to Whisper
            
        Returns:
            Transcribed text
        """
        try:
            # Load model if needed
            if model_name:
                self.load_model(model_name)
            elif self.model is None:
                self.load_model(self.model_name)
            
            # Get audio duration to estimate time
            duration = self._get_audio_duration(audio_path)
            logger.info(f"Starting transcription of {duration:.2f} seconds of audio")
            
            # Estimate time based on model size and audio duration
            estimate_per_second = {
                "tiny": 0.03, "base": 0.05, "small": 0.1, 
                "medium": 0.3, "large": 0.6
            }
            estimate = duration * estimate_per_second.get(self.model_name, 0.1)
            logger.info(f"Estimated transcription time: {estimate:.2f} seconds")
            
            # Record start time
            start_time = time.time()
            
            # Start transcription with initial prompt if provided
            logger.info(f"Transcribing audio: {audio_path}")
            transcription_options = {}
            if initial_prompt:
                logger.info("Using initial prompt for context")
                transcription_options["initial_prompt"] = initial_prompt
            
            result = self.model.transcribe(audio_path, **transcription_options)
            
            # Log completion time
            elapsed = time.time() - start_time
            logger.info(f"Transcription completed in {elapsed:.2f} seconds")
            
            return result["text"]
            
        except Exception as e:
            logger.error(f"Error transcribing audio: {str(e)}")
            raise
    
    def _get_audio_duration(self, audio_path: str) -> float:
        """Get duration of audio file in seconds."""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", 
                 "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return float(result.stdout.strip())
        except Exception:
            # Return a default if we can't get the duration
            return 0.0
    
    def process_space_url(self, url: str, model_name: str = "base", 
                          save_transcript: bool = True, initial_prompt: str = None,
                          chunk_size: int = 600) -> str:
        """
        Process an X Space URL to get its transcript.
        
        Args:
            url: URL of the X post containing the Space
            model_name: Whisper model to use
            save_transcript: Whether to save the transcript to a file
            initial_prompt: Text to provide context to Whisper
            chunk_size: Size of audio chunks in seconds
            
        Returns:
            Transcribed text from the Space
        """
        try:
            # Extract Space ID from URL
            space_id = self.extract_space_id(url)
            
            # Find m3u8 URL
            m3u8_url = self.find_m3u8_url(space_id)
            
            # Download audio
            mp3_path, wav_path = self.download_space_audio(space_id, m3u8_url)
            
            # Get total duration
            total_duration = self._get_audio_duration(wav_path)
            
            # Process audio (similar to YouTube processing)
            if total_duration <= chunk_size or chunk_size <= 0:
                # For short audio or if chunking is disabled, process the whole file
                transcript = self.transcribe_audio(wav_path, model_name, initial_prompt)
            else:
                # For longer audio, we would implement chunking similar to YouTube
                # This would be identical to the chunking code in youtube_to_text.py
                logger.info("Chunking not implemented for X Spaces yet, processing entire file")
                transcript = self.transcribe_audio(wav_path, model_name, initial_prompt)
            
            # Save transcript if requested
            if save_transcript:
                transcript_path = os.path.join(self.data_dir, f"space_{space_id}_transcript.txt")
                with open(transcript_path, 'w', encoding='utf-8') as f:
                    f.write(transcript)
                logger.info(f"Transcript saved to: {transcript_path}")
            
            return transcript
            
        except Exception as e:
            logger.error(f"Error processing X Space URL: {str(e)}")
            raise

def main():
    """Simple CLI for testing the X Space to Text functionality."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Convert X Spaces to text transcripts")
    parser.add_argument("--url", help="URL of the X post containing the Space")
    parser.add_argument("--space-id", help="Directly provide the Space ID if known")
    parser.add_argument("--m3u8-url", help="Directly provide the m3u8 URL if known")
    parser.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium", "large"],
                        help="Whisper model to use (default: base)")
    parser.add_argument("--output", help="Output file for transcript (default: print to console)")
    parser.add_argument("--no-save", action="store_true", help="Don't save the transcript automatically")
    parser.add_argument("--description", help="Space description to provide context for transcription")
    
    args = parser.parse_args()
    
    # Ensure at least one of url, space_id, or m3u8_url is provided
    if not (args.url or args.space_id or args.m3u8_url):
        parser.error("At least one of --url, --space-id, or --m3u8-url is required")
    
    try:
        converter = XSpaceToText()
        
        # If m3u8 URL is provided directly
        if args.m3u8_url:
            space_id = args.space_id or "unknown"
            logger.info(f"Using provided m3u8 URL directly: {args.m3u8_url}")
            mp3_path, wav_path = converter.download_space_audio(space_id, args.m3u8_url)
            transcript = converter.transcribe_audio(wav_path, args.model, args.description)
            
            # Save transcript if requested
            if not args.no_save:
                transcript_path = os.path.join(converter.data_dir, f"space_{space_id}_transcript.txt")
                with open(transcript_path, 'w', encoding='utf-8') as f:
                    f.write(transcript)
                logger.info(f"Transcript saved to: {transcript_path}")
            
            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(transcript)
                print(f"Transcript saved to: {args.output}")
            else:
                print("\n--- TRANSCRIPT ---\n")
                print(transcript)
            
        # If Space ID is provided directly
        elif args.space_id:
            logger.info(f"Using provided Space ID: {args.space_id}")
            m3u8_url = converter.find_m3u8_url(args.space_id)
            mp3_path, wav_path = converter.download_space_audio(args.space_id, m3u8_url)
            transcript = converter.transcribe_audio(wav_path, args.model, args.description)
            
            # Save transcript if requested
            if not args.no_save:
                transcript_path = os.path.join(converter.data_dir, f"space_{args.space_id}_transcript.txt")
                with open(transcript_path, 'w', encoding='utf-8') as f:
                    f.write(transcript)
                logger.info(f"Transcript saved to: {transcript_path}")
            
            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(transcript)
                print(f"Transcript saved to: {args.output}")
            else:
                print("\n--- TRANSCRIPT ---\n")
                print(transcript)
            
        # Otherwise, process the URL normally
        else:
            transcript = converter.process_space_url(
                args.url, 
                args.model, 
                not args.no_save,
                args.description
            )
            
            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(transcript)
                print(f"Transcript saved to: {args.output}")
            else:
                print("\n--- TRANSCRIPT ---\n")
                print(transcript)
            
    except Exception as e:
        print(f"Error: {str(e)}")
        print("\nTIP: If you have the direct m3u8 URL, you can use: --m3u8-url \"URL\"")
        print("Or if you have the Space ID, use: --space-id \"ID\"")

if __name__ == "__main__":
    main() 