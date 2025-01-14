from .config import KoKoroConfig, SUPPORTED_LANGUAGES, MAX_PHONEME_LENGTH, SAMPLE_RATE
from onnxruntime import InferenceSession
import numpy as np
from .tokenizer import tokenize, phonemize
from .log import log
import time
import re
import json
from functools import lru_cache


class Kokoro:
    def __init__(self, model_path: str, voices_path: str):
        self.config = KoKoroConfig(model_path, voices_path)
        self.config.validate()
        self.sess = InferenceSession(model_path)
        self.voices: list[str] = self.config.get_voice_names()

    @classmethod
    def from_session(cls, session: InferenceSession, voices_path: str):
        instance = cls.__new__(cls)
        instance.sess = session
        instance.config = KoKoroConfig(session._model_path, voices_path)
        instance.config.validate()
        instance.voices = instance.config.get_voice_names()
        return instance

    def _create_audio(self, phonemes: str, voice: str, speed: float):
        start_t = time.time()
        tokens = tokenize(phonemes)
        assert (
            len(tokens) <= MAX_PHONEME_LENGTH
        ), f"Context length is {MAX_PHONEME_LENGTH}, but leave room for the pad token 0 at the start & end"

        style = self.get_voice_style(voice)[len(tokens)]
        tokens = [[0, *tokens, 0]]

        audio = self.sess.run(
            None,
            dict(
                tokens=tokens, style=style, speed=np.ones(1, dtype=np.float32) * speed
            ),
        )[0]
        audio_duration = len(audio) / SAMPLE_RATE
        create_duration = time.time() - start_t
        speedup_factor = audio_duration / create_duration
        log.debug(
            f"Created audio in length of {audio_duration:.2f}s for {len(phonemes)} phonemes in {create_duration:.2f}s (More than {speedup_factor:.2f}x real-time)"
        )
        return audio, SAMPLE_RATE

    @lru_cache
    def get_voice_style(self, name: str):
        with open(self.config.voices_path) as f:
            voices = json.load(f)
        return np.array(voices[name], dtype=np.float32)

    def _split_phonemes(self, phonemes: str):
        """
        Split phonemes into batches of MAX_PHONEME_LENGTH
        Prefer splitting at punctuation marks.
        """
        # Regular expression to split by punctuation and keep them
        words = re.split(r"([.,!?;])", phonemes)
        batched_phoenemes = []
        current_batch = ""

        for part in words:
            # Remove leading/trailing whitespace
            part = part.strip()

            if part:
                # If adding the part exceeds the max length, split into a new batch
                if len(current_batch) + len(part) + 1 > MAX_PHONEME_LENGTH:
                    batched_phoenemes.append(current_batch.strip())
                    current_batch = part
                else:
                    if part in ".,!?;":
                        current_batch += part
                    else:
                        if current_batch:
                            current_batch += " "
                        current_batch += part

        # Append the last batch if it contains any phonemes
        if current_batch:
            batched_phoenemes.append(current_batch.strip())

        return batched_phoenemes

    def create(self, text: str, voice: str, speed: float = 1.0, lang="en-us"):
        """
        Create audio from text using the specified voice and speed.
        """

        assert (
            lang in SUPPORTED_LANGUAGES
        ), f"Language must be either {', '.join(SUPPORTED_LANGUAGES)}. Got {lang}"
        assert speed >= 0.5 and speed <= 2.0, "Speed should be between 0.5 and 2.0"
        assert voice in self.voices, f"Voice {voice} not found in available voices"

        start_t = time.time()
        phonemes = phonemize(text, lang)
        # Create batches of phonemes by splitting spaces to MAX_PHONEME_LENGTH
        batched_phoenemes = self._split_phonemes(phonemes)

        audio = []
        log.debug(
            f"Creating audio for {len(batched_phoenemes)} batches for {len(phonemes)} phonemes"
        )
        for phonemes in batched_phoenemes:
            log.debug(f"Phonemes: {phonemes}")
            if len(phonemes) > MAX_PHONEME_LENGTH:
                log.warning(
                    f"Phonemes are too long, truncating to {MAX_PHONEME_LENGTH} phonemes"
                )
                phonemes = phonemes[:MAX_PHONEME_LENGTH]
            audio_part, _ = self._create_audio(phonemes, voice, speed)
            audio.append(audio_part)
        audio = np.concatenate(audio)
        log.debug(f"Created audio in {time.time() - start_t:.2f}s")
        return audio, SAMPLE_RATE

    def get_voices(self):
        return self.voices

    def get_languages(self):
        return SUPPORTED_LANGUAGES
