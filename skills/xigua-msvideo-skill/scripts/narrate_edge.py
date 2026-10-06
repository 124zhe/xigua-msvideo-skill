"""Generate resumable Edge narration and verify native word timing against merged MP3."""
import argparse
import asyncio
import hashlib
import re
import sys
import unicodedata
from pathlib import Path

from media_utils import binary, decode, fingerprint, log, packets, probe, publish, read_json, run, sha256, write_json


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def split_text(source, limit=2400):
    if limit < 100:
        raise ValueError('Chunk size must be at least 100 characters')
    remaining = source.strip()
    chunks = []
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        prefix = remaining[:limit + 1]
        breaks = [m.end() for m in re.finditer(r'\n\s*\n|(?<=[.!?。！？])\s+', prefix)]
        if not breaks:
            breaks = [m.end() for m in re.finditer(r'\s+', prefix)]
        cut = breaks[-1] if breaks else limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if not chunks or normalized(''.join(chunks)) != normalized(source):
        raise ValueError('Empty source or chunk coverage mismatch')
    return chunks


async def synthesize(edge_tts, source, settings, work, ffmpeg, ffprobe):
    key = fingerprint({'source': source, **settings})
    audio, meta = work / f'{key}.mp3', work / f'{key}.json'
    if audio.exists() and meta.exists():
        saved = read_json(meta)
        if saved.get('fingerprint') == key and saved.get('sha256') == sha256(audio):
            log({'part': key[:12], 'status': 'cached'})
            return audio, saved
    temp = work / f'{key}.tmp.mp3'
    for attempt in range(2):
        try:
            messages = []
            speech = edge_tts.Communicate(source, settings['voice'], rate=settings['rate'],
                                         pitch=settings['pitch'], boundary='WordBoundary',
                                         connect_timeout=20, receive_timeout=90)
            with temp.open('wb') as dst:
                async for message in speech.stream():
                    if message['type'] == 'audio':
                        dst.write(message['data'])
                    elif message['type'] == 'WordBoundary':
                        messages.append(message)
            if temp.stat().st_size < 1000 or not messages:
                raise ValueError('No usable audio or word boundaries')
            if normalized(source) != normalized(' '.join(m['text'] for m in messages)):
                raise ValueError('Provider boundary text differs from source; inspect before proceeding')
            decode(ffmpeg, temp)
            info = probe(ffprobe, temp)
            temp.replace(audio)
            saved = {'fingerprint': key, 'sha256': sha256(audio), 'source_text': source,
                     'duration': float(info['format']['duration']), 'messages': messages, **settings}
            write_json(meta, saved)
            log({'part': key[:12], 'status': 'saved', 'duration': saved['duration']})
            return audio, saved
        except (ValueError, TypeError):
            raise  # semantic/schema failures should not trigger another service request
        except Exception:
            if attempt == 1:
                raise
            log({'part': key[:12], 'status': 'retrying_once'})
            await asyncio.sleep(2)


