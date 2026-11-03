from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from app.services import clear_all_history


class ConfirmHistoryClearDialog(QDialog):
    """Explicit confirmation dialog before moving all historical materials & Flow segments to Trash."""

    def __init__(self, plan: dict, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle("确认清空所有历史记录")
        self.setFixedSize(540, 400)
        self._build_ui()

    def _build_ui(self):
        from app.ui.sheet_rich_text import is_dark_theme
        dark = is_dark_theme(self)
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {'#151A22' if dark else '#F8FAFC'};
                color: {'#F1F5F9' if dark else '#0F172A'};
            }}
            QFrame#trashWarnCard {{
                background: {'#2D1B20' if dark else '#FEF2F2'};
                border: 1.5px solid {'#6E323B' if dark else '#FECACA'};
                border-radius: 12px;
            }}
            QFrame#trashKeepCard {{
                background: {'#163528' if dark else '#ECFDF5'};
                border: 1.5px solid {'#286448' if dark else '#A7F3D0'};
                border-radius: 12px;
            }}
            QPushButton#trashConfirmBtn {{
                min-height: 38px;
                padding: 6px 20px;
                font-size: 13.5px;
                font-weight: 800;
                border-radius: 9px;
                background: #DC2626;
                color: #FFFFFF;
                border: none;
            }}
            QPushButton#trashConfirmBtn:hover {{
                background: #B91C1C;
            }}
            QPushButton#trashCancelBtn {{
                min-height: 38px;
                padding: 6px 18px;
                font-size: 13px;
                font-weight: 700;
                border-radius: 9px;
                background: {'#252F3E' if dark else '#FFFFFF'};
                color: {'#E2E8F0' if dark else '#334155'};
                border: 1px solid {'#3A485C' if dark else '#CBD5E1'};
            }}
            QPushButton#trashCancelBtn:hover {{
                background: {'#303D50' if dark else '#F1F5F9'};
            }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("确认清空所有历史记录？")
        title.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {'#F1F5F9' if dark else '#0F172A'};")
        root.addWidget(title)

        sub = QLabel("此操作将清理所有历史任务使用过的中间素材，并移入系统回收站（废纸篓）：")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"font-size: 13px; color: {'#CBD5E1' if dark else '#475569'};")
        root.addWidget(sub)

        img_cnt = int(self.plan.get("image_count", 0))
        seg_cnt = int(self.plan.get("segment_count", 0))
        task_cnt = int(self.plan.get("task_count", 0))
        keep_cnt = int(self.plan.get("protected_export_count", 0))

        warn_card = QFrame(objectName="trashWarnCard")
        w_lay = QVBoxLayout(warn_card)
        w_lay.setContentsMargins(16, 12, 16, 12)
        w_lay.setSpacing(6)
        w_title = QLabel("将自动移入系统回收站（废纸篓）：")
        w_title.setStyleSheet(f"font-size: 13.5px; font-weight: 800; color: {'#FCA5A5' if dark else '#991B1B'};")
        w_lay.addWidget(w_title)

        for line in (
            f"• 所有使用到的图片素材与主播素材目录（检测到 {img_cnt} 项）",
            f"• 所有生成好的 Flow 视频片段与剪辑源缓存（检测到 {seg_cnt} 项）",
            f"• 清空任务日历与所有历史任务记录（共 {task_cnt} 条历史任务）",
        ):
            lbl = QLabel(line)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"font-size: 12.5px; font-weight: 650; color: {'#FECDD3' if dark else '#7F1D1D'};")
            w_lay.addWidget(lbl)
        root.addWidget(warn_card)

        keep_card = QFrame(objectName="trashKeepCard")
        k_lay = QVBoxLayout(keep_card)
        k_lay.setContentsMargins(16, 12, 16, 12)
        k_lay.setSpacing(5)
        k_title = QLabel("将为您完整保留（绝不删除）：")
        k_title.setStyleSheet(f"font-size: 13.5px; font-weight: 800; color: {'#6EE7B7' if dark else '#065F46'};")
        k_lay.addWidget(k_title)

        k_desc = QLabel(
            f"• 所有已导出的【视频剪辑成品 / 成片 MP4】（共保护 {keep_cnt} 个成片文件）\n"
            "• 您的系统设置、API 密钥池、Flow 账号与通道配置全部保留"
        )
        k_desc.setWordWrap(True)
        k_desc.setStyleSheet(f"font-size: 12.5px; font-weight: 650; color: {'#A7F3D0' if dark else '#047857'};")
        k_lay.addWidget(k_desc)
        root.addWidget(keep_card)

        root.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)

        cancel_btn = QPushButton("取消", objectName="trashCancelBtn")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn = QPushButton("确定清空（移入回收站）", objectName="trashConfirmBtn")
        confirm_btn.setCursor(Qt.PointingHandCursor)
        confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(confirm_btn)

        root.addLayout(btn_row)


class _CleanupWorker(QThread):
    progress = Signal(int, str)
    finished_result = Signal(dict)
    failed = Signal(str)

    def __init__(self, plan: dict, parent=None):
        super().__init__(parent)
        self.plan = plan

    def run(self):
        try:
            res = clear_all_history.execute(
                self.plan,
                progress_callback=lambda pct, msg: self.progress.emit(pct, msg),
            )
            self.finished_result.emit(res)
        except Exception as exc:
            self.failed.emit(str(exc))


