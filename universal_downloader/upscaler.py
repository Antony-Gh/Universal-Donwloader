"""Local HD image enhancement & optional ONNX neural super-resolution pipeline."""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageChops, ImageEnhance, ImageFilter

LOGGER = logging.getLogger("universal_downloader")


def compute_hd_target_dimensions(
    width: int,
    height: int,
    target_min_side: int = 960,
    max_scale: float = 4.0,
) -> tuple[int, int]:
    """Calculate aspect-preserving HD target dimensions (up to 4x, aiming for >=960px on the longest side)."""
    longest = max(width, height)
    if longest <= 0 or longest >= target_min_side:
        return width, height
    scale = min(max_scale, target_min_side / float(longest))
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def find_local_onnx_upscaler(explicit_path: Optional[Path] = None) -> Optional[Path]:
    """
    Locate an optional local ONNX super-resolution model (e.g. Real-ESRGAN, SwinIR, 4x-UltraSharp, FSRCNN).
    Checks explicit path, UD_UPSCALER_MODEL env var, user app-data models folder, and workspace models folder.
    """
    candidates: list[Path] = []
    if explicit_path is not None:
        candidates.append(explicit_path)

    env_path = os.environ.get("UD_UPSCALER_MODEL", "").strip()
    if env_path:
        candidates.append(Path(env_path))

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "UniversalDownloader" / "models")
    candidates.append(Path.home() / ".local" / "share" / "UniversalDownloader" / "models")
    candidates.append(Path(__file__).resolve().parent.parent / "models")

    for entry in candidates:
        if entry.is_file() and entry.suffix.lower() == ".onnx":
            return entry
        if entry.is_dir():
            for model_file in sorted(entry.glob("*.onnx")):
                if model_file.is_file():
                    return model_file
    return None