def merge_and_align(parts, source, work, ffmpeg, ffprobe):
    """Also callable offline on preserved (Path, metadata) source parts."""
    work.mkdir(parents=True, exist_ok=True)
    if normalized(source) != normalized(' '.join(s['source_text'] for _, s in parts)):
        raise ValueError('Part source text does not cover source')
    if normalized(source) != normalized(' '.join(m['text'] for _, s in parts for m in s['messages'])):
        raise ValueError('Word boundaries do not cover source')
    # Stable local ASCII names avoid quoting and concat path resolution pitfalls.
    import shutil
    for index, (path, _) in enumerate(parts, 1):
        shutil.copyfile(path, work / f'part-{index:04d}.mp3')
    listing = work / 'concat.txt'
    listing.write_text(''.join(f"file 'part-{i:04d}.mp3'\n" for i in range(1, len(parts) + 1)), encoding='utf-8')
    output = work / 'merged.mp3'
    run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', listing.name,
         '-map', '0:a:0', '-c:a', 'copy', '-write_xing', '1', output.resolve()], cwd=work)
    decode(ffmpeg, output)
    media = probe(ffprobe, output)
    duration_ms = round(float(media['format']['duration']) * 1000)
    master = packets(ffprobe, output)
    cursor, words, offsets = 0, [], []
    for index, (path, saved) in enumerate(parts, 1):
        local = packets(ffprobe, path)
        if not local or [p['data_hash'] for p in master[cursor:cursor + len(local)]] != [p['data_hash'] for p in local]:
            raise ValueError(f'MP3 packet sequence mismatch in part {index}; align final audio separately')
        offset = float(master[cursor]['pts_time']) - float(local[0]['pts_time'])
        offsets.append({'part': index, 'offset_seconds': offset, 'packet_count': len(local), 'sha256': sha256(path)})
        for message in saved['messages']:
            start = message['offset'] / 10_000 + offset * 1000
            end = (message['offset'] + message['duration']) / 10_000 + offset * 1000
            if start < -1 or end < start or end > duration_ms + 1:
                raise ValueError(f'Word boundary outside final audio: {message["text"]}')
            if words and start < words[-1]['start_ms']:
                raise ValueError('Word boundaries not monotonic')
            words.append({'index': len(words), 'text': message['text'], 'start_ms': round(start, 3),
                          'end_ms': round(end, 3), 'part': index,
                          'provider_offset_100ns': message['offset'], 'provider_duration_100ns': message['duration']})
        cursor += len(local)
    if cursor != len(master):
        raise ValueError('Final audio contains unmatched packets')
    timings = {'source_audio': 'narration.mp3', 'audio_sha256': sha256(output), 'duration_ms': duration_ms,
               'timing_status': 'audio_aligned_native_word_boundaries', 'parts': offsets, 'words': words}
    report = {'audio_sha256': timings['audio_sha256'], 'duration_ms': duration_ms,
              'source_text_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(), 'word_count': len(words),
              'boundary_text_matches_source': True, 'all_mp3_packets_match': True,
              'decode_check': 'passed', 'listening_review': 'pending', 'media': media}
    return output, timings, report


async def produce(args):
    work, out = args.work.resolve(), args.out.resolve()
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    targets = [out / n for n in ('narration.mp3', 'word-timings.json', 'audio-manifest.json')]
    if any(p.exists() for p in targets):
        raise FileExistsError('Output already contains a delivery; use a new version directory')
    if args.dependency_dir:
        sys.path.insert(0, str(args.dependency_dir.resolve()))
    import edge_tts
    ffmpeg, ffprobe = binary(args.ffmpeg), binary(args.ffprobe)
    settings = {'voice': args.voice, 'rate': args.rate, 'pitch': args.pitch,
                'library_version': edge_tts.__version__}
    source = args.text.read_text(encoding='utf-8-sig').strip()
    chunks = split_text(source, args.chunk_chars)
    parts_dir = work / 'parts'
    parts_dir.mkdir(exist_ok=True)
    write_json(work / 'input.json', {'text_path': str(args.text.resolve()), 'source_sha256': sha256(args.text),
                                   'settings': settings, 'chunks': chunks})
    parts = []
    for index, chunk in enumerate(chunks, 1):
        log({'part': index, 'total': len(chunks), 'status': 'processing'})
        parts.append(await synthesize(edge_tts, chunk, settings, parts_dir, ffmpeg, ffprobe))
    output, timings, report = merge_and_align(parts, source, work / 'merge', ffmpeg, ffprobe)
    report.update(settings)
    report['source_file_sha256'] = sha256(args.text)
    write_json(work / 'word-timings.json', timings)
    write_json(work / 'audio-manifest.json', report)
    for source_file, target in zip((output, work / 'word-timings.json', work / 'audio-manifest.json'), targets):
        publish(source_file, target)
    log({'status': 'complete', 'audio': str(targets[0]), 'duration_ms': timings['duration_ms'],
         'listening_review': 'pending'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--text', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--dependency-dir', type=Path)
    parser.add_argument('--voice', default='en-US-BrianNeural')
    parser.add_argument('--rate', default='+0%')
    parser.add_argument('--pitch', default='+0Hz')
    parser.add_argument('--chunk-chars', type=int, default=2400)
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--ffprobe', default='ffprobe')
    args = parser.parse_args()
    try:
        asyncio.run(produce(args))
    except Exception as exc:
        write_json(args.work / 'failure.json', {'status': 'failed', 'error': str(exc),
                                               'next_action': 'Inspect error; preserve parts; retry or align final audio separately'})
        parser.exit(1, f'{type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    main()