class TrashCleanupAnimationDialog(QDialog):
    """Simple, clean processing dialog while moving historical materials & Flow segments to Trash."""

    def __init__(self, plan: dict, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.result_data: Optional[dict] = None
        self._worker_done = False

        self.setWindowTitle("正在处理中")
        self.setFixedSize(460, 210)
        self._build_ui()

        self._worker = _CleanupWorker(self.plan, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_result.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _build_ui(self):
        from app.ui.sheet_rich_text import is_dark_theme
        self._dark_mode = is_dark_theme(self)
        dark = self._dark_mode
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {'#151A22' if dark else '#F8FAFC'};
                color: {'#F1F5F9' if dark else '#0F172A'};
            }}
            QFrame#trashStatusBox {{
                background: {'#1D242E' if dark else '#FFFFFF'};
                border: 1px solid {'#34404E' if dark else '#E2E8F0'};
                border-radius: 12px;
            }}
            QPushButton#trashDoneBtn {{
                min-height: 36px;
                padding: 5px 22px;
                font-size: 13px;
                font-weight: 800;
                border-radius: 8px;
                background: #2563EB;
                color: #FFFFFF;
                border: none;
            }}
            QPushButton#trashDoneBtn:hover {{
                background: #1D4ED8;
            }}
            QPushButton#trashDoneBtn:disabled {{
                background: {'#34404E' if dark else '#94A3B8'};
                color: {'#7F8CA0' if dark else '#F8FAFC'};
            }}
            QPushButton#trashOpenFinderBtn {{
                min-height: 36px;
                padding: 5px 14px;
                font-size: 12.5px;
                font-weight: 700;
                border-radius: 8px;
                background: {'#252F3E' if dark else '#FFFFFF'};
                color: {'#E2E8F0' if dark else '#334155'};
                border: 1px solid {'#3A485C' if dark else '#CBD5E1'};
            }}
            QPushButton#trashOpenFinderBtn:hover {{
                background: {'#1E3A5F' if dark else '#EFF6FF'};
                color: {'#93C5FD' if dark else '#1D4ED8'};
                border-color: {'#3B82F6' if dark else '#93C5FD'};
            }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        status_box = QFrame(objectName="trashStatusBox")
        sb_lay = QVBoxLayout(status_box)
        sb_lay.setContentsMargins(16, 14, 16, 14)
        sb_lay.setSpacing(10)

        top_row = QHBoxLayout()
        self.stage_label = QLabel("正在处理中，请稍候…")
        self.stage_label.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {'#F1F5F9' if dark else '#0F172A'};")
        top_row.addWidget(self.stage_label, 1)

        self.pct_label = QLabel("0%")
        self.pct_label.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {'#60A5FA' if dark else '#2563EB'};")
        top_row.addWidget(self.pct_label)
        sb_lay.addLayout(top_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(5)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {'#2A3442' if dark else '#E2E8F0'}; border-radius: 4px; border: none; }}"
            "QProgressBar::chunk { background: #2563EB; border-radius: 4px; }"
        )
        sb_lay.addWidget(self.progress_bar)

        self.detail_label = QLabel("正在将图片素材与 Flow 视频片段移入回收站（保留视频剪辑成品）…")
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet(f"font-size: 12.5px; color: {'#94A3B8' if dark else '#64748B'};")
        sb_lay.addWidget(self.detail_label)

        root.addWidget(status_box, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.open_trash_btn = QPushButton("打开系统回收站", objectName="trashOpenFinderBtn")
        self.open_trash_btn.setCursor(Qt.PointingHandCursor)
        self.open_trash_btn.clicked.connect(self._open_system_trash)
        self.open_trash_btn.setVisible(False)
        btn_row.addWidget(self.open_trash_btn)

        btn_row.addStretch(1)

        self.done_btn = QPushButton("处理中…", objectName="trashDoneBtn")
        self.done_btn.setEnabled(False)
        self.done_btn.setCursor(Qt.PointingHandCursor)
        self.done_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.done_btn)

        root.addLayout(btn_row)

    def _on_progress(self, pct: int, msg: str):
        val = max(5, min(99, int(pct)))
        self.progress_bar.setValue(val)
        self.pct_label.setText(f"{val}%")
        self.detail_label.setText(msg)

    def _on_worker_finished(self, result: dict):
        dark = bool(getattr(self, "_dark_mode", False))
        self.result_data = result
        self._worker_done = True
        self.setWindowTitle("清空完成")
        self.progress_bar.setValue(100)
        self.progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {'#2A3442' if dark else '#E2E8F0'}; border-radius: 4px; border: none; }}"
            "QProgressBar::chunk { background: #10B981; border-radius: 4px; }"
        )
        self.pct_label.setText("100%")
        self.pct_label.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {'#34D399' if dark else '#059669'};")

        res = self.result_data or {}
        img_c = int(res.get("image_count", 0))
        seg_c = int(res.get("segment_count", 0))
        keep_c = int(res.get("protected_export_count", 0))

        self.stage_label.setText("✓ 历史记录已清空")
        self.stage_label.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {'#34D399' if dark else '#059669'};")
        self.detail_label.setText(
            f"已移入回收站：图片素材 {img_c} 项、Flow 片段 {seg_c} 项；已保留视频剪辑成品 {keep_c} 个。"
        )
        self.detail_label.setStyleSheet(f"font-size: 12.5px; font-weight: 650; color: {'#F1F5F9' if dark else '#0F172A'};")

        self.open_trash_btn.setVisible(True)
        self.done_btn.setText("完成")
        self.done_btn.setEnabled(True)

    def _on_worker_failed(self, err: str):
        self._worker_done = True
        self.setWindowTitle("处理异常")
        self.stage_label.setText("清空过程中出现异常")
        self.stage_label.setStyleSheet("font-size: 15px; font-weight: 800; color: #DC2626;")
        self.detail_label.setText(err)
        self.done_btn.setText("关闭")
        self.done_btn.setEnabled(True)

    def _open_system_trash(self):
        trash_path = Path.home() / ".Trash"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(trash_path)))

    def reject(self):
        if not self._worker_done:
            return
        super().reject()
