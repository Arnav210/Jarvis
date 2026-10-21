"""Synthetic media and metadata for silent tests; no household music is read."""
import json
from pathlib import Path
import wave


def prepare_music(directory, music):
    music.MUSIC = Path(directory) / 'synthetic-library'
    music.MUSIC.mkdir()
    # Titles exercise command assertions; every file contains generated silence.
    entries = []
    for index, (title, artist) in enumerate([
        ('Get Lucky', 'Daft Punk'), ('Billie Jean', 'Michael Jackson'),
        ("That's What I Like", 'Bruno Mars')]):
        audio = music.MUSIC / f'synthetic-{index}.wav'
        with wave.open(str(audio), 'wb') as writer:
            writer.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            writer.writeframes(b'\0\0' * 8000 * 75)
        entries.append({'file': audio.name, 'title': title, 'artist': artist})
    (music.MUSIC / 'library.json').write_text(json.dumps(entries))
