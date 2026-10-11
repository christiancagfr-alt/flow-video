
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import csv
import json
import shutil


def task_id(task):
    return f'{int(task["video_seq"]):02d}-{int(task["seg_seq"]):02d}'


def clipboard_tsv(tasks):
    """
    Generic Google-Sheets/plugin-friendly TSV.
    Columns: task id / image path / dialogue / final Flow prompt
    Newlines inside individual fields are flattened to spaces.
    """
    rows = [["任务ID", "参考图", "人物文案", "最终Flow提示词"]]
    for t in tasks:
        rows.append([
            task_id(t),
            t["image_path"] or "",
            " ".join((t["foreign_text"] or "").splitlines()).strip(),
            " ".join((t["prompt"] or "").splitlines()).strip(),
        ])
    return "\n".join("\t".join(str(x) for x in row) for row in rows)


def create_batch(tasks, base_dir):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(base_dir) / f"flow_batch_{stamp}"
    images_dir = out / "images"
    out.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    image_map = {}
    manifest = []

    for t in tasks:
        src = Path(t["image_path"]) if (t["image_path"] or "").strip() else None
        copied = ""
        if src and src.exists():
            key = str(src.resolve())
            if key not in image_map:
                dst = images_dir / src.name
                counter = 1
                while dst.exists() and dst.resolve() != src.resolve():
                    dst = images_dir / f"{src.stem}_{counter}{src.suffix}"
                    counter += 1
                if not dst.exists():
                    shutil.copy2(src, dst)
                image_map[key] = str(dst)
            copied = image_map[key]

        manifest.append({
            "segment_id": int(t["segment_id"]),
            "task_id": task_id(t),
            "recipient": t["recipient_name"],
            "host": t["host_name"],
            "video_seq": int(t["video_seq"]),
            "segment_seq": int(t["seg_seq"]),
            "image_original": t["image_path"] or "",
            "image_batch_copy": copied,
            "dialogue": t["foreign_text"] or "",
            "prompt": t["prompt"] or "",
        })

    # JSON for future automation bridge.
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # TSV works well with spreadsheet-like bulk plugins.
    with (out / "manifest.tsv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["任务ID", "参考图", "人物文案", "最终Flow提示词"])
        for m in manifest:
            writer.writerow([
                m["task_id"],
                m["image_batch_copy"] or m["image_original"],
                " ".join(m["dialogue"].splitlines()).strip(),
                " ".join(m["prompt"].splitlines()).strip(),
            ])

    # Simple prompt/dialogue two-column file for plugins that only need text.
    with (out / "text_only.tsv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["人物文案", "最终Flow提示词"])
        for m in manifest:
            writer.writerow([
                " ".join(m["dialogue"].splitlines()).strip(),
                " ".join(m["prompt"].splitlines()).strip(),
            ])

    return out
