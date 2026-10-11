from __future__ import annotations

"""Small macOS-only AVPlayer bridge used by the QC preview.

The rest of Flow Studio keeps using Qt.  This widget only hosts Apple's AVPlayerView
inside one native QWidget and exposes the tiny playback surface needed by VideoQCPage.
If PyObjC/AVFoundation cannot be loaded the caller can keep using QMediaPlayer.
"""

import sys
import math
from ctypes import c_void_p
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QWidget

MAC_AVPLAYER_AVAILABLE = False
_MAC_IMPORT_ERROR = ""

if sys.platform == "darwin":
    try:
        import objc  # type: ignore
        import AppKit  # type: ignore
        import AVFoundation  # type: ignore
        import AVKit  # type: ignore
        import CoreMedia  # type: ignore
        import Foundation  # type: ignore
        MAC_AVPLAYER_AVAILABLE = True
    except Exception as exc:  # pragma: no cover - exercised on the user's Mac
        _MAC_IMPORT_ERROR = str(exc)


class MacAVPlayerWidget(QWidget):
    """QWidget-backed AVPlayerView with Qt-friendly playback methods/signals."""

    positionChanged = Signal(int)
    durationChanged = Signal(int)
    backendError = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setStyleSheet("background:#000;border:none;")
        self._available = False
        self._player = None
        self._player_view = None
        self._ns_view = None
        self._last_duration = -1
        self._last_position = -1
        self._fullscreen = False
        self._next_source = ''
        self._next_asset = None
        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._poll_time)
        # The backend is created on first visible use, never at hidden-page startup.

    def showEvent(self, event):
        super().showEvent(event)
        if self._available:self._poll.start()

    def hideEvent(self, event):
        self._poll.stop()
        if self._player is not None:self._player.pause()
        super().hideEvent(event)

    @property
    def available(self) -> bool:
        return bool(self._available)

    @property
    def import_error(self) -> str:
        return _MAC_IMPORT_ERROR

    def _ensure_backend(self) -> bool:
        if self._available:
            return True
        if not MAC_AVPLAYER_AVAILABLE:
            return False
        try:
            # QWidget.winId() is the existing NSView* on macOS.  PyObjC officially
            # supports converting a ctypes c_void_p into the correct ObjC proxy.
            self.winId()
            ptr = int(self.winId())
            if not ptr:
                return False
            self._ns_view = objc.objc_object(c_void_p=c_void_p(ptr))
            frame = self._ns_view.bounds()
            self._player = AVFoundation.AVPlayer.alloc().init()
            try:
                self._player.setActionAtItemEnd_(AVFoundation.AVPlayerActionAtItemEndPause)
            except Exception:
                pass
            self._player_view = AVKit.AVPlayerView.alloc().initWithFrame_(frame)
            self._player_view.setPlayer_(self._player)
            try:
                self._player_view.setControlsStyle_(AVKit.AVPlayerViewControlsStyleNone)
            except Exception:
                pass
            try:
                self._player_view.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
            except Exception:
                pass
            try:
                self._player_view.setShowsFullScreenToggleButton_(False)
            except Exception:
                pass
            self._ns_view.addSubview_(self._player_view)
            self._available = True
            self._poll.start()
            return True
        except Exception as exc:  # pragma: no cover - macOS native failure path
            self._available = False
            self.backendError.emit(str(exc))
            return False

    def set_source(self, source) -> bool:
        """Replace the current AVPlayerItem.  Accepts QUrl or path-like input."""
        if not self._ensure_backend():
            return False
        try:
            text = source.toString() if hasattr(source, "toString") else str(source or "")
            local = source.toLocalFile() if hasattr(source, "toLocalFile") else ""
            if local:
                path = str(Path(local).expanduser())
                url = Foundation.NSURL.fileURLWithPath_(path)
            elif text:
                url = Foundation.NSURL.URLWithString_(text)
            else:
                self.stop(clear=True)
                return True
            if url is None:
                return False
            if text == self._next_source and self._next_asset is not None:
                item = AVFoundation.AVPlayerItem.playerItemWithAsset_(self._next_asset)
                self._next_source, self._next_asset = '', None
            else:
                item = AVFoundation.AVPlayerItem.playerItemWithURL_(url)
            self._player.replaceCurrentItemWithPlayerItem_(item)
            self._last_duration = -1
            self._last_position = -1
            self.durationChanged.emit(0)
            self.positionChanged.emit(0)
            self._player.play()
            return True
        except Exception as exc:  # pragma: no cover
            self.backendError.emit(str(exc))
            return False

    def preload_source(self, source):
        """At most one next asset; metadata loads asynchronously without a second player."""
        text=source.toString()
        if text==self._next_source:return
        if self._next_asset is not None:
            try:self._next_asset.cancelLoading()
            except Exception:pass
        self._next_source,self._next_asset='',None
        if not text or not MAC_AVPLAYER_AVAILABLE:return
        try:
            local=source.toLocalFile()
            url=Foundation.NSURL.fileURLWithPath_(local) if local else Foundation.NSURL.URLWithString_(text)
            asset=AVFoundation.AVURLAsset.URLAssetWithURL_options_(url,None)
            asset.loadValuesAsynchronouslyForKeys_completionHandler_(['playable','duration'],lambda:None)
            self._next_source,self._next_asset=text,asset
        except Exception:
            pass

    def has_ended(self) -> bool:
        """Use exact media time, never a near-end millisecond threshold."""
        try:
            item = self._player.currentItem() if self._player is not None else None
            if item is None or self.is_playing():
                return False
            current = self._player.currentTime()
            duration = item.duration()
            seconds = float(CoreMedia.CMTimeGetSeconds(duration))
            position = float(CoreMedia.CMTimeGetSeconds(current))
            return (math.isfinite(seconds) and seconds > 0 and math.isfinite(position)
                    and CoreMedia.CMTimeCompare(current, duration) >= 0)
        except Exception:
            return False

    def play(self):
        if self._ensure_backend() and self._player is not None:
            if self.has_ended():
                zero = CoreMedia.CMTimeMakeWithSeconds(0.0, 600)
                self._player.seekToTime_toleranceBefore_toleranceAfter_(zero, zero, zero)
                self.positionChanged.emit(0)
            self._player.play()

    def pause(self):
        if self._player is not None:
            self._player.pause()

    def stop(self, clear: bool = False):
        if self._player is None:
            return
        try:
            self._player.pause()
            zero = CoreMedia.CMTimeMakeWithSeconds(0.0, 600)
            self._player.seekToTime_(zero)
            if clear:
                from PySide6.QtCore import QUrl
                self.preload_source(QUrl())
                self._player.replaceCurrentItemWithPlayerItem_(None)
        except Exception:
            pass
        self.positionChanged.emit(0)

    def is_playing(self) -> bool:
        try:
            return bool(self._player is not None and float(self._player.rate()) > 0.0)
        except Exception:
            return False

    def position(self) -> int:
        try:
            seconds = float(CoreMedia.CMTimeGetSeconds(self._player.currentTime()))
            if seconds != seconds or seconds < 0:  # NaN / invalid
                return 0
            return int(seconds * 1000)
        except Exception:
            return 0

    def duration(self) -> int:
        try:
            item = self._player.currentItem() if self._player is not None else None
            if item is None:
                return 0
            seconds = float(CoreMedia.CMTimeGetSeconds(item.duration()))
            if seconds != seconds or seconds < 0 or seconds == float("inf"):
                return 0
            return int(seconds * 1000)
        except Exception:
            return 0

    def set_position(self, value_ms: int):
        if not self._ensure_backend() or self._player is None:
            return
        try:
            target = max(0.0, float(value_ms) / 1000.0)
            self._player.seekToTime_(CoreMedia.CMTimeMakeWithSeconds(target, 600))
            self.positionChanged.emit(int(target * 1000))
        except Exception as exc:  # pragma: no cover
            self.backendError.emit(str(exc))

    def toggle_fullscreen(self) -> bool:
        if not self._ensure_backend() or self._player_view is None:
            return False
        try:
            if self._fullscreen:
                self._player_view.exitFullScreenModeWithOptions_(None)
                self._fullscreen = False
            else:
                screen = self._player_view.window().screen() if self._player_view.window() else AppKit.NSScreen.mainScreen()
                ok = self._player_view.enterFullScreenMode_withOptions_(screen, None)
                self._fullscreen = bool(ok)
            return True
        except Exception as exc:  # pragma: no cover
            self.backendError.emit(str(exc))
            return False

    def _poll_time(self):
        if not self._available:
            return
        pos = self.position()
        dur = self.duration()
        if dur != self._last_duration:
            self._last_duration = dur
            self.durationChanged.emit(dur)
        if pos != self._last_position:
            self._last_position = pos
            self.positionChanged.emit(pos)

    def close_native(self):
        from PySide6.QtCore import QUrl
        self.preload_source(QUrl())
        self._poll.stop()
        try:
            if self._player is not None:
                self._player.pause()
                self._player.replaceCurrentItemWithPlayerItem_(None)
            if self._player_view is not None:
                self._player_view.removeFromSuperview()
        except Exception:
            pass
        self._player_view = None
        self._player = None
        self._ns_view = None
        self._available = False

    def closeEvent(self, event):
        self.close_native()
        super().closeEvent(event)
