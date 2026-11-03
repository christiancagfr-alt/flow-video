from __future__ import annotations

"""Small macOS-only AVPlayer bridge used by the QC preview.

The rest of Flow Studio keeps using Qt.  To avoid Qt's native-child-widget hierarchy
contagion (which promotes every ancestor container into a separate Retina IOSurface
backing store and spikes RAM by ~1 GB), MacAVPlayerWidget stays a pure Qt alien QWidget
and mounts a clipped passthrough NSView + AVPlayerView directly onto the top-level
window's existing QNSView.
If PyObjC/AVFoundation cannot be loaded the caller can keep using QMediaPlayer.
"""

import sys
import math
import weakref
from ctypes import c_void_p
from pathlib import Path

from PySide6.QtCore import Qt, QEvent, QPoint, QRect, QTimer, Signal
from PySide6.QtWidgets import QWidget

MAC_AVPLAYER_AVAILABLE = False
_MAC_IMPORT_ERROR = ""
_PassthroughClipView = None

if sys.platform == "darwin":
    try:
        import objc  # type: ignore
        import AppKit  # type: ignore
        import AVFoundation  # type: ignore
        import AVKit  # type: ignore
        import CoreMedia  # type: ignore
        import Foundation  # type: ignore

        try:
            _PassthroughClipView = objc.lookUpClass("_FlowStudioAVClipView")
        except objc.nosuchclass_error:
            class _PassthroughClipView(AppKit.NSView):  # type: ignore[misc,valid-type]
                def isFlipped(self):
                    return True

                def hitTest_(self, point):
                    # Pass mouse clicks, wheel scrolls, and cursor hit-tests straight
                    # through to Qt's top-level QNSView so QC shortcuts and scrolling
                    # never lose focus or get swallowed by the video layer.
                    return None

        MAC_AVPLAYER_AVAILABLE = True
    except Exception as exc:  # pragma: no cover - exercised on the user's Mac
        _MAC_IMPORT_ERROR = str(exc)


def _qt_to_ns_frame(parent_view, x: float, y: float, w: float, h: float):
    """Convert a top-left Qt rect (x, y, w, h) into parent_view's Cocoa coordinate space."""
    fx, fy, fw, fh = float(x), float(y), float(w), float(h)
    try:
        if parent_view is not None and not parent_view.isFlipped():
            ph = float(parent_view.bounds().size.height)
            fy = ph - fy - fh
    except Exception:
        pass
    return ((fx, fy), (fw, fh))


def _enable_strict_layer_clipping(ns_view) -> None:
    """Ensure subviews/layers are strictly clipped on macOS 13/14/15+."""
    if ns_view is None:
        return
    try:
        ns_view.setWantsLayer_(True)
    except Exception:
        pass
    try:
        if hasattr(ns_view, "setClipsToBounds_"):
            ns_view.setClipsToBounds_(True)
    except Exception:
        pass
    try:
        layer = ns_view.layer()
        if layer is not None:
            layer.setMasksToBounds_(True)
    except Exception:
        pass


