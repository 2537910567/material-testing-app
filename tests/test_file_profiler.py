"""V4.9.3: 文件预分析引擎测试"""

import io
import os
import tempfile
import pytest
from pathlib import Path


# ── 测试辅助 ─────────────────────────────────────────────────────────


def _create_sample_pdf(output_path: str, pages_config: list):
    """
    创建测试用 PDF。
    pages_config: [{"text": "hello...", "rect_count": 0}, ...]
    每页一个 dict。
    """
    import fitz
    doc = fitz.open()
    for cfg in pages_config:
        page = doc.new_page(width=595, height=842)
        text = cfg.get("text", "")
        if text:
            page.insert_text((50, 50), text, fontsize=12)
        # 画一些矩形(模拟矢量路径)
        rects = cfg.get("rect_count", 0)
        for i in range(rects):
            page.draw_rect(fitz.Rect(100 + i * 10, 200, 150 + i * 10, 250))
    doc.save(output_path)
    doc.close()


# ── PDF 页面分类 ──────────────────────────────────────────────────────


class TestPageClassification:
    """PDF 单页分类测试"""

    def test_text_page(self):
        """文字 ≥ 200 的页面判定为 text"""
        from app.engine.file_profiler import FileProfiler
        import fitz

        doc = fitz.open()
        page = doc.new_page()
        long_text = "A" * 300
        page.insert_text((50, 50), long_text, fontsize=10)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            fpath = tf.name
        doc.save(fpath)
        doc.close()

        doc2 = fitz.open(fpath)
        result = FileProfiler._classify_single_page(doc2[0])
        doc2.close()
        os.unlink(fpath)
        assert result == "text"

    def test_drawing_page(self):
        """文字少 + 矢量路径多的页面判定为 drawing"""
        from app.engine.file_profiler import FileProfiler
        import fitz

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Short", fontsize=10)
        for i in range(60):
            page.draw_rect(fitz.Rect(10 + i * 8, 100, 40 + i * 8, 130))
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            fpath = tf.name
        doc.save(fpath)
        doc.close()

        doc2 = fitz.open(fpath)
        result = FileProfiler._classify_single_page(doc2[0])
        doc2.close()
        os.unlink(fpath)
        assert result == "drawing"

    def test_blank_page(self):
        """空白页（无文字+无图片+无矢量）判定为 blank"""
        from app.engine.file_profiler import FileProfiler
        import fitz

        doc = fitz.open()
        doc.new_page()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            fpath = tf.name
        doc.save(fpath)
        doc.close()

        doc2 = fitz.open(fpath)
        result = FileProfiler._classify_single_page(doc2[0])
        doc2.close()
        os.unlink(fpath)
        assert result == "blank"

    def test_scan_like_page(self):
        """文字极少 (< 50) 的页面不崩溃"""
        from app.engine.file_profiler import FileProfiler
        import fitz

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "AB", fontsize=10)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            fpath = tf.name
        doc.save(fpath)
        doc.close()

        doc2 = fitz.open(fpath)
        result = FileProfiler._classify_single_page(doc2[0])
        doc2.close()
        os.unlink(fpath)
        assert result in ("blank", "text", "drawing")  # 不崩溃即可


# ── PDF 采样策略 ──────────────────────────────────────────────────────


class TestPDFSampling:
    """PDF 采样策略测试"""

    def test_small_pdf_full_sampling(self):
        """≤ 30 页 PDF 全量分类"""
        from app.engine.file_profiler import FileProfiler, _uniform_sample

        sample = _uniform_sample(10, 12)
        assert len(sample) == 10  # 10 页全量
        assert sample == list(range(10))

    def test_medium_pdf_uniform_sampling(self):
        """31-200 页均匀采样 12"""
        from app.engine.file_profiler import _uniform_sample

        sample = _uniform_sample(100, 12)
        assert len(sample) >= 10  # 大约 12 个
        assert 0 in sample          # 含首页
        assert 99 in sample         # 含末页

    def test_large_pdf_uniform_sampling(self):
        """> 200 页均匀采样 15"""
        from app.engine.file_profiler import _uniform_sample

        sample = _uniform_sample(300, 15)
        assert len(sample) >= 13
        assert 0 in sample
        assert 299 in sample


# ── CAD 复杂度估算 ────────────────────────────────────────────────────