def _run_onnx_tiled_super_resolution(
    rgb_img: Image.Image,
    model_path: Path,
    tile_size: int = 128,
    overlap: int = 16,
) -> Image.Image:
    """
    Run tiled overlap-blended ONNX super-resolution inference on an RGB PIL image.
    Supports standard NCHW float32 [0, 1] RGB models (Real-ESRGAN, SwinIR, FSRCNN, etc.).
    """
    import numpy as np
    import onnxruntime as ort

    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    input_meta = sess.get_inputs()[0]
    input_name = input_meta.name
    output_name = sess.get_outputs()[0].name

    arr = np.asarray(rgb_img, dtype=np.float32) / 255.0  # H, W, 3
    h, w, _ = arr.shape

    def infer_patch(patch: np.ndarray) -> np.ndarray:
        nchw = np.transpose(patch, (2, 0, 1))[np.newaxis, :, :, :].astype(np.float32)
        out = sess.run([output_name], {input_name: nchw})[0]
        if out.ndim == 4:
            out = out[0]
        if out.shape[0] == 3:
            out = np.transpose(out, (1, 2, 0))
        return np.clip(out, 0.0, 1.0)

    if h <= tile_size and w <= tile_size:
        out_arr = infer_patch(arr)
        return Image.fromarray(np.round(out_arr * 255.0).astype(np.uint8), mode="RGB")

    probe_h = min(h, 32)
    probe_w = min(w, 32)
    probe_out = infer_patch(arr[:probe_h, :probe_w, :])
    scale_y = max(1, int(round(probe_out.shape[0] / float(probe_h))))
    scale_x = max(1, int(round(probe_out.shape[1] / float(probe_w))))

    out_h, out_w = h * scale_y, w * scale_x
    accum = np.zeros((out_h, out_w, 3), dtype=np.float32)
    weight = np.zeros((out_h, out_w, 1), dtype=np.float32)

    step = max(16, tile_size - overlap)
    ys = list(range(0, max(1, h - tile_size + 1), step))
    if not ys or ys[-1] + tile_size < h:
        ys.append(max(0, h - tile_size))
    xs = list(range(0, max(1, w - tile_size + 1), step))
    if not xs or xs[-1] + tile_size < w:
        xs.append(max(0, w - tile_size))

    for y0 in ys:
        y1 = min(h, y0 + tile_size)
        for x0 in xs:
            x1 = min(w, x0 + tile_size)
            tile_out = infer_patch(arr[y0:y1, x0:x1, :])
            th, tw, _ = tile_out.shape

            wy = np.ones(th, dtype=np.float32)
            wx = np.ones(tw, dtype=np.float32)
            feather_y = min(overlap * scale_y, th // 4)
            feather_x = min(overlap * scale_x, tw // 4)
            if y0 > 0 and feather_y > 1:
                wy[:feather_y] = np.linspace(0.05, 1.0, feather_y, dtype=np.float32)
            if y1 < h and feather_y > 1:
                wy[-feather_y:] = np.linspace(1.0, 0.05, feather_y, dtype=np.float32)
            if x0 > 0 and feather_x > 1:
                wx[:feather_x] = np.linspace(0.05, 1.0, feather_x, dtype=np.float32)
            if x1 < w and feather_x > 1:
                wx[-feather_x:] = np.linspace(1.0, 0.05, feather_x, dtype=np.float32)

            mask = (wy[:, np.newaxis] * wx[np.newaxis, :])[:, :, np.newaxis]
            oy0, ox0 = y0 * scale_y, x0 * scale_x
            accum[oy0 : oy0 + th, ox0 : ox0 + tw, :] += tile_out * mask
            weight[oy0 : oy0 + th, ox0 : ox0 + tw, :] += mask

    merged = accum / np.maximum(weight, 1e-6)
    return Image.fromarray(np.round(np.clip(merged, 0.0, 1.0) * 255.0).astype(np.uint8), mode="RGB")


def _enhance_rgb_ycbcr_numpy(
    rgb_img: Image.Image,
    target_w: int,
    target_h: int,
) -> Image.Image:
    """Luminance-only YCbCr Sobel edge-masked multi-scale detail reconstruction (numpy path)."""
    import numpy as np

    def sobel_edge_mask(luma: np.ndarray) -> np.ndarray:
        padded = np.pad(luma, 1, mode="edge")
        gx = (
            -padded[:-2, :-2]
            + padded[:-2, 2:]
            - 2.0 * padded[1:-1, :-2]
            + 2.0 * padded[1:-1, 2:]
            - padded[2:, :-2]
            + padded[2:, 2:]
        )
        gy = (
            -padded[:-2, :-2]
            - 2.0 * padded[:-2, 1:-1]
            - padded[:-2, 2:]
            + padded[2:, :-2]
            + 2.0 * padded[2:, 1:-1]
            + padded[2:, 2:]
        )
        mag = np.sqrt(gx * gx + gy * gy)
        return np.clip((mag - 6.0) / 36.0, 0.08, 1.0)

    resampler = getattr(Image, "Resampling", Image).LANCZOS
    orig_w, orig_h = rgb_img.size

    y_ch, cb_ch, cr_ch = rgb_img.convert("YCbCr").split()

    # Edge-aware JPEG deblocking on luminance
    y_arr = np.asarray(y_ch, dtype=np.float32)
    y_smooth = np.asarray(y_ch.filter(ImageFilter.GaussianBlur(radius=0.85)), dtype=np.float32)
    orig_edge = sobel_edge_mask(y_arr)
    deblock_w = (1.0 - orig_edge) * 0.34
    y_clean = np.clip(y_arr * (1.0 - deblock_w) + y_smooth * deblock_w, 0.0, 255.0)
    y_work = Image.fromarray(np.round(y_clean).astype(np.uint8), mode="L")

    cur_w, cur_h = orig_w, orig_h
    while cur_w < target_w or cur_h < target_h:
        next_w = min(target_w, max(cur_w + 1, int(round(cur_w * 1.4))))
        next_h = min(target_h, max(cur_h + 1, int(round(cur_h * 1.4))))
        y_work = y_work.resize((next_w, next_h), resampler)
        cur_w, cur_h = next_w, next_h

    cb_up = cb_ch.resize((target_w, target_h), resampler)
    cr_up = cr_ch.resize((target_w, target_h), resampler)

    y_up = np.asarray(y_work, dtype=np.float32)
    blur_fine = np.asarray(y_work.filter(ImageFilter.GaussianBlur(radius=0.95)), dtype=np.float32)
    blur_med = np.asarray(y_work.filter(ImageFilter.GaussianBlur(radius=2.3)), dtype=np.float32)

    edge_mask = sobel_edge_mask(y_up)
    fine_boost = np.clip((y_up - blur_fine) * (0.95 * edge_mask), -22.0, 22.0)
    clarity_boost = np.clip((y_up - blur_med) * (0.32 * edge_mask), -14.0, 14.0)
    y_final = np.clip(y_up + fine_boost + clarity_boost, 0.0, 255.0)

    y_out = Image.fromarray(np.round(y_final).astype(np.uint8), mode="L")
    reconstructed = Image.merge("YCbCr", (y_out, cb_up, cr_up)).convert("RGB")
    reconstructed = ImageEnhance.Contrast(reconstructed).enhance(1.03)
    reconstructed = ImageEnhance.Color(reconstructed).enhance(1.03)
    return reconstructed


def _enhance_rgb_ycbcr_pillow(
    rgb_img: Image.Image,
    target_w: int,
    target_h: int,
) -> Image.Image:
    """
    Pure-Pillow YCbCr luminance-only edge-masked detail reconstruction.
    Zero numpy dependency so bundled standalone executables stay lean while delivering
    halo-free luminance sharpening and adaptive flat-area JPEG deblocking.
    """
    resampler = getattr(Image, "Resampling", Image).LANCZOS
    orig_w, orig_h = rgb_img.size

    y_ch, cb_ch, cr_ch = rgb_img.convert("YCbCr").split()

    # 1. Edge-aware JPEG deblocking on luminance (keeps edges sharp, softens flat 8x8 blocks)
    y_smooth = y_ch.filter(ImageFilter.GaussianBlur(radius=0.85))
    orig_edges = y_ch.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.GaussianBlur(radius=0.6))
    # Brighter in mask = more edge -> keep original; darker = flat -> blend deblocked
    edge_keep_mask = orig_edges.point(lambda p: min(255, max(168, int(168 + p * 0.7))))
    y_work = Image.composite(y_ch, y_smooth, edge_keep_mask)

    # 2. Progressive 1.4x Lanczos3 upscaling on luminance
    cur_w, cur_h = orig_w, orig_h
    while cur_w < target_w or cur_h < target_h:
        next_w = min(target_w, max(cur_w + 1, int(round(cur_w * 1.4))))
        next_h = min(target_h, max(cur_h + 1, int(round(cur_h * 1.4))))
        y_work = y_work.resize((next_w, next_h), resampler)
        cur_w, cur_h = next_w, next_h

    cb_up = cb_ch.resize((target_w, target_h), resampler)
    cr_up = cr_ch.resize((target_w, target_h), resampler)

    # 3. Multi-scale luminance sharpening masked strictly to structural edges
    y_fine = y_work.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=3))
    y_clarity = y_fine.filter(ImageFilter.UnsharpMask(radius=2.2, percent=45, threshold=5))
    up_edges = y_work.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.GaussianBlur(radius=1.0))
    sharp_mask = up_edges.point(lambda p: min(255, max(24, int(p * 2.1))))
    y_out = Image.composite(y_clarity, y_work, sharp_mask)

    reconstructed = Image.merge("YCbCr", (y_out, cb_up, cr_up)).convert("RGB")
    reconstructed = ImageEnhance.Contrast(reconstructed).enhance(1.03)
    reconstructed = ImageEnhance.Color(reconstructed).enhance(1.03)
    return reconstructed


