"""Interactive UI dialogs and helpers for manual external video import.

Supports:
1. Single-segment manual video import (`import_single_segment_interactive`)
2. Whole-video sequential manual video import (`ManualVideoImportDialog(scope="video", target_id=video_id)`)
3. Whole-host sequential / code-matched manual video import (`ManualVideoImportDialog(scope="host", target_id=host_id)`)
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.work_dates import read_connection
from app.services import manual_video_import as mvi


def _resolve_bridge(owner_or_parent=None, explicit_bridge=None):
    if explicit_bridge is not None:
        return explicit_bridge
    cur = owner_or_parent
    visited = set()
    while cur is not None and id(cur) not in visited:
        visited.add(id(cur))
        b = getattr(cur, "bridge", None)
        if b is not None:
            return b
        cur = getattr(cur, "owner", None) or (cur.parentWidget() if hasattr(cur, "parentWidget") else None)
    try:
        from app.services.local_bridge import get_bridge
        return get_bridge()
    except Exception:
        return None


def import_single_segment_interactive(
    parent: QWidget,
    segment_id: int,
    *,
    bridge=None,
    auto_pass_qc: bool = True,
) -> dict | None:
    """Open a file picker to manually import an external video into ``segment_id``."""
    sid = int(segment_id or 0)
    if sid <= 0:
        return None
    with read_connection() as con:
        row = con.execute(
            """
            SELECT fs.id AS segment_id, fs.seg_seq, v.seq AS video_seq, COALESCE(h.name, '') AS host_name
            FROM flow_segments fs
            JOIN videos v ON v.id = fs.video_id
            JOIN hosts h ON h.id = v.host_id
            WHERE fs.id = ?
            """,
            (sid,),
        ).fetchone()
    if not row:
        QMessageBox.warning(parent, "手动导入视频", f"未找到片段 S{sid:06d}")
        return None

    host_name = str(row["host_name"] or "主播")
    code = f"{int(row['video_seq']):02d}-{int(row['seg_seq']):02d}"
    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        f"选择要导入到「{host_name} · {code}」的视频文件",
        str(Path.home() / "Downloads"),
        "视频文件 (*.mp4 *.mov *.m4v *.webm);;所有文件 (*)",
    )
    if not file_path:
        return None
    if not mvi.is_video_file(file_path):
        QMessageBox.warning(parent, "无效视频文件", "所选文件不存在、格式不支持或文件大小为 0。")
        return None

    eff_bridge = _resolve_bridge(parent, bridge)
    res = mvi.execute_manual_imports(
        [(sid, file_path)],
        bridge=eff_bridge,
        auto_pass_qc=auto_pass_qc,
    )
    if res.get("errors"):
        QMessageBox.warning(parent, "导入失败", "\n".join(res["errors"]))
        return res
    return res


class ManualVideoImportDialog(QDialog):
    """Batch sequential / code-matched external video import dialog for a Video or Host."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        scope: str = "video",
        target_id: int = 0,
        bridge=None,
        initial_files: list[str] | None = None,
    ):
        super().__init__(parent)
        self.scope = "host" if str(scope).lower() == "host" else "video"
        self.target_id = int(target_id or 0)
        self.bridge = _resolve_bridge(parent, bridge)
        self._selected_files: list[str] = []
        self._manual_overrides: dict[int, str] = {}  # segment_id -> explicit file path
        self._all_segments: list[dict] = (
            mvi.list_host_segments(self.target_id)
            if self.scope == "host"
            else mvi.list_video_segments(self.target_id)
        )
        self._row_widgets: dict[int, dict] = {}
        self.import_result: dict | None = None

        host_name = str(self._all_segments[0]["host_name"] if self._all_segments else "主播")
        video_seq = int(self._all_segments[0]["video_seq"] if self._all_segments else 0)
        if self.scope == "host":
            scope_title = f"📤 按序号批量导入主播视频 · {host_name}"
            scope_sub = f"支持按文件名编号（如 01-02.mp4）或自然排序序号批量导入到「{host_name}」的各个片段"
        else:
            scope_title = f"📤 按序号导入整条视频 · {host_name} · 视频 #{video_seq:02d}"
            scope_sub = f"选择多个视频或文件夹后，将按自然顺序（1→{video_seq:02d}-01, 2→{video_seq:02d}-02…）导入该条视频"

        self.setWindowTitle(scope_title)
        self.resize(860, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # ── 1. Header ──
        head = QHBoxLayout()
        head.setSpacing(10)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.title_lbl = QLabel(scope_title, objectName="sectionTitle")
        self.sub_lbl = QLabel(scope_sub, objectName="muted")
        title_col.addWidget(self.title_lbl)
        title_col.addWidget(self.sub_lbl)
        head.addLayout(title_col, 1)

        self.btn_pick_files = QPushButton("📄 选择多个视频…", objectName="primaryBtn")
        self.btn_pick_files.setCursor(Qt.PointingHandCursor)
        self.btn_pick_files.setToolTip("从电脑中选择一个或多个外部视频文件（按文件名序号自动排序对应）")
        self.btn_pick_files.clicked.connect(self._on_pick_files)
        head.addWidget(self.btn_pick_files)

        self.btn_pick_folder = QPushButton("📁 选择文件夹…")
        self.btn_pick_folder.setCursor(Qt.PointingHandCursor)
        self.btn_pick_folder.setToolTip("选择一个包含外部视频的文件夹，自动扫描里面的所有视频并按序号匹配")
        self.btn_pick_folder.clicked.connect(self._on_pick_folder)
        head.addWidget(self.btn_pick_folder)

        self.btn_clear_files = QPushButton("清空所选")
        self.btn_clear_files.setCursor(Qt.PointingHandCursor)
        self.btn_clear_files.clicked.connect(self._on_clear_files)
        head.addWidget(self.btn_clear_files)
        root.addLayout(head)

        # ── 2. Options Bar ──
        opt_frame = QFrame(objectName="flowHostDrawerHead")
        opt_lay = QHBoxLayout(opt_frame)
        opt_lay.setContentsMargins(12, 8, 12, 8)
        opt_lay.setSpacing(12)

        if self.scope == "host":
            opt_lay.addWidget(QLabel("匹配范围：", objectName="cardMeta"))
            self.mode_combo = QComboBox()
            self.mode_combo.addItem("全部片段按序号匹配（同时识别 02-05 编号）", "all")
            self.mode_combo.addItem("仅按序号填入「未完成 / 本地缺失」的片段", "incomplete")
            self.mode_combo.currentIndexChanged.connect(lambda *_: self._rebuild_preview())
            opt_lay.addWidget(self.mode_combo)
        else:
            self.mode_combo = None

        self.chk_auto_qc = QCheckBox("导入后直接标记为「质检通过」（视频齐片后直接进入待剪辑）")
        self.chk_auto_qc.setChecked(True)
        self.chk_auto_qc.setCursor(Qt.PointingHandCursor)
        opt_lay.addWidget(self.chk_auto_qc)
        opt_lay.addStretch(1)

        self.match_stat_lbl = QLabel("已匹配 0 / 0 段", objectName="flowRecBadge")
        opt_lay.addWidget(self.match_stat_lbl)
        root.addWidget(opt_frame)

        # ── 3. Segment Mapping Scroll List ──
        self.scroll = QScrollArea(objectName="cardScroll")
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_content = QWidget(objectName="scrollContent")
        self.rows_layout = QVBoxLayout(self.scroll_content)
        self.rows_layout.setContentsMargins(2, 2, 6, 8)
        self.rows_layout.setSpacing(5)
        self.rows_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.scroll_content)
        root.addWidget(self.scroll, 1)

        # ── 4. Footer ──
        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.foot_hint_lbl = QLabel(
            "提示：您既可以在上方批量选文件/文件夹按序号一键对应，也可以在下方任意片段右侧单独点击「📤 选文件」",
            objectName="muted",
        )
        foot.addWidget(self.foot_hint_lbl, 1)

        btn_cancel = QPushButton("取消")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        foot.addWidget(btn_cancel)

        self.btn_confirm = QPushButton("📤 确认导入 (0 段)", objectName="primaryBtn")
        self.btn_confirm.setCursor(Qt.PointingHandCursor)
        self.btn_confirm.setEnabled(False)
        self.btn_confirm.clicked.connect(self._on_confirm_import)
        foot.addWidget(self.btn_confirm)
        root.addLayout(foot)

        if initial_files:
            self._selected_files = [str(p) for p in initial_files if mvi.is_video_file(p)]
        self._build_rows()
        self._rebuild_preview()

    def _build_rows(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._row_widgets.clear()

        for seg in self._all_segments:
            sid = int(seg["segment_id"])
            row = QFrame(self.scroll_content, objectName="dlSegRow")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(12, 6, 10, 6)
            lay.setSpacing(8)

            code_lbl = QLabel(seg["code"], objectName="dlSegCode")
            code_lbl.setFixedWidth(54)
            code_lbl.setAlignment(Qt.AlignCenter)
            lay.addWidget(code_lbl)

            f_status = str(seg.get("flow_status") or "待生成")
            cur_out = str(seg.get("flow_output_path") or "").strip()
            has_local = f_status == "已完成" and mvi.is_video_file(cur_out)
            code_lbl.setProperty("tone", "done" if has_local else "default")

            st_chip = QLabel(
                "已有视频" if has_local else f"⏳ {f_status}",
                objectName="dlChip",
            )
            st_chip.setProperty("tone", "done" if has_local else "warn")
            st_chip.setFixedWidth(78)
            st_chip.setAlignment(Qt.AlignCenter)
            lay.addWidget(st_chip)

            arrow_lbl = QLabel("→", objectName="muted")
            lay.addWidget(arrow_lbl)

            target_lbl = QLabel("未选择外部视频", objectName="dlSegFile")
            target_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            lay.addWidget(target_lbl, 1)

            pick_one_btn = QPushButton("📤 选文件", objectName="dlHostMiniBtn")
            pick_one_btn.setProperty("kind", "import")
            pick_one_btn.setCursor(Qt.PointingHandCursor)
            pick_one_btn.setToolTip(f"单独为片段 {seg['code']} 选择一个外部视频文件")
            pick_one_btn.clicked.connect(lambda _=False, s=sid: self._on_pick_single_row(s))
            lay.addWidget(pick_one_btn)

            clr_one_btn = QPushButton("✕", objectName="dlHostMiniBtn")
            clr_one_btn.setProperty("iconOnly", "true")
            clr_one_btn.setCursor(Qt.PointingHandCursor)
            clr_one_btn.setToolTip("清除该片段待导入的文件")
            clr_one_btn.clicked.connect(lambda _=False, s=sid: self._on_clear_single_row(s))
            lay.addWidget(clr_one_btn)

            self.rows_layout.addWidget(row)
            self._row_widgets[sid] = {
                "row": row,
                "seg": seg,
                "target_lbl": target_lbl,
                "clr_btn": clr_one_btn,
                "matched_file": "",
            }

    def _compute_plan(self) -> dict[int, str]:
        only_inc = bool(self.mode_combo and self.mode_combo.currentData() == "incomplete")
        if self.scope == "host":
            plan = mvi.plan_host_files_match(
                self.target_id,
                self._selected_files,
                only_incomplete=only_inc,
            )
        else:
            plan = mvi.plan_video_files_match(self.target_id, self._selected_files)

        mapping: dict[int, str] = {
            int(seg["segment_id"]): fp for seg, fp in (plan.get("pairs") or [])
        }
        for sid, fp in self._manual_overrides.items():
            if fp:
                mapping[int(sid)] = fp
            else:
                mapping.pop(int(sid), None)
        return mapping

    def _rebuild_preview(self) -> None:
        mapping = self._compute_plan()
        matched_count = 0
        for sid, entry in self._row_widgets.items():
            fp = mapping.get(sid, "")
            entry["matched_file"] = fp
            lbl: QLabel = entry["target_lbl"]
            row: QFrame = entry["row"]
            if fp:
                matched_count += 1
                p = Path(fp)
                try:
                    mb = p.stat().st_size / (1024.0 * 1024.0)
                    lbl.setText(f"🎬 {p.name}  ({mb:.1f} MB)")
                except OSError:
                    lbl.setText(f"🎬 {p.name}")
                lbl.setToolTip(fp)
                row.setProperty("checked", "true")
                entry["clr_btn"].setVisible(True)
            else:
                lbl.setText("— 未分配外部视频 —")
                lbl.setToolTip("")
                row.setProperty("checked", "false")
                entry["clr_btn"].setVisible(False)
            row.style().unpolish(row)
            row.style().polish(row)

        tot = len(self._all_segments)
        self.match_stat_lbl.setText(f"已匹配 {matched_count} / {tot} 段")
        self.btn_confirm.setText(f"📤 确认导入 ({matched_count} 段)")
        self.btn_confirm.setEnabled(matched_count > 0)

    def _on_pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择要按序号导入的视频文件（可多选）",
            str(Path.home() / "Downloads"),
            "视频文件 (*.mp4 *.mov *.m4v *.webm);;所有文件 (*)",
        )
        if not files:
            return
        self._selected_files = [str(p) for p in files if mvi.is_video_file(p)]
        self._rebuild_preview()

    def _on_pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择包含外部视频文件的文件夹",
            str(Path.home() / "Downloads"),
        )
        if not folder:
            return
        found = mvi.collect_video_files_from_folder(folder)
        if not found:
            QMessageBox.information(self, "未找到视频", "所选文件夹内没有找到有效的视频文件（.mp4 / .mov / .m4v / .webm）。")
            return
        self._selected_files = found
        self._rebuild_preview()

    def _on_clear_files(self) -> None:
        self._selected_files.clear()
        self._manual_overrides.clear()
        self._rebuild_preview()

    def _on_pick_single_row(self, sid: int) -> None:
        entry = self._row_widgets.get(int(sid))
        if not entry:
            return
        seg = entry["seg"]
        fp, _ = QFileDialog.getOpenFileName(
            self,
            f"选择导入到片段 {seg['code']} 的视频文件",
            str(Path.home() / "Downloads"),
            "视频文件 (*.mp4 *.mov *.m4v *.webm);;所有文件 (*)",
        )
        if not fp:
            return
        if not mvi.is_video_file(fp):
            QMessageBox.warning(self, "无效视频文件", "所选文件不存在或大小为 0。")
            return
        self._manual_overrides[int(sid)] = str(fp)
        self._rebuild_preview()

    def _on_clear_single_row(self, sid: int) -> None:
        self._manual_overrides[int(sid)] = ""
        self._rebuild_preview()

    def _on_confirm_import(self) -> None:
        mapping = self._compute_plan()
        pairs = [(sid, fp) for sid, fp in sorted(mapping.items()) if fp]
        if not pairs:
            return
        res = mvi.execute_manual_imports(
            pairs,
            bridge=self.bridge,
            auto_pass_qc=self.chk_auto_qc.isChecked(),
        )
        self.import_result = res
        if res.get("errors"):
            QMessageBox.warning(
                self,
                "部分片段导入异常",
                f"已成功导入 {res.get('imported', 0)} 个片段，但有以下异常：\n" + "\n".join(res["errors"][:8]),
            )
        if int(res.get("imported") or 0) > 0:
            self.accept()
