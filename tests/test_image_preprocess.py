"""V4.9.3: 图片预处理管线测试"""

import io
import pytest
from PIL import Image


class TestBlankDetection:
    """空白检测测试"""

    def test_solid_white_is_blank(self):
        """纯白图片应判定为空白"""
        from app.engine.image_preprocess import _is_blank
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        assert _is_blank(img) is True

    def test_solid_black_is_blank(self):
        """纯黑图片应判定为空白"""
        from app.engine.image_preprocess import _is_blank
        img = Image.new("RGB", (100, 100), (0, 0, 0))
        assert _is_blank(img) is True

    def test_two_color_is_blank(self):
        """2 种颜色的简单图片应判定为空白"""
        from app.engine.image_preprocess import _is_blank
        # 白底 + 一条黑线 = 2 色
        img = Image.new("RGB", (200, 200), (255, 255, 255))
        for x in range(200):
            img.putpixel((x, 100), (0, 0, 0))
        assert _is_blank(img) is True  # < 5 colors

    def test_photo_is_not_blank(self):
        """丰富颜色图片不应判定为空白"""
        from app.engine.image_preprocess import _is_blank
        # 创建渐变图，超过 256 色
        img = Image.new("RGB", (300, 300))
        for x in range(300):
            for y in range(300):
                img.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
        assert _is_blank(img) is False

    def test_large_image_sampling(self):
        """大图降采样不应影响空白判定"""
        from app.engine.image_preprocess import _is_blank
        # 2000×2000 纯白图
        img = Image.new("RGB", (2000, 2000), (255, 255, 255))
        assert _is_blank(img) is True

    def test_five_color_boundary(self):
        """正好 5 色的判定"""
        from app.engine.image_preprocess import _is_blank
        img = Image.new("RGB", (100, 100), (0, 0, 0))
        # 加 3 条不同颜色的线 → 共 4 色
        for x in range(100):
            img.putpixel((x, 30), (255, 0, 0))  # red
            img.putpixel((x, 60), (0, 255, 0))  # green
            img.putpixel((x, 90), (0, 0, 255))  # blue
        assert _is_blank(img) is True  # 4 < 5


class TestResize:
    """自适应尺寸测试"""

    def test_small_image_no_resize(self):
        """小图不缩放"""
        from app.engine.image_preprocess import _resize_if_needed
        img = Image.new("RGB", (800, 600))
        result = _resize_if_needed(img, max_long_edge=2048)
        assert result.size == (800, 600)

    def test_large_image_resized(self):
        """大图等比缩放"""
        from app.engine.image_preprocess import _resize_if_needed
        img = Image.new("RGB", (4096, 2048))
        result = _resize_if_needed(img, max_long_edge=2048)
        assert result.size == (2048, 1024)  # 4096 is long edge, scaled to 2048

    def test_square_large_image(self):
        """正方形大图等比例缩放"""
        from app.engine.image_preprocess import _resize_if_needed
        img = Image.new("RGB", (3000, 3000))
        result = _resize_if_needed(img, max_long_edge=2048)
        assert result.size == (2048, 2048)


class TestColorNormalization:
    """色彩归一化测试"""

    def test_rgb_passthrough(self):
        """RGB 图片原样返回"""
        from app.engine.image_preprocess import _normalize_color
        img = Image.new("RGB", (100, 100), (128, 128, 128))
        result = _normalize_color(img)
        assert result.mode == "RGB"

    def test_rgba_to_rgb(self):
        """RGBA → 白底 RGB"""
        from app.engine.image_preprocess import _normalize_color
        img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
        result = _normalize_color(img)
        assert result.mode == "RGB"

    def test_grayscale_to_rgb(self):
        """灰度 L → RGB"""
        from app.engine.image_preprocess import _normalize_color
        img = Image.new("L", (100, 100), 128)
        result = _normalize_color(img)
        assert result.mode == "RGB"

    def test_palette_to_rgb(self):
        """调色板 P → RGB"""
        from app.engine.image_preprocess import _normalize_color
        rgb_img = Image.new("RGB", (100, 100), (100, 150, 200))
        p_img = rgb_img.convert("P")
        assert p_img.mode == "P"
        result = _normalize_color(p_img)
        assert result.mode == "RGB"


class TestPreprocessForVL:
    """完整预处理管线测试"""

    def test_blank_image_returns_none(self):
        """空白图片返回 None"""
        from app.engine.image_preprocess import preprocess_for_vl
        img = Image.new("RGB", (500, 500), (255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = preprocess_for_vl(buf.getvalue())
        assert result is None

    def test_normal_image_returns_jpeg(self):
        """正常图片返回 JPEG 字节"""
        from app.engine.image_preprocess import preprocess_for_vl
        # 创建非空白图案
        img = Image.new("RGB", (500, 500), (255, 255, 255))
        # 画很多色块使其不空白
        for i in range(50):
            for j in range(50):
                img.putpixel((i * 10, j * 10), (i * 5 % 256, j * 5 % 256, (i + j) * 5 % 256))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = preprocess_for_vl(buf.getvalue())
        assert result is not None
        assert len(result) > 0
        # 验证是 JPEG
        verify = Image.open(io.BytesIO(result))
        assert verify.format == "JPEG"

    def test_large_image_compressed(self):
        """大图经预处理后缩放为 JPEG"""
        from app.engine.image_preprocess import preprocess_for_vl
        from PIL import ImageDraw
        img = Image.new("RGB", (4000, 3000))  # 12M pixels
        # 用 ImageDraw 画满足够多的颜色使其非空白
        draw = ImageDraw.Draw(img)
        for x in range(0, 4000, 50):
            for y in range(0, 3000, 50):
                color = (x % 256, y % 256, (x + y) % 256)
                draw.rectangle([x, y, x + 40, y + 40], fill=color)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = preprocess_for_vl(buf.getvalue(), max_long_edge=2048, jpeg_quality=85)
        assert result is not None
        # 验证输出是 JPEG 且已缩放至 ≤ 2048 长边
        verify = Image.open(io.BytesIO(result))
        assert verify.format == "JPEG"
        assert max(verify.size) <= 2048

    def test_corrupted_image_passthrough(self):
        """损坏的图片原样返回"""
        from app.engine.image_preprocess import preprocess_for_vl
        result = preprocess_for_vl(b"not an image")
        assert result == b"not an image"

    def test_scan_type_enhancement(self):
        """scan 类型触发 CLAHE（cv2 未安装时也能通过）"""
        from app.engine.image_preprocess import preprocess_for_vl
        img = Image.new("RGB", (500, 500), (200, 200, 200))
        for i in range(100):
            for j in range(100):
                img.putpixel((i * 5, j * 5), (i * 2 % 256, j * 2 % 256, (i + j) % 256))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = preprocess_for_vl(buf.getvalue(), page_type="scan")
        # cv2 未装时不应崩溃
        assert result is not None
        verify = Image.open(io.BytesIO(result))
        assert verify.format == "JPEG"
