from __future__ import annotations

import hashlib
import json
import os
import shutil
from app.services import quiet_process as subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class RemotionStatus:
    ok: bool
    project_dir: str = ""
    runner: str = ""
    version: str = ""
    node_version: str = ""
    message: str = ""
    detail: str = ""


class RemotionRenderer:
    """Direct local Remotion adapter used only by the Video Packaging workspace.

    The adapter deliberately stays isolated from Flow scheduling, QC, Resolve and the
    database.  It uses the Remotion CLI already installed in a user-managed project.
    No background daemon and no permanent Bridge process are required.
    """

    TEMPLATE_DIR = ".flowstudio-remotion"
    TEMPLATE_ENTRY = "Root.tsx"
    ASSET_DIR = "flowstudio-assets"

    def __init__(self, project_dir: str = ""):
        self.project_dir = str(project_dir or "").strip()

    @staticmethod
    def _candidate_dirs():
        home = Path.home()
        env = os.environ.get("FLOW_STUDIO_REMOTION_DIR", "").strip()
        if env:
            yield Path(env).expanduser()
        for p in (
            home / "FlowStudio_Engine",
            home / "Remotion",
            home / "remotion",
            home / "Documents" / "FlowStudio_Engine",
            home / "Documents" / "Remotion",
            home / "Documents" / "remotion",
            home / "Projects" / "FlowStudio_Engine",
            home / "Projects" / "Remotion",
            home / "Projects" / "remotion",
            home / "Developer" / "FlowStudio_Engine",
            home / "Developer" / "Remotion",
            home / "Developer" / "remotion",
        ):
            yield p

    @classmethod
    def autodetect(cls) -> str:
        for p in cls._candidate_dirs():
            if cls._looks_like_project(p):
                return str(p)
        return ""

    @staticmethod
    def _looks_like_project(path: Path) -> bool:
        return path.is_dir() and (path / "package.json").is_file()

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _resolve_runner(self, root: Path) -> Optional[Path]:
        for rel in (("node_modules/.bin/remotion.cmd",) if os.name == "nt" else ("node_modules/.bin/remotion",)):
            p = root / rel
            if p.exists():
                return p
        return None

    def _detect_version(self, root: Path) -> str:
        # --version is not stable across all Remotion CLI releases.  Read the local
        # package metadata first so Help output can never be mistaken for a failure.
        for rel in (
            "node_modules/@remotion/cli/package.json",
            "node_modules/remotion/package.json",
        ):
            data = self._read_json(root / rel)
            if data.get("version"):
                return str(data["version"])
        package = self._read_json(root / "package.json")
        deps = {}
        deps.update(package.get("dependencies") or {})
        deps.update(package.get("devDependencies") or {})
        for key in ("@remotion/cli", "remotion"):
            value = str(deps.get(key) or "").strip()
            if value:
                return value
        return "已安装"

    def check(self) -> RemotionStatus:
        raw = self.project_dir or self.autodetect()
        if not raw:
            return RemotionStatus(False, message="未找到 Remotion 项目目录，请选择包含 package.json 的项目目录。")
        root = Path(raw).expanduser().resolve()
        if not self._looks_like_project(root):
            return RemotionStatus(False, str(root), message="所选目录缺少 package.json，不是有效的 Remotion 项目。")
        runner = self._resolve_runner(root)
        if not runner:
            return RemotionStatus(False, str(root), message="未找到 node_modules/.bin/remotion，请确认该项目已执行 npm install。")
        node = shutil.which("node")
        if not node:
            return RemotionStatus(False, str(root), str(runner), message="未找到 Node.js，请确认 node 可从终端直接运行。")

        try:
            node_cp = subprocess.run([node, "--version"], text=True, capture_output=True, timeout=8, check=False)
            node_version = (node_cp.stdout or node_cp.stderr or "").strip()
        except Exception:
            node_version = ""

        version = self._detect_version(root)
        try:
            cp = subprocess.run(
                [str(runner), "help"],
                cwd=str(root), text=True, capture_output=True, timeout=15, check=False,
            )
            combined = ((cp.stdout or "") + "\n" + (cp.stderr or "")).strip()
            if cp.returncode != 0:
                return RemotionStatus(
                    False, str(root), str(runner), version, node_version,
                    "Remotion CLI 无法正常启动。", combined[-1200:],
                )
            return RemotionStatus(
                True, str(root), str(runner), version, node_version,
                "Remotion 已连接 · CLI 可用 · 本地直接调用",
                "CLI help 探测成功",
            )
        except Exception as exc:
            return RemotionStatus(
                False, str(root), str(runner), version, node_version,
                f"Remotion 检测异常：{exc}",
            )

    def probe_duration(self, media_path: str) -> float:
        """Return media duration in seconds using Remotion's bundled ffprobe wrapper."""
        status = self.check()
        if not status.ok:
            return 0.0
        p = Path(media_path).expanduser()
        if not p.is_file():
            return 0.0
        try:
            cp = subprocess.run(
                [status.runner, "ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
                cwd=status.project_dir, text=True, capture_output=True, timeout=20, check=False,
            )
            if cp.returncode == 0:
                for line in (cp.stdout or "").splitlines():
                    try:
                        value = float(line.strip())
                        if value > 0:
                            return value
                    except Exception:
                        continue
        except Exception:
            pass
        return 0.0

    def ensure_flowstudio_template(self) -> Path:
        status = self.check()
        if not status.ok:
            raise RuntimeError(status.message)
        root = Path(status.project_dir)
        target = root / self.TEMPLATE_DIR
        target.mkdir(parents=True, exist_ok=True)
        entry = target / self.TEMPLATE_ENTRY
        entry.write_text(_FLOW_STUDIO_REMOTION_TEMPLATE, encoding="utf-8")
        (root / "public" / self.ASSET_DIR).mkdir(parents=True, exist_ok=True)
        return entry

    def _public_asset(self, root: Path, source: str) -> str:
        text = str(source or "").strip()
        if not text:
            return ""
        if text.startswith(("http://", "https://", "data:")):
            return text
        src = Path(text).expanduser().resolve()
        if not src.is_file():
            return ""
        digest = hashlib.sha1(str(src).encode("utf-8", errors="ignore")).hexdigest()[:14]
        safe_suffix = src.suffix.lower()[:12]
        name = f"{digest}{safe_suffix}"
        public_dir = root / "public" / self.ASSET_DIR
        public_dir.mkdir(parents=True, exist_ok=True)
        dst = public_dir / name
        if not dst.exists():
            try:
                os.symlink(str(src), str(dst))
            except Exception:
                try:
                    os.link(str(src), str(dst))
                except Exception:
                    shutil.copy2(str(src), str(dst))
        return f"{self.ASSET_DIR}/{name}"

    def prepare_flowstudio_props(self, payload: dict[str, Any]) -> tuple[dict[str, Any], RemotionStatus]:
        status = self.check()
        if not status.ok:
            raise RuntimeError(status.message)
        root = Path(status.project_dir)
        self.ensure_flowstudio_template()
        props = json.loads(json.dumps(payload, ensure_ascii=False))

        props["source"] = self._public_asset(root, props.get("source", ""))
        watermark = props.get("watermark") or {}
        if watermark.get("path"):
            watermark["path"] = self._public_asset(root, watermark["path"])
        props["watermark"] = watermark

        for item in props.get("broll") or []:
            if item.get("path"):
                item["path"] = self._public_asset(root, item["path"])
        for key in ("intro", "outro"):
            item = props.get(key) or {}
            if item.get("path"):
                item["path"] = self._public_asset(root, item["path"])
            props[key] = item
        return props, status

    @staticmethod
    def composition_for_ratio(ratio: str) -> str:
        return {
            "16:9": "FlowStudioPackaging169",
            "1:1": "FlowStudioPackaging11",
        }.get(str(ratio), "FlowStudioPackaging916")

    def render_flowstudio_command(self, payload: dict[str, Any], output_path: str):
        props, status = self.prepare_flowstudio_props(payload)
        output = str(Path(output_path).expanduser())
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        entry = str(Path(status.project_dir) / self.TEMPLATE_DIR / self.TEMPLATE_ENTRY)
        composition = self.composition_for_ratio(props.get("ratio", "9:16"))
        cmd = [status.runner, "render", entry, composition, output,
               "--props", json.dumps(props, ensure_ascii=False, separators=(",", ":"))]
        return cmd, status.project_dir

    def render_command(self, composition: str, output_path: str, props: Optional[dict] = None):
        """Compatibility path for an arbitrary user composition."""
        status = self.check()
        if not status.ok:
            raise RuntimeError(status.message)
        composition = str(composition or "").strip()
        if not composition:
            raise ValueError("必须填写 Composition ID。")
        output = str(Path(output_path).expanduser())
        cmd = [status.runner, "render", composition, output]
        if props:
            cmd += ["--props", json.dumps(props, ensure_ascii=False, separators=(",", ":"))]
        return cmd, status.project_dir


_FLOW_STUDIO_REMOTION_TEMPLATE = r'''import React from 'react';
import {
  AbsoluteFill,
  Composition,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  registerRoot,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

type OverlayAsset = {path?: string; enabled?: boolean; duration?: number};
type Broll = {path?: string; start?: number; end?: number; fit?: string};
type CaptionWord = {text?: string; start?: number; end?: number};
type Caption = {text?: string; start?: number; end?: number; words?: CaptionWord[]};
type Props = {
  source?: string;
  mainDuration?: number;
  totalDuration?: number;
  ratio?: string;
  watermark?: {path?: string; enabled?: boolean; position?: string; scale?: number; opacity?: number};
  title?: {text?: string; enabled?: boolean; position?: string; size?: number; color?: string; background?: boolean};
  captions?: Caption[];
  captionStyle?: {
    preset?: string; font?: string; size?: number; color?: string; background?: boolean; backgroundColor?: string; backgroundOpacity?: number;
    position?: string; weight?: number; strokeColor?: string; strokeWidth?: number; shadow?: boolean; shadowColor?: string; shadowBlur?: number; shadowY?: number;
    radius?: number; paddingX?: number; paddingY?: number; animation?: string; maxWidth?: number; lineHeight?: number; letterSpacing?: number;
    karaokeEnabled?: boolean; karaokeMode?: string; karaokeActiveColor?: string; karaokeReadColor?: string; karaokeUnreadColor?: string;
    karaokeActiveScale?: number; karaokeTiming?: string;
  };
  broll?: Broll[];
  intro?: OverlayAsset;
  outro?: OverlayAsset;
};

const asset = (p?: string) => !p ? '' : (/^(https?:|data:)/.test(p) ? p : staticFile(p));
const isImage = (p?: string) => !!p && /\.(png|jpe?g|webp|gif|bmp)$/i.test(p);
const withAlpha = (color = '#000000', opacity = 55) => {
  const a = Math.max(0, Math.min(1, Number(opacity || 0) / 100));
  const m = String(color).trim().match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
  if (!m) return color;
  return `rgba(${parseInt(m[1],16)},${parseInt(m[2],16)},${parseInt(m[3],16)},${a})`;
};

const posStyle = (pos = '右上'): React.CSSProperties => {
  const s: React.CSSProperties = {position: 'absolute'};
  if (pos.includes('左')) s.left = 48; else if (pos.includes('右')) s.right = 48; else {s.left = '50%'; s.transform = 'translateX(-50%)';}
  if (pos.includes('上')) s.top = 60; else if (pos.includes('下') || pos.includes('底')) s.bottom = 80; else {s.top = '50%'; s.transform = (String(s.transform || '') + ' translateY(-50%)').trim();}
  return s;
};

const Media = ({src, muted = false, fit = 'cover'}: {src: string; muted?: boolean; fit?: string}) => {
  if (!src) return null;
  if (isImage(src)) return <Img src={asset(src)} style={{width:'100%',height:'100%',objectFit:fit as any}}/>;
  return <OffthreadVideo src={asset(src)} muted={muted} style={{width:'100%',height:'100%',objectFit:fit as any}}/>;
};

const Packaging: React.FC<Props> = (p) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const introSec = p.intro?.enabled && p.intro?.path ? Math.max(0, Number(p.intro.duration || 0)) : 0;
  const outroSec = p.outro?.enabled && p.outro?.path ? Math.max(0, Number(p.outro.duration || 0)) : 0;
  const mainSec = Math.max(0.1, Number(p.mainDuration || 30));
  const introF = Math.round(introSec * fps);
  const mainF = Math.round(mainSec * fps);
  const outroF = Math.round(outroSec * fps);
  const relFrame = frame - introF;
  const relSec = relFrame / fps;

  const currentCaption = (p.captions || []).find((c) => relSec >= Number(c.start || 0) && relSec < Number(c.end ?? mainSec));
  const cap = p.captionStyle || {};
  const capStart = Number(currentCaption?.start || 0);
  const capEnd = Number(currentCaption?.end ?? mainSec);
  const capLocalFrame = Math.max(0, Math.round((relSec - capStart) * fps));
  const capDurationFrames = Math.max(1, Math.round(Math.max(0.1, capEnd - capStart) * fps));
  const enterFrames = Math.max(3, Math.min(Math.round(fps * 0.22), Math.floor(capDurationFrames / 3)));
  const anim = String(cap.animation || '淡入');
  let capOpacity = 1;
  let capTransform = '';
  if (anim === '淡入') {
    capOpacity = interpolate(capLocalFrame, [0, enterFrames], [0, 1], {extrapolateRight:'clamp'});
  } else if (anim === '弹入') {
    const v = spring({frame: capLocalFrame, fps, config:{damping:13, stiffness:180, mass:0.65}});
    capOpacity = interpolate(capLocalFrame, [0, Math.max(2, enterFrames / 2)], [0, 1], {extrapolateRight:'clamp'});
    capTransform = `scale(${0.82 + 0.18 * v})`;
  } else if (anim === '上滑') {
    const y = interpolate(capLocalFrame, [0, enterFrames], [28, 0], {extrapolateRight:'clamp'});
    capOpacity = interpolate(capLocalFrame, [0, enterFrames], [0, 1], {extrapolateRight:'clamp'});
    capTransform = `translateY(${y}px)`;
  } else if (anim === '轻微放大') {
    const sc = interpolate(capLocalFrame, [0, enterFrames], [0.94, 1], {extrapolateRight:'clamp'});
    capOpacity = interpolate(capLocalFrame, [0, enterFrames], [0, 1], {extrapolateRight:'clamp'});
    capTransform = `scale(${sc})`;
  }
  const title = p.title || {};
  const wm = p.watermark || {};

  const captionText = String(currentCaption?.text || '');
  const explicitWords = Array.isArray(currentCaption?.words) ? (currentCaption?.words || []).filter((w) => String(w?.text || '').trim()) : [];
  const estimatedWords = captionText.trim() ? captionText.trim().split(/\s+/).map((text, i, arr) => ({
    text,
    start: capStart + (Math.max(0.001, capEnd - capStart) * i / Math.max(1, arr.length)),
    end: capStart + (Math.max(0.001, capEnd - capStart) * (i + 1) / Math.max(1, arr.length)),
  })) : [];
  const wordItems = explicitWords.length ? explicitWords.map((w) => {
    let start = Number(w.start ?? 0);
    let end = Number(w.end ?? start);
    const capDur = Math.max(0.001, capEnd - capStart);
    // Accept both absolute video time and caption-relative word time.
    if (start < capStart - 0.001 && start >= 0 && start <= capDur + 0.001) { start += capStart; end += capStart; }
    return {text:String(w.text || ''), start, end:Math.max(start + 0.001, end)};
  }) : estimatedWords;
  let activeWord = -1;
  if (wordItems.length && cap.karaokeEnabled) {
    activeWord = wordItems.findIndex((w) => relSec >= Number(w.start) && relSec < Number(w.end));
    if (activeWord < 0) {
      const next = wordItems.findIndex((w) => relSec < Number(w.start));
      activeWord = next >= 0 ? next : wordItems.length - 1;
    }
  }

  return <AbsoluteFill style={{backgroundColor:'#000', fontFamily:'Arial, sans-serif'}}>
    {introF > 0 && <Sequence from={0} durationInFrames={introF}><Media src={p.intro?.path || ''}/></Sequence>}
    <Sequence from={introF} durationInFrames={mainF}>
      <AbsoluteFill><Media src={p.source || ''}/></AbsoluteFill>
      {(p.broll || []).map((b, i) => {
        const from = Math.max(0, Math.round(Number(b.start || 0) * fps));
        const to = Math.max(from + 1, Math.round(Number(b.end || 0) * fps));
        return b.path ? <Sequence key={i} from={from} durationInFrames={to-from}>
          <AbsoluteFill><Media src={b.path} muted={true} fit={b.fit || 'cover'}/></AbsoluteFill>
        </Sequence> : null;
      })}
      {wm.enabled && wm.path && <Img src={asset(wm.path)} style={{...posStyle(wm.position || '右上'), width:`${Math.max(4, Number(wm.scale || 18))}%`, opacity: Math.max(0, Math.min(1, Number(wm.opacity ?? 0.92))), objectFit:'contain'}}/>}
      {title.enabled && title.text && <div style={{...posStyle(title.position || '顶部居中'), color:title.color || '#FFFFFF', fontSize:Number(title.size || 58), fontWeight:800, textAlign:'center', padding:'14px 22px', borderRadius:18, background:title.background ? 'rgba(0,0,0,.52)' : 'transparent', maxWidth:'86%', lineHeight:1.2}}>{title.text}</div>}
      {currentCaption?.text && <div style={{
        ...posStyle(cap.position || '底部居中'),
        color:cap.color || '#FFFFFF',
        fontFamily:cap.font || 'Arial, sans-serif',
        fontSize:Number(cap.size || 54),
        fontWeight:Number(cap.weight || 800),
        textAlign:'center',
        WebkitTextStroke:`${Math.max(0, Number(cap.strokeWidth || 0))}px ${cap.strokeColor || '#000000'}`,
        paintOrder:'stroke fill',
        textShadow:cap.shadow === false ? 'none' : `0 ${Number(cap.shadowY ?? 4)}px ${Number(cap.shadowBlur ?? 10)}px ${cap.shadowColor || 'rgba(0,0,0,.9)'}`,
        background:cap.background ? withAlpha(cap.backgroundColor || '#000000', Number(cap.backgroundOpacity ?? 55)) : 'transparent',
        borderRadius:Number(cap.radius ?? 16),
        padding:`${Number(cap.paddingY ?? 10)}px ${Number(cap.paddingX ?? 18)}px`,
        maxWidth:`${Math.max(50, Math.min(96, Number(cap.maxWidth || 88)))}%`,
        lineHeight:Number(cap.lineHeight || 1.22),
        letterSpacing:Number(cap.letterSpacing || 0),
        opacity:capOpacity,
        transform:[String((posStyle(cap.position || '底部居中') as any).transform || ''), capTransform].filter(Boolean).join(' '),
      }}>{cap.karaokeEnabled && wordItems.length ? wordItems.map((word, i) => {
        const active = i === activeWord;
        const read = i < activeWord;
        const wordColor = active ? (cap.karaokeActiveColor || '#FFD54A') : (read ? (cap.karaokeReadColor || '#FFFFFF') : (cap.karaokeUnreadColor || '#C9C9C9'));
        const scale = active ? Math.max(1, Number(cap.karaokeActiveScale || 110) / 100) : 1;
        return <React.Fragment key={`${i}-${word.text}`}><span style={{display:'inline-block', color:wordColor, transform:`scale(${scale})`, transformOrigin:'50% 75%', transition:'none'}}>{word.text}</span>{i < wordItems.length-1 ? ' ' : ''}</React.Fragment>;
      }) : currentCaption.text}</div>}
    </Sequence>
    {outroF > 0 && <Sequence from={introF + mainF} durationInFrames={outroF}><Media src={p.outro?.path || ''}/></Sequence>}
  </AbsoluteFill>;
};

const defaultProps: Props = {source:'',mainDuration:30,totalDuration:30,ratio:'9:16',watermark:{},title:{},captions:[],captionStyle:{},broll:[],intro:{},outro:{}};
const calc = async ({props}: {props: Props}) => ({durationInFrames: Math.max(1, Math.ceil(Number(props.totalDuration || props.mainDuration || 30) * 30))});

const Root: React.FC = () => <>
  <Composition id="FlowStudioPackaging916" component={Packaging} width={1080} height={1920} fps={30} durationInFrames={900} defaultProps={defaultProps} calculateMetadata={calc as any}/>
  <Composition id="FlowStudioPackaging169" component={Packaging} width={1920} height={1080} fps={30} durationInFrames={900} defaultProps={{...defaultProps,ratio:'16:9'}} calculateMetadata={calc as any}/>
  <Composition id="FlowStudioPackaging11" component={Packaging} width={1080} height={1080} fps={30} durationInFrames={900} defaultProps={{...defaultProps,ratio:'1:1'}} calculateMetadata={calc as any}/>
</>;
registerRoot(Root);
'''
