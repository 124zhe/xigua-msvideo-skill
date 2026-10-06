"""Offline regression checks. Fixtures use test tones, never generated speech."""
import argparse
from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/xigua-msvideo-skill/scripts'))
sys.path.insert(0, str(ROOT / 'skills/youtube-ms-paint-images/scripts'))
import assemble_video
import frame_manifest
import media_utils
import narrate_edge

spec = importlib.util.spec_from_file_location('install_skills', ROOT / 'scripts/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class PackageTests(unittest.TestCase):
    def test_internal_document_links_resolve(self):
        for doc in ROOT.rglob('*.md'):
            for target in re.findall(r'\]\(([^)]+)\)', doc.read_text(encoding='utf-8')):
                if '://' in target or target.startswith('#'):
                    continue
                with self.subTest(file=doc.relative_to(ROOT), target=target):
                    self.assertTrue((doc.parent / target.split('#')[0]).is_file())

    def test_installer_copies_full_bundle_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()):
            destination = Path(temporary) / 'skills'
            installer.install(destination, dry_run=True)
            self.assertFalse(destination.exists())
            installer.install(destination)
            for name in installer.SKILLS:
                for original in (ROOT / 'skills' / name).rglob('*'):
                    if original.is_file() and '__pycache__' not in original.parts:
                        relative = original.relative_to(ROOT / 'skills' / name)
                        self.assertEqual(original.read_bytes(), (destination / name / relative).read_bytes())
            marker = destination / installer.SKILLS[0] / 'SKILL.md'
            marker.write_text('local customization', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                installer.install(destination)
            self.assertEqual(marker.read_text(encoding='utf-8'), 'local customization')

    def test_installer_checks_all_conflicts_before_copying(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            (destination / installer.SKILLS[-1]).mkdir()
            with self.assertRaises(FileExistsError):
                installer.install(destination)
            self.assertFalse((destination / installer.SKILLS[0]).exists())


class PlanningTests(unittest.TestCase):
    def test_text_split_preserves_content_and_rejects_empty(self):
        source = ('An unexpected observation. A second explanation!\n\n' * 40) + '最后一个句子。'
        chunks = narrate_edge.split_text(source, 180)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(narrate_edge.normalized(''.join(chunks)), narrate_edge.normalized(source))
        with self.assertRaises(ValueError):
            narrate_edge.split_text('  ')

    def test_timestamp_and_filename_precision(self):
        self.assertEqual(frame_manifest.clock_ms('03:57.746'), 237746)
        self.assertEqual(frame_manifest.clock_ms('01:03:57.746'), 3837746)
        self.assertEqual(frame_manifest.filename(119, 237746), 'frame-119_03m57s746ms.png')
        with self.assertRaises(ValueError):
            frame_manifest.clock_ms('00:60')

    def test_rejects_overlap_and_reports_gaps(self):
        frames = [{'id': 1, 'start_ms': 0, 'end_ms': 900},
                  {'id': 2, 'start_ms': 1000, 'end_ms': 2000}]
        _, gaps = frame_manifest.normalize(frames)
        self.assertEqual(gaps[0]['from_ms'], 900)
        frames[0]['end_ms'] = 1100
        with self.assertRaises(ValueError):
            frame_manifest.normalize(frames)

    def test_plan_is_non_destructive_and_reports_missing_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            frame_manifest.make_plan(ROOT / 'examples/storyboard.estimated.json', out)
            report = frame_manifest.audit(out / 'frame-plan.json')
            self.assertEqual(report['missing_ids'], ['001', '002'])
            self.assertFalse(report['complete_inventory'])
            with self.assertRaises(FileExistsError):
                frame_manifest.make_plan(ROOT / 'examples/storyboard.estimated.json', out)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/FFprobe required')
class MediaTests(unittest.TestCase):
    def test_render_cache_and_material_validation(self):
        with tempfile.TemporaryDirectory(prefix='youtube-skills-') as temporary:
            base = Path(temporary) / '素材 with spaces'
            base.mkdir()
            audio = base / 'test-tone.wav'
            media_utils.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                             'sine=frequency=440:sample_rate=24000:duration=2.357', '-c:a', 'pcm_s16le', audio])
            duration = round(float(media_utils.probe('ffprobe', audio)['format']['duration']) * 1000)
            assets = sorted((ROOT / 'skills/youtube-ms-paint-images/assets').glob('*.png'))[:3]
            cuts, frames = [0, 713, 1621, duration], []
            for index, asset in enumerate(assets, 1):
                start, end = cuts[index - 1], cuts[index]
                name = frame_manifest.filename(index, start)
                image = base / name
                shutil.copyfile(asset, image)
                frames.append({'id': index, 'start_ms': start, 'end_ms': end, 'filename': name,
                               'image': name, 'image_review_status': 'passed',
                               'image_sha256': media_utils.sha256(image)})
            # Synthetic test metadata, not a claim of narration alignment or production review.
            storyboard = {'source_audio': audio.name, 'audio_sha256': media_utils.sha256(audio),
                          'duration_ms': duration, 'timing_status': 'audio_aligned_manual', 'frames': frames}
            path = base / 'storyboard.json'
            media_utils.write_json(path, storyboard)
            args = argparse.Namespace(storyboard=path, out=base / 'render-v1.mp4', work=base / 'render-cache',
                                      audio=None, width=320, height=180, fps=30, ffmpeg='ffmpeg', ffprobe='ffprobe')
            with redirect_stdout(io.StringIO()):
                assemble_video.render(args)
            first = media_utils.read_json(args.out.with_suffix('.render-report.json'))
            self.assertEqual(first['video_frames'], math.ceil(duration * 30 / 1000))
            self.assertEqual(first['segments_rendered'], 3)
            self.assertEqual(first['decode_check'], 'passed')
            self.assertEqual(first['visual_audio_review'], 'pending')
            with self.assertRaises(FileExistsError):
                assemble_video.render(args)
            args.out = base / 'render-v2.mp4'
            with redirect_stdout(io.StringIO()):
                assemble_video.render(args)
            self.assertEqual(media_utils.read_json(args.out.with_suffix('.render-report.json'))['segments_reused'], 3)
            bad_inputs = []
            bad = copy.deepcopy(storyboard)
            bad['timing_status'] = 'estimated'
            bad_inputs.append(bad)
            bad = copy.deepcopy(storyboard)
            bad['audio_sha256'] = '0' * 64
            bad_inputs.append(bad)
            bad = copy.deepcopy(storyboard)
            bad['frames'][1]['start_ms'] += 1
            bad_inputs.append(bad)
            bad = copy.deepcopy(storyboard)
            bad['frames'][0]['image_review_status'] = 'pending'
            bad_inputs.append(bad)
            bad = copy.deepcopy(storyboard)
            bad['frames'][0]['image_sha256'] = '0' * 64
            bad_inputs.append(bad)
            for index, bad in enumerate(bad_inputs):
                with self.subTest(rejected_case=index):
                    media_utils.write_json(path, bad)
                    with self.assertRaises(ValueError):
                        assemble_video.validate(path, None, 'ffprobe', 30)

    def test_offline_mp3_merge_preserves_packets_and_word_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, parts = Path(temporary), []
            for index, word in enumerate(['first', 'second']):
                path = base / f'part-{index}.mp3'
                media_utils.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                                 f'sine=frequency={440 + index * 100}:sample_rate=24000:duration=0.6',
                                 '-c:a', 'libmp3lame', '-b:a', '48k', path])
                parts.append((path, {'source_text': word, 'messages': [
                    {'text': word, 'offset': 1000000, 'duration': 2000000}]}))
            _, timings, report = narrate_edge.merge_and_align(parts, 'first second', base / 'merge', 'ffmpeg', 'ffprobe')
            self.assertTrue(report['all_mp3_packets_match'])
            self.assertEqual([w['text'] for w in timings['words']], ['first', 'second'])
            self.assertGreater(timings['words'][1]['start_ms'], timings['words'][0]['end_ms'])
            self.assertEqual(report['listening_review'], 'pending')


if __name__ == '__main__':
    unittest.main()