class MacAVPlayerWidget(QWidget):
    """Alien-QWidget-backed AVPlayerView mounted on the top-level window's NSView."""

    positionChanged = Signal(int)
    durationChanged = Signal(int)
    backendError = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # IMPORTANT: Do NOT set Qt.WA_NativeWindow or call self.winId() on this deep
        # child widget. Keeping this widget alien prevents Qt from allocating dozens of
        # Retina 'Qt Raster Backingstore' IOSurface buffers (~1.1 GB) on ancestor containers.
        self.setStyleSheet("background:#000;border:none;")
        self._available = False
        self._player = None
        self._player_view = None
        self._ns_view = None
        self._clip_view = None
        self._stage_view = None
        self._backdrop_box = None
        self._host_top_win_ref = None
        self._watched_ancestor_refs: list[weakref.ReferenceType[QWidget]] = []
        self._geometry_sync_queued = False
        self._clip_view_hidden = True
        self._last_applied_geom = None
        self._last_duration = -1
        self._last_position = -1
        self._fullscreen = False
        self._playback_rate = 1.0
        self._transform_values = {'ZoomX': 1.0, 'ZoomY': 1.0, 'Pan': 0.0, 'Tilt': 0.0, 'width': 720, 'height': 1280}
        self._next_source = ''
        self._next_asset = None
        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._poll_time)
        # The backend is created on first visible use, never at hidden-page startup.

    def _set_clip_hidden(self, hidden: bool) -> None:
        flag = bool(hidden)
        if self._clip_view is not None and (self._clip_view_hidden != flag or bool(self._clip_view.isHidden()) != flag):
            try:
                self._clip_view.setHidden_(flag)
            except Exception:
                pass
        self._clip_view_hidden = flag
        if flag:
            self._last_applied_geom = None

    def _clear_ancestor_filters(self) -> None:
        for ref in self._watched_ancestor_refs:
            anc = ref()
            if anc is not None:
                try:
                    anc.removeEventFilter(self)
                except Exception:
                    pass
        self._watched_ancestor_refs.clear()

    def _sync_host_hierarchy(self) -> bool:
        """Bind _clip_view to the top-level window's existing QNSView and watch ancestors."""
        top_win = self.window()
        if top_win is None or not top_win.isWindow():
            return False
        cur_top = self._host_top_win_ref() if self._host_top_win_ref is not None else None
        if cur_top is not top_win or self._ns_view is None:
            ptr = int(top_win.winId())
            if not ptr:
                return False
            new_ns_view = objc.objc_object(c_void_p=c_void_p(ptr))
            if self._clip_view is not None and self._clip_view.superview() is not new_ns_view:
                try:
                    self._clip_view.removeFromSuperview()
                except Exception:
                    pass
                new_ns_view.addSubview_(self._clip_view)
                _enable_strict_layer_clipping(self._clip_view)
                _enable_strict_layer_clipping(self._stage_view)
            self._ns_view = new_ns_view
            self._host_top_win_ref = weakref.ref(top_win)
            self._last_applied_geom = None

        # Ensure every ancestor up to top_win has our lightweight geometry/visibility filter.
        wanted: list[QWidget] = []
        anc = self.parentWidget()
        while anc is not None:
            wanted.append(anc)
            if anc is top_win:
                break
            anc = anc.parentWidget()
        if top_win is not self and (not wanted or wanted[-1] is not top_win):
            wanted.append(top_win)

        existing_live = {w for ref in self._watched_ancestor_refs if (w := ref()) is not None}
        wanted_set = set(wanted)
        if existing_live != wanted_set:
            for old_w in existing_live - wanted_set:
                try:
                    old_w.removeEventFilter(self)
                except Exception:
                    pass
            for new_w in wanted:
                if new_w not in existing_live:
                    try:
                        new_w.installEventFilter(self)
                    except Exception:
                        pass
            self._watched_ancestor_refs = [weakref.ref(w) for w in wanted]
        return True

    def _queue_geometry_sync(self) -> None:
        if self._geometry_sync_queued or not self._available:
            return
        self._geometry_sync_queued = True
        QTimer.singleShot(0, self._flush_geometry_sync)

    def _flush_geometry_sync(self) -> None:
        self._geometry_sync_queued = False
        if self._available:
            self._sync_host_hierarchy()
            self._apply_transform_frame()

    def eventFilter(self, watched, event):
        if self._available:
            et = event.type()
            if et in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show, QEvent.Type.Hide):
                self._apply_transform_frame()
            elif et in (QEvent.Type.LayoutRequest, QEvent.Type.ParentChange, QEvent.Type.WindowStateChange):
                self._queue_geometry_sync()
            elif et == QEvent.Type.Close:
                top_win = self._host_top_win_ref() if self._host_top_win_ref is not None else None
                if watched is top_win:
                    self.close_native()
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        if self._available:
            self._sync_host_hierarchy()
            self._apply_transform_frame()
            self._queue_geometry_sync()
            self._poll.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._available:
            self._apply_transform_frame()

    def moveEvent(self, event):
        super().moveEvent(event)
        if self._available:
            self._apply_transform_frame()

    def set_transform(self, values):
        from app.services import clip_transform as transforms
        self._transform_values = transforms.validate(values)
        self._last_applied_geom = None
        self._apply_transform_frame()

    def _apply_transform_frame(self):
        if not self._available or self._ns_view is None or self._clip_view is None or self._stage_view is None or self._player_view is None:
            return
        try:
            if self._fullscreen:
                try:
                    if hasattr(self._player_view, "isInFullScreenMode") and not self._player_view.isInFullScreenMode():
                        self._fullscreen = False
                    else:
                        return
                except Exception:
                    return

            top_win = self.window()
            if (
                top_win is None
                or not top_win.isWindow()
                or not self.isVisible()
                or not top_win.isVisible()
                or self.width() <= 0
                or self.height() <= 0
            ):
                self._set_clip_hidden(True)
                return

            cur_top = self._host_top_win_ref() if self._host_top_win_ref is not None else None
            if cur_top is not top_win:
                if not self._sync_host_hierarchy():
                    self._set_clip_hidden(True)
                    return

            if top_win is self:
                full_rect = QRect(0, 0, self.width(), self.height())
                vis_rect = QRect(full_rect)
            else:
                origin = self.mapTo(top_win, QPoint(0, 0))
                full_rect = QRect(origin, self.size())
                vis_rect = full_rect.intersected(QRect(0, 0, top_win.width(), top_win.height()))
                anc = self.parentWidget()
                while anc is not None and anc is not top_win:
                    if not anc.isVisible():
                        self._set_clip_hidden(True)
                        return
                    anc_rect = QRect(anc.mapTo(top_win, QPoint(0, 0)), anc.size())
                    vis_rect = vis_rect.intersected(anc_rect)
                    if vis_rect.isEmpty():
                        self._set_clip_hidden(True)
                        return
                    anc = anc.parentWidget()

            if vis_rect.width() <= 0 or vis_rect.height() <= 0 or full_rect.width() <= 0 or full_rect.height() <= 0:
                self._set_clip_hidden(True)
                return

            v = getattr(self, '_transform_values', None) or {'ZoomX': 1.0, 'Pan': 0.0, 'Tilt': 0.0, 'width': 720, 'height': 1280}
            zoom = float(v.get('ZoomX', 1.0) or 1.0)
            pan = float(v.get('Pan', 0.0) or 0.0)
            tilt = float(v.get('Tilt', 0.0) or 0.0)
            tw = float(v.get('width', 720) or 720)
            th = float(v.get('height', 1280) or 1280)

            geom_key = (
                vis_rect.x(), vis_rect.y(), vis_rect.width(), vis_rect.height(),
                full_rect.x(), full_rect.y(), full_rect.width(), full_rect.height(),
                top_win.height(),
                round(zoom, 5), round(pan, 3), round(tilt, 3), round(tw, 2), round(th, 2),
            )
            if geom_key == self._last_applied_geom and not self._clip_view_hidden:
                return
            self._last_applied_geom = geom_key

            # 1. Outer viewport-clipped container in top-level QNSView coordinates
            self._clip_view.setFrame_(
                _qt_to_ns_frame(self._ns_view, vis_rect.x(), vis_rect.y(), vis_rect.width(), vis_rect.height())
            )
            _enable_strict_layer_clipping(self._clip_view)

            # 2. Full widget stage inside _clip_view (offset when scrolled partially out of view)
            stage_x = full_rect.x() - vis_rect.x()
            stage_y = full_rect.y() - vis_rect.y()
            W = float(full_rect.width())
            H = float(full_rect.height())
            self._stage_view.setFrame_(
                _qt_to_ns_frame(self._clip_view, stage_x, stage_y, W, H)
            )
            _enable_strict_layer_clipping(self._stage_view)

            # 3. Backdrop + transformed AVPlayerView inside _stage_view
            if self._backdrop_box is not None:
                try:
                    self._backdrop_box.setFrame_(_qt_to_ns_frame(self._stage_view, 0.0, 0.0, W, H))
                except Exception:
                    pass

            w = W * zoom
            h = H * zoom
            qt_x = (W - w) / 2.0 + pan * W / tw
            qt_y = (H - h) / 2.0 - tilt * H / th
            self._player_view.setFrame_(_qt_to_ns_frame(self._stage_view, qt_x, qt_y, w, h))

            self._set_clip_hidden(False)
        except Exception:
            pass

    def hideEvent(self, event):
        self._poll.stop()
        if self._player is not None:
            try:
                self._player.pause()
            except Exception:
                pass
        self._set_clip_hidden(True)
        super().hideEvent(event)

    @property
    def available(self) -> bool:
        return bool(self._available)

    @property
    def import_error(self) -> str:
        return _MAC_IMPORT_ERROR

    def _ensure_backend(self) -> bool:
        if self._available:
            self._sync_host_hierarchy()
            return True
        if not MAC_AVPLAYER_AVAILABLE:
            return False
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.platformName().lower() != "cocoa":
            return False
        try:
            top_win = self.window()
            if top_win is None or not top_win.isWindow():
                return False
            # Attach ONLY to the top-level window's already-existing QNSView.
            # Never call self.winId() on this deep child widget!
            ptr = int(top_win.winId())
            if not ptr:
                return False
            self._ns_view = objc.objc_object(c_void_p=c_void_p(ptr))
            self._host_top_win_ref = weakref.ref(top_win)

            view_cls = _PassthroughClipView if _PassthroughClipView is not None else AppKit.NSView
            init_rect = ((0.0, 0.0), (1.0, 1.0))

            clip_view = view_cls.alloc().initWithFrame_(init_rect)
            clip_view.setAutoresizingMask_(0)
            clip_view.setHidden_(True)
            _enable_strict_layer_clipping(clip_view)

            stage_view = view_cls.alloc().initWithFrame_(init_rect)
            stage_view.setAutoresizingMask_(0)
            _enable_strict_layer_clipping(stage_view)
            clip_view.addSubview_(stage_view)

            try:
                backdrop = AppKit.NSBox.alloc().initWithFrame_(init_rect)
                backdrop.setBoxType_(AppKit.NSBoxCustom)
                backdrop.setTitlePosition_(AppKit.NSNoTitle)
                backdrop.setContentViewMargins_((0.0, 0.0))
                backdrop.setFillColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.06, 0.09, 0.16, 1.0))
                backdrop.setBorderColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.23, 0.51, 0.96, 1.0))
                backdrop.setBorderWidth_(1.5)
                backdrop.setAutoresizingMask_(0)
                stage_view.addSubview_(backdrop)
                self._backdrop_box = backdrop
            except Exception:
                self._backdrop_box = None

            self._player = AVFoundation.AVPlayer.alloc().init()
            try:
                self._player.setActionAtItemEnd_(AVFoundation.AVPlayerActionAtItemEndPause)
            except Exception:
                pass
            try:
                if hasattr(self._player, "setDefaultRate_"):
                    self._player.setDefaultRate_(float(self._playback_rate))
            except Exception:
                pass

            self._player_view = AVKit.AVPlayerView.alloc().initWithFrame_(init_rect)
            self._player_view.setPlayer_(self._player)
            try:
                self._player_view.setControlsStyle_(AVKit.AVPlayerViewControlsStyleNone)
            except Exception:
                pass
            try:
                self._player_view.setAutoresizingMask_(0)
            except Exception:
                pass
            try:
                self._player_view.setShowsFullScreenToggleButton_(False)
            except Exception:
                pass
            try:
                if hasattr(self._player_view, "setRefusesFirstResponder_"):
                    self._player_view.setRefusesFirstResponder_(True)
            except Exception:
                pass

            stage_view.addSubview_(self._player_view)
            self._ns_view.addSubview_(clip_view)
            _enable_strict_layer_clipping(clip_view)
            _enable_strict_layer_clipping(stage_view)

            self._clip_view = clip_view
            self._stage_view = stage_view
            self._clip_view_hidden = True
            self._last_applied_geom = None
            self._available = True

            self._sync_host_hierarchy()
            self._apply_transform_frame()
            self._queue_geometry_sync()
            if self.isVisible():
                self._poll.start()
            return True
        except Exception as exc:  # pragma: no cover - macOS native failure path
            self.close_native()
            self.backendError.emit(str(exc))
            return False

    def set_source(self, source, autoplay: bool = True) -> bool:
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
            try:
                if hasattr(item, "setAudioTimePitchAlgorithm_"):
                    item.setAudioTimePitchAlgorithm_(AVFoundation.AVAudioTimePitchAlgorithmTimeDomain)
            except Exception:
                pass
            self._player.replaceCurrentItemWithPlayerItem_(item)
            self._last_duration = -1
            self._last_position = -1
            self.durationChanged.emit(0)
            self.positionChanged.emit(0)
            try:
                if hasattr(self._player, "setDefaultRate_"):
                    self._player.setDefaultRate_(float(self._playback_rate))
            except Exception:
                pass
            if autoplay:
                self._player.play()
                if self._playback_rate != 1.0:
                    try:
                        self._player.setRate_(float(self._playback_rate))
                    except Exception:
                        pass
            else:
                self._player.pause()
            self._apply_transform_frame()
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
            if self._playback_rate != 1.0:
                try:
                    self._player.setRate_(float(self._playback_rate))
                except Exception:
                    pass

    def set_playback_rate(self, rate: float):
        try:
            r = float(rate or 1.0)
        except Exception:
            r = 1.0
        self._playback_rate = r if r > 0 else 1.0
        if self._player is not None:
            try:
                if hasattr(self._player, "setDefaultRate_"):
                    self._player.setDefaultRate_(self._playback_rate)
            except Exception:
                pass
            if self.is_playing():
                try:
                    self._player.setRate_(self._playback_rate)
                except Exception:
                    pass

    def playback_rate(self) -> float:
        return float(self._playback_rate)

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
            cm_target = CoreMedia.CMTimeMakeWithSeconds(target, 600)
            if target <= 0.0:
                self._player.seekToTime_toleranceBefore_toleranceAfter_(cm_target, cm_target, cm_target)
            else:
                self._player.seekToTime_(cm_target)
            self.positionChanged.emit(int(target * 1000))
        except Exception as exc:  # pragma: no cover
            self.backendError.emit(str(exc))

    def toggle_fullscreen(self) -> bool:
        if not self._ensure_backend() or self._player_view is None:
            return False
        try:
            in_fs = bool(self._fullscreen)
            try:
                if hasattr(self._player_view, "isInFullScreenMode"):
                    in_fs = bool(self._player_view.isInFullScreenMode())
            except Exception:
                pass
            if in_fs:
                self._player_view.exitFullScreenModeWithOptions_(None)
                self._fullscreen = False
                self._last_applied_geom = None
                self._apply_transform_frame()
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
        if self._fullscreen and self._player_view is not None:
            try:
                if hasattr(self._player_view, "isInFullScreenMode") and not self._player_view.isInFullScreenMode():
                    self._fullscreen = False
                    self._last_applied_geom = None
                    self._apply_transform_frame()
            except Exception:
                pass
        if self.is_playing() and self._playback_rate > 0:
            try:
                if abs(float(self._player.rate()) - self._playback_rate) > 0.05:
                    self._player.setRate_(float(self._playback_rate))
            except Exception:
                pass
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
        self._clear_ancestor_filters()
        try:
            if self._fullscreen and self._player_view is not None:
                try:
                    self._player_view.exitFullScreenModeWithOptions_(None)
                except Exception:
                    pass
                self._fullscreen = False
            if self._player is not None:
                self._player.pause()
                self._player.replaceCurrentItemWithPlayerItem_(None)
            for view in (self._player_view, self._backdrop_box, self._stage_view, self._clip_view):
                if view is not None:
                    try:
                        view.removeFromSuperview()
                    except Exception:
                        pass
        except Exception:
            pass
        self._player_view = None
        self._backdrop_box = None
        self._stage_view = None
        self._clip_view = None
        self._player = None
        self._ns_view = None
        self._host_top_win_ref = None
        self._clip_view_hidden = True
        self._last_applied_geom = None
        self._available = False

    def closeEvent(self, event):
        self.close_native()
        super().closeEvent(event)