def _enhance_rgb_classical_hd(
    rgb_img: Image.Image,
    target_w: int,
    target_h: int,
) -> Image.Image:
    try:
        return _enhance_rgb_ycbcr_numpy(rgb_img, target_w, target_h)
    except ImportError:
        return _enhance_rgb_ycbcr_pillow(rgb_img, target_w, target_h)


def enhance_image_bytes_to_hd(
    data: bytes,
    target_min_side: int = 960,
    output_format: str = "PNG",
    model_path: Optional[Path] = None,
) -> tuple[bytes, int, int, str]:
    """
    Enhance a low-resolution profile image to crisp HD.
    Automatically uses a local ONNX neural super-resolution model when installed,
    and otherwise runs the multi-scale YCbCr edge-masked detail reconstruction pipeline.
    Returns (enhanced_bytes, new_width, new_height, ext_without_dot).
    """
    resampler = getattr(Image, "Resampling", Image).LANCZOS

    with Image.open(io.BytesIO(data)) as raw_img:
        has_alpha = raw_img.mode in ("RGBA", "LA") or (
            raw_img.mode == "P" and "transparency" in raw_img.info
        )
        rgba_img = raw_img.convert("RGBA") if has_alpha else None
        rgb_img = rgba_img.convert("RGB") if rgba_img is not None else raw_img.convert("RGB")
        orig_w, orig_h = rgb_img.size
        target_w, target_h = compute_hd_target_dimensions(
            orig_w, orig_h, target_min_side=target_min_side
        )

        if target_w <= orig_w and target_h <= orig_h:
            out_img = rgba_img if rgba_img is not None else rgb_img
            buf = io.BytesIO()
            if has_alpha or output_format.upper() == "PNG":
                out_img.save(buf, format="PNG", optimize=True)
                return buf.getvalue(), orig_w, orig_h, "png"
            out_img.save(buf, format="JPEG", quality=96, subsampling=0)
            return buf.getvalue(), orig_w, orig_h, "jpg"

        enhanced_rgb: Optional[Image.Image] = None
        onnx_model = find_local_onnx_upscaler(model_path)
        if onnx_model is not None:
            try:
                LOGGER.info("Upscaling profile image using local ONNX model: %s", onnx_model.name)
                sr_img = _run_onnx_tiled_super_resolution(rgb_img, onnx_model)
                if sr_img.size != (target_w, target_h):
                    sr_img = sr_img.resize((target_w, target_h), resampler)
                enhanced_rgb = sr_img
            except Exception as exc:
                LOGGER.warning("Local ONNX upscaler failed (%s); falling back to YCbCr enhancer.", exc)

        if enhanced_rgb is None:
            enhanced_rgb = _enhance_rgb_classical_hd(rgb_img, target_w, target_h)

        if has_alpha and rgba_img is not None:
            alpha_up = rgba_img.getchannel("A").resize((target_w, target_h), resampler)
            final_img = enhanced_rgb.convert("RGBA")
            final_img.putalpha(alpha_up)
        else:
            final_img = enhanced_rgb

        buf = io.BytesIO()
        if has_alpha or output_format.upper() == "PNG":
            final_img.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), target_w, target_h, "png"
        final_img.save(buf, format="JPEG", quality=96, subsampling=0)
        return buf.getvalue(), target_w, target_h, "jpg"
