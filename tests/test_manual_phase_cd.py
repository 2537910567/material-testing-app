"""
Phase C+D manual test: file profiling + conversion
Tests all 4 file types without AI analysis or Excel export.
"""
import sys, os, time, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from app.logger import setup_logging
setup_logging()

BASE = r'C:\Users\Administrator\Documents\xwechat_files\wxid_i0tdmsi16kfg22_747a\msg\file\2026-06'
CAD_DIR = os.path.join(BASE, '2、图纸CAD', '图纸CAD', 'SⅦ-通信工程一期施工图设计CAD')

DWG_PATH = os.path.join(CAD_DIR, 'SVII-02、主要设备材料表20250110.dwg')
PDF_PATH = os.path.join(BASE, 'ZQ202504210011肇庆市大型产业集聚区（肇庆新区片）配套基础设施建设项目一标段（永莲大道）(1)(1).pdf')
WORD_PATH = os.path.join(BASE, 'test_word.docx')
EXCEL_PATH = os.path.join(BASE, '永莲大道_检测计划表.xlsx')

# ==================== Phase C: Profiling ====================
def test_c1_cad_profile():
    """C1: CAD profiling"""
    from app.engine.file_profiler import FileProfiler
    p = FileProfiler.profile_cad(DWG_PATH)
    assert p.strategy, "Strategy should not be empty"
    assert p.file_size_mb > 0, "File size should be > 0"
    print(f'  C1 CAD: strategy={p.strategy} size={p.file_size_mb}MB dxf_est={p.cad_complexity.get("estimated_dxf_mb")}MB')
    print(f'    Reason: {p.strategy_reason}')

def test_c2_pdf_profile():
    """C2: PDF profiling"""
    from app.engine.file_profiler import FileProfiler
    p = FileProfiler.profile_pdf(PDF_PATH)
    assert p.strategy, "Strategy should not be empty"
    assert p.total_pages > 0, "Pages should be > 0"
    print(f'  C2 PDF: strategy={p.strategy} pages={p.total_pages} size={p.file_size_mb}MB')
    print(f'    Reason: {p.strategy_reason}')
    print(f'    Types: {p.metadata.get("type_counts")}')
    print(f'    Dominant: {p.metadata.get("dominant_type")}')

def test_c3_doc_profile():
    """C3: Word/Excel profiling"""
    from app.engine.file_profiler import FileProfiler
    wp = FileProfiler.profile_document(WORD_PATH)
    assert wp.strategy == 'text_only', "Word should be text_only"
    print(f'  C3 Word: strategy={wp.strategy}')
    ep = FileProfiler.profile_document(EXCEL_PATH)
    assert ep.strategy == 'text_only', "Excel should be text_only"
    print(f'  C3 Excel: strategy={ep.strategy}')

# ==================== Phase D: Conversion ====================
def test_d1_cad_conversion():
    """D1: CAD conversion (DWG->DXF->PNG)"""
    from app.engine.dwg_parser import convert_cad_with_strategy
    from app.engine.file_profiler import FileProfiler
    profile = FileProfiler.profile_cad(DWG_PATH)
    t0 = time.time()
    result = convert_cad_with_strategy(DWG_PATH, profile.strategy)
    dt = time.time() - t0
    pngs = result.get('png_paths', [])
    err = result.get('error', '')
    text_len = len(result.get('text', ''))
    print(f'  D1 CAD: strategy={profile.strategy} time={dt:.1f}s pngs={len(pngs)} text={text_len}chars')
    if err:
        print(f'    Error: {err}')
    for png in pngs[:3]:
        sz = os.path.getsize(png) if os.path.exists(png) else 0
        print(f'    PNG: {os.path.basename(png)} ({sz/1024:.1f}KB)')
    # text_only strategy + small file should still produce text
    assert text_len > 0, "Should extract some text"

def test_d2_pdf_conversion():
    """D2: PDF conversion (strategy-based)"""
    from app.engine.file_profiler import FileProfiler
    from app.engine.pdf_parser import extract_pdf_with_strategy
    profile = FileProfiler.profile_pdf(PDF_PATH)
    page_types_int = {int(k): v for k, v in profile.page_types.items()}
    t0 = time.time()
    tmpd = tempfile.mkdtemp(prefix='test_pdf_')
    result = extract_pdf_with_strategy(PDF_PATH, page_types_int, tmpd)
    dt = time.time() - t0
    pngs = result.get('png_paths', [])
    text_len = len(result.get('text', ''))
    print(f'  D2 PDF: strategy={profile.strategy} time={dt:.1f}s pngs={len(pngs)} text={text_len}chars')
    print(f'    Types: {result.get("type_summary")}')
    assert text_len > 0, "Should extract some text from PDF"

def test_d3_word_excel_direct():
    """D3: Word/Excel are text_only, no conversion needed"""
    from app.engine.file_profiler import FileProfiler
    from app.engine.word_parser import extract_word_content
    from app.engine.excel_parser import extract_excel_content
    # Word
    wp = FileProfiler.profile_document(WORD_PATH)
    assert wp.strategy == 'text_only'
    wc = extract_word_content(WORD_PATH)
    assert wc['text'], "Word text should not be empty"
    print(f'  D3 Word: strategy={wp.strategy} text={len(wc["text"])}chars OK')
    # Excel
    ep = FileProfiler.profile_document(EXCEL_PATH)
    assert ep.strategy == 'text_only'
    ec = extract_excel_content(EXCEL_PATH)
    assert ec['text'], "Excel text should not be empty"
    print(f'  D3 Excel: strategy={ep.strategy} text={len(ec["text"])}chars OK')


if __name__ == '__main__':
    print('=' * 60)
    print('PHASE C: File Profiling')
    print('=' * 60)
    test_c1_cad_profile()
    test_c2_pdf_profile()
    test_c3_doc_profile()

    print()
    print('=' * 60)
    print('PHASE D: File Conversion')
    print('=' * 60)
    test_d1_cad_conversion()
    test_d2_pdf_conversion()
    test_d3_word_excel_direct()

    print()
    print('=== Phase C+D: ALL PASSED ===')
