import os
import tempfile
import subprocess
import whisper
from typing import Optional, Tuple
import logging
import time
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('youtube_to_text')

# TODO: add async support
class YouTubeToText:
    def __init__(self, data_dir: str = None):
        """
        Initialize the YouTube to Text converter.
        
        Args:
            data_dir: Directory to store downloaded audio files. If None, uses a temp directory.
        """
        self.data_dir = data_dir or os.path.join(tempfile.gettempdir(), "youtube_to_text")
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
    
    def extract_video_id(self, youtube_url: str) -> str:
        """
        Extract YouTube video ID from URL.
        
        Args:
            youtube_url: URL of the YouTube video
            
        Returns:
            Video ID
        """
        # Extract video ID using regex
        if 'youtu.be' in youtube_url:
            video_id = youtube_url.split('/')[-1].split('?')[0]
        else:
            match = re.search(r'v=([a-zA-Z0-9_-]+)', youtube_url)
            if match:
                video_id = match.group(1)
            else:
                raise ValueError(f"Could not extract video ID from URL: {youtube_url}")
        
        return video_id
    
    def download_audio(self, youtube_url: str) -> Tuple[str, str]:
        """
        Download audio from a YouTube video using yt-dlp.
        
        Args:
            youtube_url: URL of the YouTube video
            
        Returns:
            Tuple containing paths to the downloaded audio files (mp3, wav)
        """
        try:
            logger.info(f"Downloading audio from: {youtube_url}")
            
            # Extract video ID from URL
            video_id = self.extract_video_id(youtube_url)
            
            mp3_path = os.path.join(self.data_dir, f"{video_id}.mp3")
            wav_path = os.path.join(self.data_dir, f"{video_id}.wav")
            
            # Download if file doesn't exist
            if not os.path.exists(mp3_path):
                logger.info(f"Downloading audio to: {mp3_path}")
                
                # Create a temporary filename for yt-dlp output
                temp_output = os.path.join(self.data_dir, f"{video_id}.%(ext)s")
                
                # Use yt-dlp to download audio
                subprocess.run(
                    [
                        "yt-dlp", 
                        "-x", 
                        "--audio-format", "mp3", 
                        "-o", temp_output,
                        youtube_url
                    ],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                # Ensure the file was downloaded with the expected name
                if not os.path.exists(mp3_path):
                    # Try to find the downloaded file
                    downloaded_files = [f for f in os.listdir(self.data_dir) if f.startswith(video_id) and f.endswith('.mp3')]
                    if downloaded_files:
                        # Rename the first matching file to the expected name
                        os.rename(
                            os.path.join(self.data_dir, downloaded_files[0]), 
                            mp3_path
                        )
            else:
                logger.info(f"Audio file already exists: {mp3_path}")
            
            # Convert to WAV for Whisper if needed
            if not os.path.exists(wav_path):
                logger.info(f"Converting MP3 to WAV: {wav_path}")
                subprocess.run(
                    ["ffmpeg", "-i", mp3_path, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav_path],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
            
            return mp3_path, wav_path
            
        except Exception as e:
            logger.error(f"Error downloading audio: {str(e)}")
            raise
    
    def transcribe_audio(self, audio_path: str, model_name: str = None, initial_prompt: str = None) -> str:
        """
        Transcribe audio using Whisper with optional context.
        
        Args:
            audio_path: Path to the audio file
            model_name: Optional model name to use (overrides the default)
            initial_prompt: Text to provide context to Whisper (e.g., video description)
            
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
    
    def process_youtube_url(self, youtube_url: str, model_name: str = "base", 
                            save_transcript: bool = True, initial_prompt: str = None,
                            chunk_size: int = 600) -> str:
        """
        Process a YouTube URL to get its transcript.
        
        Args:
            youtube_url: URL of the YouTube video
            model_name: Whisper model to use
            save_transcript: Whether to save the transcript to a file
            initial_prompt: Text to provide context to Whisper
            chunk_size: Size of audio chunks in seconds (default: 10 minutes)
            
        Returns:
            Transcribed text from the video
        """
        try:
            # Download audio
            mp3_path, wav_path = self.download_audio(youtube_url)
            
            # Extract video ID for saving
            video_id = self.extract_video_id(youtube_url)
            
            # Get total duration
            total_duration = self._get_audio_duration(wav_path)
            
            if total_duration <= chunk_size or chunk_size <= 0:
                # For short audio or if chunking is disabled, process the whole file
                transcript = self.transcribe_audio(wav_path, model_name, initial_prompt)
            else:
                # Split audio into chunks and transcribe each chunk
                logger.info(f"Splitting {total_duration:.2f} seconds audio into {chunk_size} second chunks")
                chunks_dir = os.path.join(self.data_dir, f"{video_id}_chunks")
                os.makedirs(chunks_dir, exist_ok=True)
                
                # Create chunks
                chunk_paths = self._split_audio(wav_path, chunks_dir, chunk_size)
                
                # Transcribe each chunk
                transcripts = []
                for i, chunk_path in enumerate(chunk_paths):
                    logger.info(f"Transcribing chunk {i+1}/{len(chunk_paths)}")
                    
                    # Use initial prompt for context in all chunks
                    # This helps maintain consistency across chunks
                    chunk_transcript = self.transcribe_audio(chunk_path, model_name, initial_prompt)
                    transcripts.append(chunk_transcript)
                
                # Smart combination of transcripts
                transcript = self._combine_transcripts(transcripts)
            
            # Save transcript if requested
            if save_transcript:
                transcript_path = os.path.join(self.data_dir, f"{video_id}_transcript.txt")
                with open(transcript_path, 'w', encoding='utf-8') as f:
                    f.write(transcript)
                logger.info(f"Transcript saved to: {transcript_path}")
            
            return transcript
            
        except Exception as e:
            logger.error(f"Error processing YouTube URL: {str(e)}")
            raise

    def _split_audio(self, audio_path: str, output_dir: str, chunk_size: int) -> list:
        """
        Split audio file into chunks of specified size with overlap.
        
        Args:
            audio_path: Path to the audio file
            output_dir: Directory to save chunks
            chunk_size: Size of chunks in seconds
            
        Returns:
            List of paths to chunk files
        """
        try:
            # Get total duration
            total_duration = self._get_audio_duration(audio_path)
            
            # Define overlap (5 seconds or 5% of chunk size, whichever is larger)
            overlap = max(5, int(chunk_size * 0.05))
            logger.info(f"Using {overlap} seconds overlap between chunks")
            
            # Calculate number of chunks
            num_chunks = int(total_duration / chunk_size) + (1 if total_duration % chunk_size > 0 else 0)
            
            chunk_paths = []
            for i in range(num_chunks):
                # Calculate start time with overlap
                start_time = max(0, i * chunk_size - (0 if i == 0 else overlap))
                
                # Calculate duration with overlap
                duration = min(
                    chunk_size + (0 if i == 0 else overlap) + (0 if i == num_chunks - 1 else overlap),
                    total_duration - start_time
                )
                
                chunk_path = os.path.join(output_dir, f"chunk_{i:03d}.wav")
                
                # Use ffmpeg to extract chunk
                subprocess.run([
                    "ffmpeg", "-y", "-i", audio_path, 
                    "-ss", str(start_time), 
                    "-t", str(duration),
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                    chunk_path
                ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                chunk_paths.append(chunk_path)
                
            return chunk_paths
            
        except Exception as e:
            logger.error(f"Error splitting audio: {str(e)}")
            raise

    def _combine_transcripts(self, transcripts: list) -> str:
        """
        Intelligently combine transcripts from chunks, removing duplicated content.
        
        Args:
            transcripts: List of transcripts from audio chunks
            
        Returns:
            Combined transcript
        """
        if not transcripts:
            return ""
        
        if len(transcripts) == 1:
            return transcripts[0]
        
        # Process each transcript to find potential overlaps
        combined = transcripts[0]
        
        for i in range(1, len(transcripts)):
            current = transcripts[i]
            
            # Try to find overlap between the end of the combined text and the start of the current chunk
            # Look for sentences or phrases that appear in both
            overlap_found = False
            
            # Check for overlapping content (try with different overlap sizes)
            for overlap_size in range(min(100, len(combined)), 20, -10):
                end_of_combined = combined[-overlap_size:].lower()
                start_of_current = current[:min(overlap_size, len(current))].lower()
                
                # Find the longest common substring
                common = self._find_longest_common_substring(end_of_combined, start_of_current)
                
                if common and len(common) > 15:  # Only consider substantial overlaps
                    # Find where the common part ends in the combined text
                    overlap_end = combined.lower().rfind(common) + len(common)
                    
                    # Find where the common part ends in the current chunk
                    current_start = current.lower().find(common) + len(common)
                    
                    # Join the texts, removing the overlapping part
                    combined = combined[:overlap_end] + current[current_start:]
                    overlap_found = True
                    break
            
            # If no overlap found, just append with a space
            if not overlap_found:
                combined += " " + current
        
        return combined

    def _find_longest_common_substring(self, str1: str, str2: str) -> str:
        """
        Find the longest common substring between two strings.
        
        Args:
            str1: First string
            str2: Second string
            
        Returns:
            Longest common substring
        """
        # Simple dynamic programming approach
        m, n = len(str1), len(str2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        max_length = 0
        end_pos = 0
        
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if str1[i - 1] == str2[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                    if dp[i][j] > max_length:
                        max_length = dp[i][j]
                        end_pos = i
        
        return str1[end_pos - max_length:end_pos]

def main():
    """Simple CLI for testing the YouTube to Text functionality."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Convert YouTube videos to text transcripts")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium", "large"],
                        help="Whisper model to use (default: base)")
    parser.add_argument("--output", help="Output file for transcript (default: print to console)")
    
    args = parser.parse_args()
    
    try:
        converter = YouTubeToText()
        transcript = converter.process_youtube_url(args.url, args.model)
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(transcript)
            print(f"Transcript saved to: {args.output}")
        else:
            print("\n--- TRANSCRIPT ---\n")
            print(transcript)
            
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    main() 