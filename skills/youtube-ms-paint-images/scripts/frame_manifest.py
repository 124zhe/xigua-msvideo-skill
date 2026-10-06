"""Plan stable frame filenames and audit PNG inventory without editing images."""
import argparse
import csv
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

def integer(value, label, minimum=0):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"\d+", value):
        number = int(value)
    else:
        raise ValueError(f"{label} must be an integer")
    if number < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return number

def clock_ms(value):
    match = re.fullmatch(r"(?:(\d+):)?(\d+):(\d{2})(?:\.(\d{1,3}))?", str(value))
    if not match:
        raise ValueError(f"Unsupported time: {value!r}")
    hours, minutes, seconds, fraction = match.groups()
    if int(seconds) >= 60 or (hours is not None and int(minutes) >= 60):
        raise ValueError(f"Invalid time components: {value!r}")
    return ((int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int((fraction or "").ljust(3, "0"))

def time_value(frame, which, required):
    for key in (which + "_ms", "estimated_" + which + "_ms"):
        if key in frame and frame[key] is not None:
            return integer(frame[key], key), key
    if frame.get(which) is not None:
        return clock_ms(frame[which]), which
    if required:
        raise ValueError(f"Frame {frame.get('id')} has no {which} time")
    return None, None

def filename(frame_id, start_ms):
    minutes, tail = divmod(start_ms, 60000)
    seconds, millis = divmod(tail, 1000)
    return f"frame-{frame_id:03d}_{minutes:02d}m{seconds:02d}s{millis:03d}ms.png"

def normalize(document):
    frames = document if isinstance(document, list) else document.get("frames", document.get("jobs"))
    if not isinstance(frames, list) or not frames:
        raise ValueError("Input must contain a nonempty frames/jobs list")
    result, gaps = [], []
    previous_id, previous_start, previous_end = 0, -1, None
    for frame in frames:
        frame_id = integer(frame.get("id"), "id", 1)
        start, start_source = time_value(frame, "start", True)
        end, end_source = time_value(frame, "end", False)
        if frame_id <= previous_id:
            raise ValueError("IDs must be unique and strictly increasing")
        if start <= previous_start:
            raise ValueError("Start times must be strictly increasing")
        if end is not None and end <= start:
            raise ValueError(f"Frame {frame_id}: end must be after start")
        if previous_end is not None:
            if previous_end > start:
                raise ValueError(f"Frame {frame_id}: overlaps previous frame")
            if previous_end < start:
                gaps.append({"before_id": f"{frame_id:03d}", "from_ms": previous_end, "to_ms": start})
        result.append({
            **frame, "id": f"{frame_id:03d}", "filename": filename(frame_id, start),
            "start_ms": start, "end_ms": end, "start_source": start_source, "end_source": end_source,
            "timing_status": frame.get("timing_status", "estimated" if start_source.startswith("estimated_") else "provided_unspecified"),
        })
        previous_id, previous_start, previous_end = frame_id, start, end
    return result, gaps

def make_plan(storyboard, out_dir):
    source = Path(storyboard)
    raw = source.read_bytes()
    frames, gaps = normalize(json.loads(raw.decode("utf-8-sig")))
    out = Path(out_dir)
    plan_path, csv_path = out / "frame-plan.json", out / "timeline.csv"
    if plan_path.exists() or csv_path.exists():
        raise FileExistsError("Plan or timeline already exists; reuse it or choose a new version directory")
    out.mkdir(parents=True, exist_ok=True)
    plan = {
        "source": str(source.resolve()), "source_sha256": hashlib.sha256(raw).hexdigest(),
        "total": len(frames), "gaps": gaps, "frames": frames,
        "filename_rule": "frame-NNN_MMmSSsmmmms.png",
    }
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["id", "filename", "start_ms", "end_ms", "timing_status", "narration_fragment", "shot_type"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(frames)
    return {"total": len(frames), "gaps": gaps, "plan": str(plan_path.resolve())}

def png_header(path):
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError("Invalid PNG signature or IHDR header")
    width, height = struct.unpack(">II", header[16:24])
    if not width or not height:
        raise ValueError("Zero image dimension")
    return width, height

def audit(plan_path, image_dir=None):
    source = Path(plan_path)
    plan = json.loads(source.read_text(encoding="utf-8-sig"))
    directory = Path(image_dir) if image_dir else source.parent
    records, missing, invalid, off_ratio = [], [], [], []
    expected = set()
    for frame in plan["frames"]:
        name = frame["filename"]
        if name != Path(name).name or "/" in name or "\\" in name:
            raise ValueError("A planned filename must be a basename")
        if name in expected:
            raise ValueError("Duplicate planned filename")
        expected.add(name)
        path = directory / name
        row = {"id": frame["id"], "filename": name, "status": "missing"}
        if not path.is_file():
            missing.append(frame["id"])
        else:
            try:
                width, height = png_header(path)
                exact = width * 9 == height * 16
                relative_error = abs(width / height / (16 / 9) - 1)
                ratio = "exact_16_9" if exact else "near_16_9" if relative_error <= 0.002 else "off_ratio"
                row.update(status="present_unreviewed", width=width, height=height, aspect_status=ratio)
                if not exact:
                    off_ratio.append({"id": frame["id"], "width": width, "height": height, "aspect_status": ratio})
            except (OSError, ValueError, struct.error) as error:
                row.update(status="invalid_header", error=str(error))
                invalid.append(frame["id"])
        records.append(row)
    present = sum(r["status"] == "present_unreviewed" for r in records)
    return {
        "total": len(records), "present": present, "missing_ids": missing, "invalid_header_ids": invalid,
        "extra_png_files": sorted(p.name for p in directory.glob("*.png") if p.name not in expected),
        "nonexact_16_9": off_ratio, "complete_inventory": not missing and not invalid,
        "visual_review": "not_performed",
        "note": "Header inventory only. Does not decode image pixels, validate PNG CRC/data, edit images, or approve visual content.",
        "frames": records,
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--storyboard", required=True)
    plan_parser.add_argument("--out-dir", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--plan", required=True)
    audit_parser.add_argument("--image-dir")
    audit_parser.add_argument("--report")
    args = parser.parse_args()
    if args.action == "plan":
        print(json.dumps(make_plan(args.storyboard, args.out_dir), ensure_ascii=False))
        return 0
    report = audit(args.plan, args.image_dir)
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {k: v for k, v in report.items() if k != "frames"}
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if report["complete_inventory"] else 2

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