class TestCADProfiling:
    """CAD 预分析测试 — V6.0: 聚焦主流文件（0.5-5MB）画质提升"""

    def test_small_cad_standard_render(self):
        """小 CAD (<0.5MB) 使用 standard_render (150dpi 不变)"""
        from app.engine.file_profiler import _cad_strategy
        strategy, reason = _cad_strategy(0.05, 0.3)
        assert strategy == "standard_render"

    def test_medium_cad_standard_high(self):
        """主力 CAD (0.5~2MB) 使用 standard_high (400dpi)"""
        from app.engine.file_profiler import _cad_strategy
        strategy, reason = _cad_strategy(1.0, 6.0)
        assert strategy == "standard_high"

    def test_large_cad_standard_plus(self):
        """偏大 CAD (2~5MB) 使用 standard_plus (350dpi)"""
        from app.engine.file_profiler import _cad_strategy
        strategy, reason = _cad_strategy(3.0, 18.0)
        assert strategy == "standard_plus"

    def test_huge_cad_reduced_render(self):
        """大 CAD (5~10MB) 使用 reduced_render (200dpi)"""
        from app.engine.file_profiler import _cad_strategy
        strategy, reason = _cad_strategy(7.0, 42.0)
        assert strategy == "reduced_render"

    def test_giant_cad_text_only(self):
        """超大 CAD (>10MB) 仅文字 + 120dpi 预览"""
        from app.engine.file_profiler import _cad_strategy
        strategy, reason = _cad_strategy(12.0, 72.0)
        assert strategy == "text_only"

    def test_dxf_expansion_too_large(self):
        """V5.1: DXF 膨胀 >500MB 直接 text_only"""
        from app.engine.file_profiler import _cad_strategy

        strategy, reason = _cad_strategy(1.0, 520.0)
        assert strategy == "text_only"


# ── FileProfile dataclass ─────────────────────────────────────────────


class TestFileProfile:
    """FileProfile dataclass 测试"""

    def test_to_dict(self):
        from app.engine.file_profiler import FileProfile

        p = FileProfile(
            file_id=1, file_type="pdf", file_path="/a/b.pdf",
            strategy="text_only", total_pages=5,
            page_types={0: "text", 1: "text"},
        )
        d = p.to_dict()
        assert d["file_type"] == "pdf"
        assert d["strategy"] == "text_only"
        assert d["total_pages"] == 5

    def test_defaults(self):
        from app.engine.file_profiler import FileProfile

        p = FileProfile()
        assert p.file_type == ""
        assert p.page_types == {}
        assert p.profile_version == "4.9.3"


# ── PDF 策略决策 ──────────────────────────────────────────────────────


class TestPDFStrategy:
    """PDF 策略决策测试"""

    def test_pure_text(self):
        from app.engine.file_profiler import _pdf_strategy

        strategy, reason = _pdf_strategy(
            {"text": 50, "drawing": 0, "scan": 0, "blank": 0}, 50
        )
        assert strategy == "text_only"

    def test_pure_drawing(self):
        from app.engine.file_profiler import _pdf_strategy

        strategy, reason = _pdf_strategy(
            {"text": 0, "drawing": 30, "scan": 0, "blank": 0}, 30
        )
        assert strategy == "standard_render"

    def test_pure_scan(self):
        from app.engine.file_profiler import _pdf_strategy

        strategy, reason = _pdf_strategy(
            {"text": 0, "drawing": 0, "scan": 20, "blank": 0}, 20
        )
        assert strategy == "ocr"

    def test_hybrid(self):
        from app.engine.file_profiler import _pdf_strategy

        strategy, reason = _pdf_strategy(
            {"text": 100, "drawing": 60, "scan": 8, "blank": 0}, 168
        )
        assert strategy == "hybrid"


# ── MD5 计算 ──────────────────────────────────────────────────────────


class TestFileMD5:
    """文件 MD5 计算测试"""

    def test_md5_stable(self):
        from app.engine.file_profiler import _compute_file_md5
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"hello world")
            fpath = f.name

        md5_1 = _compute_file_md5(fpath)
        md5_2 = _compute_file_md5(fpath)
        assert md5_1 == md5_2
        assert len(md5_1) == 32

        os.remove(fpath)

    def test_md5_nonexistent(self):
        from app.engine.file_profiler import _compute_file_md5
        assert _compute_file_md5("/nonexistent/file.pdf") == ""
