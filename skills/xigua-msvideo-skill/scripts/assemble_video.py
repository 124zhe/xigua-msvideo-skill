"""Render reviewed timestamped stills with one continuous narration track."""
import argparse
import math
from fractions import Fraction
from pathlib import Path

from media_utils import binary, decode, fingerprint, log, probe, publish, read_json, run, sha256, write_json

TIMING_STATES = {'audio_aligned_native_word_boundaries', 'audio_aligned_asr',
                 'audio_aligned_forced', 'audio_aligned_manual'}


def resolve(base, value):
    path = Path(value)
    return (path if path.is_absolute() else base / path).resolve()


def integer(value, label):
    if type(value) is not int:
        raise ValueError(f'{label} must be an integer')
    return value


def validate(storyboard_path, audio_override, ffprobe, fps):
    storyboard = read_json(storyboard_path)
    base = storyboard_path.resolve().parent
    if storyboard.get('timing_status') not in TIMING_STATES:
        raise ValueError('Storyboard lacks a verified audio alignment status')
    audio = audio_override.resolve() if audio_override else resolve(base, storyboard['source_audio'])
    if not audio.is_file() or sha256(audio) != storyboard.get('audio_sha256'):
        raise ValueError('Audio missing or SHA256 differs from storyboard')
    audio_info = probe(ffprobe, audio)
    streams = audio_info['streams']
    if len(streams) != 1 or streams[0]['codec_type'] != 'audio':
        raise ValueError('Use a single-track audio-only narration file')
    duration_ms = integer(storyboard['duration_ms'], 'duration_ms')
    if duration_ms <= 0 or abs(float(audio_info['format']['duration']) * 1000 - duration_ms) > 2:
        raise ValueError('Storyboard duration differs from measured audio duration')
    frames = storyboard['frames']
    if not frames:
        raise ValueError('No storyboard frames')
    total_frames = math.ceil(duration_ms * fps / 1000)
    plan, cursor, last_cut = [], 0, 0
    for index, frame in enumerate(frames, 1):
        start = integer(frame['start_ms'], 'start_ms')
        end = integer(frame['end_ms'], 'end_ms')
        if integer(frame['id'], 'id') != index or start != cursor or end <= start:
            raise ValueError(f'Invalid numbering or non-contiguous interval at frame {index}')
        if frame.get('image_review_status') != 'passed':
            raise ValueError(f'Image review is not passed at frame {index}')
        image = resolve(base, frame['image'])
        minutes, seconds = divmod(start // 1000, 60)
        expected_stem = f'frame-{index:03d}_{minutes:02d}m{seconds:02d}s{start % 1000:03d}ms'
        if not image.is_file() or image.stem != expected_stem or image.name != frame.get('filename'):
            raise ValueError(f'Missing image or inconsistent numbered filename at frame {index}')
        image_hash = sha256(image)
        if image_hash != frame.get('image_sha256'):
            raise ValueError(f'Image SHA256 differs from reviewed version at frame {index}')
        cut = total_frames if index == len(frames) else (end * fps + 500) // 1000
        if cut <= last_cut:
            raise ValueError(f'Frame {index} becomes zero video frames after quantization')
        plan.append({'id': index, 'image': str(image), 'sha256': image_hash,
                     'start_ms': start, 'end_ms': end, 'start_frame': last_cut,
                     'end_frame': cut, 'frames': cut - last_cut})
        cursor, last_cut = end, cut
    if cursor != duration_ms:
        raise ValueError('Storyboard does not cover the entire narration')
    return audio, duration_ms, total_frames, plan


def render(args):
    if args.width < 2 or args.height < 2 or args.width % 2 or args.height % 2 or args.fps <= 0:
        raise ValueError('Width/height must be positive even integers; fps must be positive')
    out, work = args.out.resolve(), args.work.resolve()
    if out.suffix.lower() != '.mp4':
        raise ValueError('Output must be .mp4')
    report_path = out.with_suffix('.render-report.json')
    if out.exists() or report_path.exists():
        raise FileExistsError('Output already exists; use a new video version')
    ffmpeg, ffprobe = binary(args.ffmpeg), binary(args.ffprobe)
    audio, duration_ms, total_frames, plan = validate(args.storyboard, args.audio, ffprobe, args.fps)
    cache = work / 'segments'
    cache.mkdir(parents=True, exist_ok=True)
    settings = {'version': 1, 'width': args.width, 'height': args.height, 'fps': args.fps,
                'codec': 'libx264', 'pix_fmt': 'yuv420p', 'crf': 18, 'preset': 'veryfast',
                'ffmpeg_version': run([ffmpeg, '-version']).splitlines()[0]}
    segment_paths, reused = [], 0
    for item in plan:
        key = fingerprint({'source': item['sha256'], 'frames': item['frames'], **settings})
        segment, metadata = cache / f'{key}.mp4', cache / f'{key}.json'
        cached = False
        if segment.exists() and metadata.exists():
            saved = read_json(metadata)
            cached = saved.get('fingerprint') == key and saved.get('sha256') == sha256(segment)
        if cached:
            reused += 1
        else:
            temporary = cache / f'{key}.tmp.mp4'
            vf = (f'scale={args.width}:{args.height}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                  f'pad={args.width}:{args.height}:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1')
            run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-loop', '1', '-framerate', args.fps,
                 '-i', item['image'], '-vf', vf, '-frames:v', item['frames'], '-an', '-c:v', 'libx264',
                 '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', args.fps,
                 '-video_track_timescale', args.fps * 1000, '-threads', '2', temporary])
            info = probe(ffprobe, temporary)['streams'][0]
            if int(info.get('nb_frames', -1)) != item['frames']:
                raise ValueError(f'Wrong rendered frame count for image {item["id"]}')
            temporary.replace(segment)
            write_json(metadata, {'fingerprint': key, 'sha256': sha256(segment), 'media': info})
        segment_paths.append(segment)
        log({'frame': item['id'], 'total': len(plan), 'status': 'cached' if cached else 'rendered'})
    # The list and each segment reside together, so paths need no escaping.
    listing = cache / 'concat.txt'
    # ffconcat otherwise trusts millisecond-rounded MP4 format.duration. Specify
    # differences of absolute microsecond cuts so its internal time base cannot
    # accumulate one rounding error per image.
    entries = []
    for segment, item in zip(segment_paths, plan):
        start_us = round(item['start_frame'] * 1_000_000 / args.fps)
        end_us = round(item['end_frame'] * 1_000_000 / args.fps)
        entries.append(f"file '{segment.name}'\nduration {(end_us - start_us) / 1_000_000:.6f}\n")
    listing.write_text(''.join(entries), encoding='utf-8')
    intermediate = work / 'final.tmp.mp4'
    run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', listing.name,
         '-i', audio, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
         '-movflags', '+faststart', intermediate], cwd=cache)
    media = probe(ffprobe, intermediate)
    videos = [s for s in media['streams'] if s['codec_type'] == 'video']
    audios = [s for s in media['streams'] if s['codec_type'] == 'audio']
    if len(videos) != 1 or len(audios) != 1:
        raise ValueError('Final video must have exactly one video and one audio stream')
    video, sound = videos[0], audios[0]
    if (video['codec_name'], video['pix_fmt'], video['width'], video['height']) != ('h264', 'yuv420p', args.width, args.height):
        raise ValueError('Final video encoding does not match requested settings')
    if sound['codec_name'] != 'aac' or Fraction(video['avg_frame_rate']) != args.fps or int(video['nb_frames']) != total_frames:
        raise ValueError('Unexpected audio codec, frame rate or total frame count')
    if abs(float(video['duration']) - total_frames / args.fps) > 0.002:
        raise ValueError('Final video duration drifted')
    if abs(float(sound['duration']) - duration_ms / 1000) > 0.15:
        raise ValueError('Final narration duration differs from source')
    decode(ffmpeg, intermediate)
    report = {'status': 'technical_checks_passed', 'output': str(out), 'output_sha256': sha256(intermediate),
              'storyboard': str(args.storyboard.resolve()), 'storyboard_sha256': sha256(args.storyboard),
              'audio': str(audio), 'audio_sha256': sha256(audio), 'source_duration_ms': duration_ms,
              'video_frames': total_frames, 'image_count': len(plan), 'segments_reused': reused,
              'segments_rendered': len(plan) - reused, 'settings': settings, 'cuts': plan,
              'media': media, 'decode_check': 'passed', 'visual_audio_review': 'pending'}
    # Both prepared in work; final path is published only after full technical verification.
    write_json(work / 'render-report.json', report)
    publish(intermediate, out)
    publish(work / 'render-report.json', report_path)
    log({'status': 'complete', 'output': str(out), 'report': str(report_path), 'visual_audio_review': 'pending'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storyboard', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--ffprobe', default='ffprobe')
    args = parser.parse_args()
    try:
        render(args)
    except Exception as exc:
        write_json(args.work / (args.out.stem + '.failure.json'), {'status': 'failed', 'error': str(exc)})
        parser.exit(1, f'{type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    main()
