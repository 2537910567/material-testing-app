"""
全局应用状态 — QObject 单例，桥接 engine/database 层到 QML。
V5.1: Thread classes kept inline (sandbox constraints), organized with section headers.
"""
import os, json, threading, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PySide6.QtCore import QObject, Signal, Slot, Property, QThread
from PySide6.QtQml import QmlElement
from PySide6.QtWidgets import QFileDialog
from ..config import AppConfig
from ..engine.project_manager import ProjectManager, Project
from ..engine.ai_agent import analyze_with_provider
from ..engine.model_provider import ModelProviderFactory
from ..engine.pdf_parser import extract_pdf_content, extract_page_images
from ..engine.dwg_parser import parse_dwg, extract_all_text, convert_dwg_to_png
from ..report.report_generator import generate_testing_plan
from ..logger import get_logger
from ..errors import AppError, ConversionError, AnalysisError, ParseError, ConfigError
logger = get_logger("bridge")

def _detect_testing_guide(file_path: str, content_text: str = "") -> bool:
    """V4.6: 检测文件是否为送检指南"""
    file_name = Path(file_path).name.lower()
    name_keywords = ["送检指南","检测指南","送检指引","材料检测","testing guide"]
    if any(kw in file_name for kw in name_keywords): return True
    if content_text:
        content_keywords = ["送检频率","检验批","取样频率","检测频次","inspection frequency","送检计划","检验批次"]
        if any(kw in content_text for kw in content_keywords): return True
    return False

# ═══════════════ Utility ═══════════════

def _calc_worker_count() -> int:
    """V5.3: 硬件自适应 Worker 数。

    Returns:
        建议并发数 (1-8)。基于 CPU 核心数和内存。
    """
    try:
        import os as _os
        cpu_count = _os.cpu_count() or 4
        # 简单策略：留 2 核给 UI + 系统
        workers = max(1, min(cpu_count - 2, 8))
        # 内存检查：<4GB → 减半
        try:
            import psutil
            mem_gb = psutil.virtual_memory().total / (1024 ** 3)
            if mem_gb < 4:
                workers = max(1, workers // 2)
        except ImportError:
            pass
        return workers
    except Exception:
        return 4  # fallback

# ═══════════════ Worker Threads ═══════════════

class FileImportThread(QThread):
    progress = Signal(int,int,str); file_started = Signal(str,str); file_done = Signal(str,str,object)
    file_thumbnailed = Signal(int,str); cad_done = Signal(list); pdf_done = Signal(list)
    error = Signal(str); queue_finished = Signal()
    def __init__(self, file_groups, project_id="", db=None, skip_parsed=True):
        super().__init__(); self._project_id=project_id; self._db=db; self._skip_parsed=skip_parsed
        completed_set=set(); skipped=0
        if skip_parsed and db and project_id:
            completed_set=self._get_completed_files(db,project_id)
            for ft in list(file_groups.keys()):
                before=len(file_groups[ft]); file_groups[ft]=[f for f in file_groups[ft] if f not in completed_set]
                skipped+=before-len(file_groups[ft])
            if skipped: logger.info("Skip %d already parsed files", skipped)
        self.task_queue=[(ft,f) for ft,files in file_groups.items() for f in files]
        self._paused=False; self._cancelled=False; self.cad_results=[]; self.pdf_results=[]
        self.word_results=[]; self.excel_results=[]; self._skipped_count=skipped
        self._lock=threading.Lock(); self._last_progress_time=0
    def _get_completed_files(self,db,project_id):
        try:
            files=db.get_files(project_id); completed=set()
            for f in files:
                if f.get("parse_status")=="done":
                    fp=f.get("file_path","")
                    if fp and os.path.exists(fp) and abs(os.path.getmtime(fp)-f.get("file_mtime",0))<1.0: completed.add(fp)
            return completed
        except Exception as e: logger.warning("_get_completed_files: %s",e); return set()
    def _get_optimal_workers(self):
        cad=sum(1 for ft,_ in self.task_queue if ft=="cad")
        pdfs=sum(1 for ft,_ in self.task_queue if ft=="pdf")
        io=sum(1 for ft,_ in self.task_queue if ft in ("pdf","word","excel"))
        cpu=os.cpu_count() or 4
        # V6.0: PDF 超大文件串行处理，避免内存争抢+进度条卡死
        if pdfs>0: return 1
        if cad>io: return min(4,cad,cpu)
        return min(8,io,cpu)
    def _parse_file_wrapper(self,ftype,fpath):
        fn=Path(fpath).name
        try:
            logger.info("Parsing %s: %s",ftype,fn)
            if ftype=="cad": return parse_dwg(fpath,auto_convert=True)
            elif ftype=="pdf": return extract_pdf_content(fpath)
            elif ftype=="word":
                from ..engine.word_parser import extract_word_content; return extract_word_content(fpath)
            elif ftype=="excel":
                from ..engine.excel_parser import extract_excel_content; return extract_excel_content(fpath)
            else: logger.warning("Unknown type: %s",ftype); return None
        except Exception as e: logger.error("Parse failed: %s - %s",fn,str(e)); raise
    def _store_parse_result(self,fpath,project_id,ftype,result):
        from pathlib import Path as _P; from ..engine.dwg_parser import DWGContent
        fn=_P(fpath).name; ext=_P(fpath).suffix.lower(); import os as _os
        fpn=_os.path.normpath(fpath)
        rows=self._db._conn.execute("SELECT id,file_path FROM files WHERE project_id=?",(project_id,)).fetchall()
        fid=None
        for r in rows:
            if fpath==r[1] or fpn==_os.path.normpath(r[1] or ""): fid=r[0]; break
        if not fid: logger.warning("_store_parse_result: id not found for %s",fn); return
        if isinstance(result,DWGContent):
            entities=[{"text":t["text"],"layer":t.get("layer",""),"x":t.get("x",0),"y":t.get("y",0)} for t in result.text_entities]
            self._db.store_text_entities(fid,entities)
            self._db.update_file_parse_status(fid,"done",result.discipline,result.description)
        elif isinstance(result,dict) and "text" in result:
            disc,desc=("Word","") if ext==".docx" else ("Excel","") if ext==".xlsx" else ("PDF","")
            if ext in (".pdf",".docx") and _detect_testing_guide(fpath,result.get("text","")): disc,desc="送检指南","TESTING_GUIDE"
            entities=[{"text":l,"layer":disc,"x":0,"y":0} for l in result["text"].split("\n")[:20000]]
            self._db.store_text_entities(fid,entities); self._db.update_file_parse_status(fid,"done",disc,desc)
            if ext in (".docx",".xlsx"): self._db.set_conversion_status(fid,"done")
    def run(self):
        total=len(self.task_queue); mw=self._get_optimal_workers()
        logger.info("Parallel import: %d files, %d workers",total,mw)
        with ThreadPoolExecutor(max_workers=mw) as ex:
            fmap={}; completed=0
            for i,(ft,fp) in enumerate(self.task_queue):
                if self._cancelled: break
                fmap[ex.submit(self._parse_file_wrapper,ft,fp)]=(i,ft,fp)
            for fut in as_completed(fmap):
                while self._paused and not self._cancelled: self.msleep(100)
                if self._cancelled: ex.shutdown(wait=False,cancel_futures=True); self.progress.emit(completed,total,"已取消"); self.queue_finished.emit(); return
                _,ft,fp=fmap[fut]; fn=Path(fp).name
                try:
                    r=fut.result()
                    with self._lock:
                        completed+=1
                        if ft=="cad": self.cad_results.append(r)
                        elif ft=="pdf": self.pdf_results.append(r)
                        elif ft=="word": self.word_results.append(r)
                        elif ft=="excel": self.excel_results.append(r)
                    if self._db and r is not None: self._store_parse_result(fp,self._project_id,ft,r)
                    if time.time()*1000-getattr(self,'_last_progress_time',0)>=200:
                        self.progress.emit(completed,total,f"解析 {completed}/{total}: {fn}"); self._last_progress_time=time.time()*1000
                    self.file_done.emit(fp,self._project_id,r)
                except Exception as e:
                    with self._lock: completed+=1
                    self.error.emit(f"{fn}: {str(e)}"); self.file_done.emit(fp,self._project_id,None)
        self.progress.emit(total,total,"解析完成！"); self.cad_done.emit(self.cad_results); self.pdf_done.emit(self.pdf_results); self.queue_finished.emit()
    def pause(self): self._paused=True
    def resume(self): self._paused=False
    def cancel(self): self._cancelled=True; self._paused=False

class ProfileThread(QThread):
    progress=Signal(str); profile_ready=Signal(int,object); error=Signal(str); finished=Signal(list)
    def __init__(self,project_id="",db=None,file_ids=None):
        super().__init__(); self._project_id=project_id; self._db=db; self._file_ids=file_ids or []
        self._cancelled=False; self._paused=False
    def run(self):
        import traceback as _tb
        try:
            self._run_impl()
        except Exception:
            import logging; _log = logging.getLogger(__name__)
            _log.critical("ProfileThread CRASHED:\n%s", _tb.format_exc())
            self.error.emit(f"预分析线程崩溃: {_tb.format_exc()[:300]}")

    def _run_impl(self):
        from ..engine.file_profiler import FileProfiler, _compute_file_md5
        import logging; _log = logging.getLogger(__name__)
        _log.info("ProfileThread.run() STARTED — file_ids=%s", self._file_ids)
        results=[]; total=len(self._file_ids)
        for i,fid in enumerate(self._file_ids):
            if self._cancelled: break
            while self._paused and not self._cancelled: self.msleep(100)
            try:
                row=self._db._conn.execute("SELECT id,file_path,file_type FROM files WHERE id=?",(fid,)).fetchone()
            except Exception as e:
                _log.critical("ProfileThread DB query failed for fid=%s: %s", fid, e)
                continue
            _log.info("ProfileThread: fid=%s row=%s", fid, row is not None)
            if not row: continue
            fid2,fp,ftype=row; fn=Path(fp).name
            cached=self._db.get_file_profile(fid2)
            if cached: results.append((fid2,cached)); self.progress.emit(f"Phase0: {i+1}/{total} — {fn} (已缓存)"); continue
            self.progress.emit(f"Phase0: {i+1}/{total} — {fn}")
            try:
                ext=Path(fp).suffix.lower()
                if ext in (".dwg",".dxf"): prof=FileProfiler.profile_cad(fp)
                elif ext==".pdf": prof=FileProfiler.profile_pdf(fp)
                else: prof=FileProfiler.profile_document(fp)
                fmd5=_compute_file_md5(fp)
                pd={"strategy":prof.strategy,"file_size_mb":prof.file_size_mb,"total_pages":getattr(prof,"total_pages",0),
                    "page_types":getattr(prof,"page_types",{}),"cad_complexity":getattr(prof,"cad_complexity",""),"metadata":getattr(prof,"metadata",{})}
                self._db.save_file_profile(fid2,fmd5,pd); self.profile_ready.emit(fid2,pd); results.append((fid2,pd))
            except Exception as e: logger.error("Profile failed: %s - %s",fn,e); self.error.emit(f"{fn}: {str(e)}")
        self.progress.emit(f"Phase0完成: {len(results)}/{total}"); self.finished.emit(results)
    def cancel(self): self._cancelled=True; self._paused=False
    def pause(self): self._paused=True
    def resume(self): self._paused=False

class StrategyConversionThread(QThread):
    progress=Signal(str); file_progress=Signal(int,int,str); conversion_done=Signal(int,str)
    conversion_error=Signal(int,str); finished=Signal(); error=Signal(str)
    def __init__(self,project_id,db,files_to_convert):
        super().__init__(); self._project_id=project_id; self._db=db; self._files=files_to_convert
        self._cancelled=False; self._paused=False
        import threading; self._cancel_event = threading.Event()
    def cancel(self):
        self._cancelled=True; self._paused=False
        self._cancel_event.set()
    def pause(self): self._paused=True
    def resume(self): self._paused=False
    def run(self):
        import traceback as _tb2
        try:
            self._run_impl()
        except Exception:
            import logging; _log2 = logging.getLogger(__name__)
            _log2.critical("StrategyConversionThread CRASHED:\n%s", _tb2.format_exc())
            self.error.emit(f"转换线程崩溃: {_tb2.format_exc()[:300]}")

    def _run_impl(self):
        import os as _os
        # 降低本线程优先级，避免 ODAFC 子进程抢死 UI
        try:
            _os.nice(10)  # Unix
        except AttributeError:
            try:
                import ctypes; ctypes.windll.kernel32.SetThreadPriority(
                    ctypes.windll.kernel32.GetCurrentThread(), 0xFFFFFFFE)  # BELOW_NORMAL
            except Exception:
                pass
        from ..engine.dwg_parser import convert_cad_with_strategy
        from ..engine.pdf_parser import extract_pdf_with_strategy
        total=len(self._files); completed=0

        # V6.0: 转换前文件类型判断 — 决定 CAD+PDF 混合策略
        has_cad = any(f.get("file_type") == "cad" for f in self._files)
        has_pdf = any(f.get("file_type") == "pdf" for f in self._files)
        mixed = has_cad and has_pdf
        if mixed:
            self.progress.emit("检测到 CAD+PDF 混合文件: PDF 负责视觉，CAD 仅提取文字")

        groups={"text_only":[],"standard_high":[],"standard_plus":[],"standard_render":[],"reduced_render":[],"ocr":[],"hybrid":[],"cairo_render":[]}
        for f in self._files:
            prof=self._db.get_file_profile(f["id"])
            s=prof.get("strategy","text_only") if prof else "text_only"
            # V6.0: 混合模式下 CAD 文件不渲染 PNG（省时间，PDF 已覆盖视觉）
            if mixed and f.get("file_type") == "cad" and s not in ("text_only",):
                groups["text_only"].append(f)
            else:
                groups.get(s,groups["text_only"]).append(f)
        order=["text_only","standard_high","standard_plus","standard_render","reduced_render","ocr","hybrid","cairo_render"]
        # V5.3: 动态并发数（硬件自适应 + try/except 兜底）
        hw_max = _calc_worker_count()
        workers = {
            "text_only": min(hw_max, 6),
            "standard_high": min(hw_max - 1, 2),    # 400dpi — 2 上限防内存争抢
            "standard_plus": min(hw_max - 1, 2),    # 350dpi — 2 上限
            "standard_render": min(hw_max - 1, 2),  # V6.0: 4→2, 防高DPI多文件内存暴涨
            "reduced_render": min(hw_max - 2, 2),   # V6.0: 3→2
            "ocr": min(hw_max - 2, 2),
            "hybrid": min(hw_max - 2, 2),
            "cairo_render": min(hw_max - 3, 2),
        }
        # 确保最小值为 1
        for k in workers:
            workers[k] = max(workers[k], 1)
        for s in order:
            flist=groups[s]
            if not flist: continue
            w=workers.get(s,2); self.progress.emit(f"转换: {s} ({len(flist)}文件, x{w})")
            with ThreadPoolExecutor(max_workers=w) as ex:
                fmap={}
                for f in flist:
                    if self._cancelled: break
                    fmap[ex.submit(self._convert_one,f,s)]=f
                for fut in as_completed(fmap):
                    if self._cancelled: ex.shutdown(wait=True,cancel_futures=True); return
                    f=fmap[fut]
                    try:
                        fut.result(timeout=150); completed+=1
                        fn = f.get("file_name", "?") if isinstance(f, dict) else "?"
                        self.file_progress.emit(completed, total, f"[{completed}/{total}] {fn}")
                    except Exception as e: self.conversion_error.emit(f["id"],str(e))
        if not self._cancelled:
            self.progress.emit("✅ 转换完成")
        self.finished.emit()
    def _convert_one(self,f,strategy):
        if self._cancelled:
            return
        # 降低 worker 线程优先级，避免抢占 UI
        try:
            import ctypes; ctypes.windll.kernel32.SetThreadPriority(
                ctypes.windll.kernel32.GetCurrentThread(), 0xFFFFFFFE)
        except Exception:
            pass
        from ..engine.dwg_parser import convert_cad_with_strategy
        from ..engine.pdf_parser import extract_pdf_with_strategy, extract_pdf_content
        fp=f["file_path"]; fn=f["file_name"]; fid=f["id"]; ft=f.get("file_type","cad")
        error_detail = ""
        try:
            if ft=="cad":
                cad_result=convert_cad_with_strategy(fp,strategy=strategy,
                                                     cancel_event=self._cancel_event)
                pngs=cad_result.get("png_paths",[]) if isinstance(cad_result,dict) else []
            elif ft=="pdf":
                # V5.1 修复: extract_pdf_with_strategy 的签名是 (pdf_path, page_types, output_dir)
                # 原代码错误传入了 strategy=strategy（TypeError）
                prof=self._db.get_file_profile(fid)
                page_types=prof.get("page_types",{}) if prof else {}
                if not isinstance(page_types,dict) or not page_types:
                    page_types={}
                from pathlib import Path
                png_dir=Path(fp).parent/f"_converted_{Path(fp).stem}"
                png_dir.mkdir(exist_ok=True)
                if strategy=="text_only":
                    r=extract_pdf_content(fp,skip_tables_for_large=False)
                    pngs=[]
                else:
                    r=extract_pdf_with_strategy(fp,page_types,str(png_dir))
                    pngs=r.get("png_paths",[]) if r else []
            else: pngs=[]
            if self._cancelled:
                return
            pdir=pngs[0] if pngs else ""
            self._db.set_conversion_status(fid,"done"); self._db.set_setting(f"conversion_type_{fid}",strategy)
            self.conversion_done.emit(fid,pdir)
        except Exception as e:
            import logging, traceback
            _log = logging.getLogger(__name__)
            error_detail = f"{fn}: {str(e)}"
            _log.error("_convert_one FAILED: %s\n%s", error_detail, traceback.format_exc())
            if not self._cancelled:
                self._db.set_conversion_status(fid,"error")
                self.conversion_error.emit(fid,error_detail)

class AIAnalysisThread(QThread):
    progress=Signal(str); finished=Signal(object); error=Signal(str); paused=Signal(bool)
    def __init__(self,project_id,db,ds_key,qwen_key,config):
        super().__init__(); self._project_id=project_id; self._db=db; self._ds_key=ds_key
        self._qwen_key=qwen_key; self._config=config; self._cancelled=False; self._paused=False; self._plan_drawing_path=""
    def cancel(self): self._cancelled=True; self._paused=False
    def pause(self): self._paused=True; self.paused.emit(True)
    def resume(self): self._paused=False; self.paused.emit(False)
    def run(self):
        try:
            cp=self._db.get_checkpoint(self._project_id)
            skip=cp and cp["step"] in ("vision","text_analysis")
            if skip: self.progress.emit("断点恢复: 跳过解析，从视觉分析继续...")
            unp=self._db.get_unparsed_files(self._project_id) if not skip else []
            if unp:
                from ..engine.dwg_parser import parse_dwg as _pd; from ..engine.pdf_parser import extract_pdf_content as _ep
                from ..engine.word_parser import extract_word_content as _ew; from ..engine.excel_parser import extract_excel_content as _ee
                self.progress.emit(f"解析 {len(unp)} 个待处理文件...")
                for fi,f in enumerate(unp):
                    while self._paused and not self._cancelled: self.msleep(100)
                    if self._cancelled: self.progress.emit("已取消"); return
                    fp=f.get("file_path",""); fn=f.get("file_name",""); ft=f.get("file_type","cad"); fid=f["id"]
                    self.progress.emit(f"解析 {fi+1}/{len(unp)}: {fn}")
                    try:
                        if ft=="cad": r=_pd(fp,auto_convert=True)
                        elif ft=="word": r=_ew(fp)
                        elif ft=="excel": r=_ee(fp)
                        else: r=_ep(fp)
                        if r is not None:
                            if ft=="cad":
                                entities=[{"text":t.get("text",str(t)),"layer":t.get("layer",""),"x":t.get("pos_x",t.get("x",0)),"y":t.get("pos_y",t.get("y",0))} for t in (r.text_entities or [])]
                                self._db.store_text_entities(fid,entities); self._db.update_file_parse_status(fid,"done",getattr(r,"discipline",""),getattr(r,"description",""))
                            elif isinstance(r,dict) and "text" in r:
                                disc="Word" if ft=="word" else "Excel" if ft=="excel" else "PDF"
                                entities=[{"text":l,"layer":disc,"x":0,"y":0} for l in r["text"].split("\n")[:20000]]
                                # V6.0.1: 表格数据也存入 text_entities，供 AI 分析使用
                                if "tables" in r and r["tables"]:
                                    for tbl in r["tables"]:
                                        page = tbl.get("page", "?")
                                        rows = tbl.get("rows", [])
                                        if rows and len(rows) > 0:
                                            ncols = len(rows[0]) if rows[0] else 0
                                            entities.append({"text": f"--- 第{page}页表格 ({len(rows)}行×{ncols}列) ---", "layer": disc, "x": 0, "y": 0})
                                            for row in rows:
                                                entities.append({"text": " | ".join(str(c) if c is not None else "" for c in row), "layer": disc, "x": 0, "y": 0})
                                self._db.store_text_entities(fid,entities); self._db.update_file_parse_status(fid,"done",disc,"")
                            self.progress.emit(f"  ✅ {fn}")
                    except Exception as e: self.progress.emit(f"  ❌ {fn}: {e}")
            self._db.save_checkpoint(self._project_id,"vision")
            nf=self._db.get_files_without_vision(self._project_id); exv=self._db.get_all_vision_results(self._project_id)
            self.progress.emit(f"Vision: {len(exv)} 缓存, {len(nf)} 新")
            if nf and self._qwen_key:
                from ..engine.model_provider import QwenVLProvider
                from ..engine.qwen_vl import analyze_drawing, is_cross_section_drawing
                import os as _os
                qwen_model = self._config.qwen_model
                tasks=[]; skipped=0
                for f in nf:
                    fn=f.get("file_name",""); fid=f["id"]
                    if self._db.get_setting(f"conversion_type_{fid}")=="text_only": self.progress.emit(f"  跳过 {fn}: 文字型"); continue
                    pp=self._db.get_setting(f"converted_png_{fid}")
                    if pp and _os.path.exists(pp) and _os.path.isfile(pp):
                        pd=_os.path.dirname(pp); pb=_os.path.splitext(_os.path.basename(pp))[0]
                        pngs=[pp]
                        try:
                            for p in _os.listdir(pd):
                                if p.endswith(".png") and p.startswith(pb) and (fp2:=_os.path.join(pd,p)) not in pngs: pngs.append(fp2)
                        except: pass
                        if not self._plan_drawing_path: self._plan_drawing_path=pngs[0]
                        if not is_cross_section_drawing(fn): self._plan_drawing_path=pngs[0]
                        # V6.0: Vision 全量 — 移除 pngs[:3] 限制，所有图纸页全送
                        tasks.append({"file_id":fid,"fname":fn,"image_paths":pngs,"drawing_type":"cross_section" if is_cross_section_drawing(fn) else "plan"})
                    else: skipped+=1; self.progress.emit(f"  跳过 {fn}: 无PNG")
                if skipped: self.progress.emit(f"  ⚠️ {skipped} 文件缺PNG")
                if tasks:
                    total_pngs = sum(len(t["image_paths"]) for t in tasks)
                    self.progress.emit(f"Vision: {len(tasks)} 文件, {total_pngs} 张图, x5 并行")
                    def _vt(t):
                        p=QwenVLProvider(self._qwen_key,qwen_model); self.progress.emit(f"  Vision: {t['fname']} ({len(t['image_paths'])}张)")
                        try:
                            r=analyze_drawing(p,t["image_paths"],drawing_type=t["drawing_type"])
                            if "error" not in r: self._db.store_vision_result(t["file_id"],qwen_model,r); self.progress.emit(f"  ✅ {t['fname']}"); return(t["file_id"],True,None)
                            else: self.progress.emit(f"  ❌ {t['fname']}: {r.get('error')}"); return(t["file_id"],False,r.get("error"))
                        except Exception as e: self.progress.emit(f"  ❌ {t['fname']}: {e}"); return(t["file_id"],False,str(e))
                    with ThreadPoolExecutor(max_workers=5) as ex:
                        fm={ex.submit(_vt,t):t for t in tasks}
                        for fut in as_completed(fm):
                            if self._cancelled: ex.shutdown(wait=False,cancel_futures=True); self.progress.emit("已取消"); return
                            fut.result()
                self._db.save_checkpoint(self._project_id,"text_analysis",",".join(str(f["id"]) for f in nf))
                exv=self._db.get_all_vision_results(self._project_id)
                if self._plan_drawing_path:
                    try:
                        import shutil; pd=Path(self._config.config_dir)/"plan_drawing"; pd.mkdir(parents=True,exist_ok=True)
                        dp=pd/f"{self._project_id}.png"; shutil.copy2(self._plan_drawing_path,dp)
                        self._plan_drawing_path=str(dp); self._db.set_setting(f"plan_drawing_{self._project_id}",self._plan_drawing_path)
                    except Exception as e: logger.warning("plan drawing save failed: %s",e)
            elif nf and not self._qwen_key: self.progress.emit("⚠️ 未配置 Qwen-VL Key")
            self.progress.emit("构建分析 prompt...")
            ct=self._build_combined_prompt(exv)
            if not ct or len(ct.strip())<50: self.error.emit("文档文本不足"); return
            # V5.2: 从项目上下文匹配标准知识库
            try:
                kw_parts = []
                for fid,rv in exv.items():
                    mt = rv.get("result",{}).get("material_text","")
                    if isinstance(mt,str) and mt:
                        kw_parts.append(mt[:2000])
                txt = self._db.get_extracted_text(self._project_id) or ""
                kw_parts.append(txt[:2000])
                combined = " ".join(kw_parts)
                keywords = list(set(
                    w for w in combined.replace("\n"," ").replace(","," ").split()
                    if len(w) >= 2 and not w.startswith("K") and not w.startswith("http")
                ))
                matched = self._db.get_matching_standards_for_keywords(keywords[:20])
                if matched:
                    ct = "APPLICABLE STANDARDS (from knowledge base, sorted by relevance):\n" + \
                         "\n".join(f"- {s}" for s in matched[:8]) + "\n\n" + ct
                    self.progress.emit(f"匹配标准: {len(matched)} 本 ({' '.join(matched[:5])}...)")
            except Exception as e:
                logger.debug("Standards matching skipped: %s", e)
            while self._paused and not self._cancelled: self.msleep(100)
            if self._cancelled: self.progress.emit("已取消"); return
            # V5.1: 细粒度进度信息
            sections = self._db.get_latest_analysis(self._project_id)
            sec_count = len(sections.get("sections", [])) if sections else 0
            if sec_count:
                self.progress.emit(f"AI 文本分析 (DeepSeek) — {sec_count} 个路段...")
            else:
                self.progress.emit("AI 文本分析 (DeepSeek)...")
            from ..engine.ai_agent import analyze_with_provider; from ..engine.model_provider import DeepSeekProvider
            # V6.0: 获取项目主专业，传递给 AI 分析以提升 Few-Shot 准确度
            disc_summary = self._db.get_discipline_summary(self._project_id)
            proj_discipline = disc_summary[0]["discipline"] if disc_summary else ""
            ds_model = self._config.deepseek_model
            p=DeepSeekProvider(self._ds_key,ds_model); r=analyze_with_provider(p,ct,self.progress.emit,db_manager=self._db,discipline=proj_discipline)
            if "error" in r: self.error.emit(r["error"])
            else:
                if self._plan_drawing_path: r["_plan_drawing_path"]=self._plan_drawing_path
                sec_names = [s.get("section","") for s in r.get("sections",[])]
                n_layers = len(r.get("construction_layers",[]))
                self.progress.emit(f"完成: {len(r.get('testing_plan',[]))}项, {len(r.get('sections',[]))}段, {n_layers}层")
                self._db.clear_checkpoint(self._project_id); self.finished.emit(r)
        except Exception as e: import traceback; self.error.emit(f"{e}: {traceback.format_exc()}")
    def _build_combined_prompt(self,vr):
        parts=[]
        gt=self._db.get_extracted_testing_guide_text(self._project_id)
        if gt: parts.append("===== TESTING GUIDE (HIGHEST PRIORITY) ====="); parts.append(gt); parts.append("")
        for fid,rv in vr.items():
            fn=rv.get("file_name","?"); r=rv.get("result",{})
            parts.append(f"\n===== Vision: {fn} =====")
            mt=r.get("material_text","")
            if isinstance(mt,str): parts.append(mt)
            elif isinstance(mt,list): parts.extend(mt)
            else: parts.append(str(r))
        t=self._db.get_extracted_text(self._project_id)
        if t: parts.append("\n===== Extracted Text ====="); parts.append(t)
        return "\n".join(parts)

class ExportThread(QThread):
    finished=Signal(str); error=Signal(str); progress=Signal(str)  # V6.0.1: 导出进度
    def __init__(self,output_path,project_info,testing_plan,contract_info,key_notes,project_name,sections,construction_layers=None):
        super().__init__(); self._output_path=output_path; self._project_info=project_info; self._testing_plan=testing_plan
        self._contract_info=contract_info; self._key_notes=key_notes; self._project_name=project_name
        self._sections=sections; self._construction_layers=construction_layers
    def run(self):
        try:
            ap=generate_testing_plan(output_path=self._output_path,project_info=self._project_info,testing_plan=self._testing_plan,
                contract_info=self._contract_info,key_notes=self._key_notes,project_name=self._project_name,
                sections=self._sections,construction_layers=self._construction_layers,
                progress_callback=lambda m: self.progress.emit(m))  # V6.0.1
            self.finished.emit(ap)
        except Exception as e: self.error.emit(str(e))

class ConnectionTestThread(QThread):
    finished=Signal(object)
    def __init__(self,ds_key,qwen_key): super().__init__(); self._ds_key=ds_key; self._qwen_key=qwen_key
    def run(self):
        import requests; r={"ds_ok":False,"ds_msg":"","qwen_ok":False,"qwen_msg":""}
        if self._ds_key:
            try:
                resp=requests.post("https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization":f"Bearer {self._ds_key}","Content-Type":"application/json"},
                    json={"model":"deepseek-chat","messages":[{"role":"user","content":"say ok"}],"max_tokens":10},timeout=15)
                if resp.status_code==200: r["ds_ok"]=True; r["ds_msg"]="连接成功"
                elif resp.status_code==401: r["ds_msg"]="API Key无效(401)"
                elif resp.status_code==403: r["ds_msg"]="无权访问(403)"
                else: r["ds_msg"]=f"HTTP {resp.status_code}"
            except Exception as e: r["ds_msg"]=str(e)
        else: r["ds_msg"]="未配置"
        if self._qwen_key:
            try:
                resp=requests.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                    headers={"Authorization":f"Bearer {self._qwen_key}","Content-Type":"application/json"},
                    json={"model":"qwen-plus","messages":[{"role":"user","content":"say ok"}],"max_tokens":10},timeout=15)
                if resp.status_code==200: r["qwen_ok"]=True; r["qwen_msg"]="连接成功"
                elif resp.status_code==401: r["qwen_msg"]="API Key无效(401)"
                else: r["qwen_msg"]=f"HTTP {resp.status_code}"
            except Exception as e: r["qwen_msg"]=str(e)
        else: r["qwen_msg"]="未配置"
        self.finished.emit({"ds_ok": r["ds_ok"], "ds_msg": r["ds_msg"],
                            "qwen_ok": r["qwen_ok"], "qwen_msg": r["qwen_msg"]})


# ═══════════════ AppState Singleton ═══════════════

QML_IMPORT_NAME = "app.bridge"
QML_IMPORT_MAJOR_VERSION = 1


@QmlElement
class AppState(QObject):
    """全局应用状态，暴露给 QML 的 context property。V5.1"""
    currentProjectChanged = Signal(str)
    projectsChanged = Signal()
    importStarted = Signal()
    importFinished = Signal(str)
    importError = Signal(str, str)  # V6.1.1: 导入错误汇总 (projectId, errorMessage)
    importProgress = Signal(int, int, str)
    mixedFileTypesDetected = Signal("QVariantList")  # V5.3: [{type: "cad"/"pdf", count: N}, ...]
    conversionStarted = Signal()
    conversionFinished = Signal(str)
    conversionProgress = Signal(int, int, str)
    analysisStarted = Signal()
    analysisFinished = Signal(str, object)
    analysisError = Signal(str, str)
    analysisProgress = Signal(str)
    exportStarted = Signal()
    exportFinished = Signal(str)
    exportError = Signal(str)
    projectDeleted = Signal(str)
    connectionTestFinished = Signal(object)
    errorLogChanged = Signal()
    # V6.0: 模型切换信号
    deepseekModelsChanged = Signal()
    qwenModelsChanged = Signal()
    currentDeepseekModelChanged = Signal()
    currentQwenModelChanged = Signal()
    modelsLoadingChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = AppConfig()
        self._pm = ProjectManager()
        self._db = self._pm._db
        self._current_project_id = ""
        self._is_importing = False
        self._import_current = 0
        self._import_total = 0
        self._import_message = ""
        self._import_thread = None
        self._import_start_time = 0
        self._is_converting = False
        self._conversion_current = 0
        self._conversion_total = 0
        self._profile_thread = None
        self._conversion_thread = None
        self._is_analyzing = False
        self._is_analysis_paused = False
        self._analysis_current = 0
        self._analysis_total = 0
        self._ai_progress = ""
        self._ai_thread = None
        self._is_exporting = False
        self._export_thread = None
        self._conn_test_thread = None
        self._error_logs = []
        self._error_log_max = 100
        # V6.0: 模型切换状态
        self._deepseek_models = []
        self._qwen_models = []
        self._current_deepseek_model = self._config.deepseek_model
        self._current_qwen_model = self._config.qwen_model
        self._models_loading = False
        self._is_offline = False  # V5.3: 默认乐观，后台线程异步检查
        self._check_network()  # 启动后台网络检查
        # V6.1: 自动更新
        self._update_available = False
        self._update_version = ""
        self._update_url = ""
        self._update_body = ""
        self._check_for_updates()  # 启动后台更新检查

    # ── Properties ──────────────────────────────
    @Property(str, notify=currentProjectChanged)
    def currentProjectId(self):
        return self._current_project_id

    @currentProjectId.setter
    def currentProjectId(self, v):
        if v != self._current_project_id:
            self._current_project_id = v
            self.currentProjectChanged.emit(v)

    @Property(bool, notify=importStarted)
    def isImporting(self):
        return self._is_importing

    @Property(int, notify=importProgress)
    def importCurrent(self):
        return self._import_current

    @Property(int, notify=importProgress)
    def importTotal(self):
        return self._import_total

    @Property(str, notify=importProgress)
    def importMessage(self):
        return self._import_message

    @Property(bool, notify=conversionStarted)
    def isConverting(self):
        return self._is_converting

    @Property(int, notify=conversionProgress)
    def conversionCurrent(self):
        return self._conversion_current

    @Property(int, notify=conversionProgress)
    def conversionTotal(self):
        return self._conversion_total

    @Property(bool, notify=analysisStarted)
    def isAnalyzing(self):
        return self._is_analyzing

    @Property(bool, notify=analysisProgress)
    def isAnalysisPaused(self):
        return self._is_analysis_paused

    @Property(int, notify=analysisProgress)
    def analysisCurrent(self):
        return self._analysis_current

    @Property(int, notify=analysisProgress)
    def analysisTotal(self):
        return self._analysis_total

    @Property(str, notify=analysisProgress)
    def aiProgress(self):
        return self._ai_progress

    @Property(bool, notify=analysisStarted)
    def isOffline(self):
        return self._is_offline

    def _check_network(self):
        """V5.3: 后台线程检查网络（不阻塞 UI 启动）"""
        import threading
        def _check():
            try:
                import socket
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3)
                s.connect(("api.deepseek.com", 443))
                s.close()
                self._is_offline = False
            except Exception:
                self._is_offline = True
            self.analysisStarted.emit()  # 触发 QML isOffline 绑定刷新
        threading.Thread(target=_check, daemon=True, name="net-check").start()

    # ── V6.1: 自动更新 ──────────────────────────

    def _check_for_updates(self):
        """后台线程检查 GitHub Release 更新"""
        import threading
        def _check():
            try:
                from ..engine.update_checker import check_for_updates
                result = check_for_updates("6.1.0")
                if result and result.get("version"):
                    self._update_available = True
                    self._update_version = result["version"]
                    self._update_url = result["url"]
                    self._update_body = result.get("body", "")
                    self.updateAvailableChanged.emit()
                    self.updateVersionChanged.emit()
                    self.updateUrlChanged.emit()
                    self.updateBodyChanged.emit()
            except Exception:
                pass
        threading.Thread(target=_check, daemon=True, name="update-check").start()

    @Slot()
    def dismissUpdate(self):
        """忽略当前更新提醒"""
        self._update_available = False
        self.updateAvailableChanged.emit()

    @Slot(result="QVariantMap")
    def downloadUpdate(self):
        """下载更新安装包 → 返回下载结果"""
        import tempfile, os
        try:
            dest = os.path.join(tempfile.gettempdir(),
                                f"MaterialTestingTool-Setup-v{self._update_version}.exe")
            from ..engine.update_checker import download_update

            def _cb(dl, total, pct):
                self._ai_progress = f"下载更新... {pct}%"
                self.analysisProgress.emit(self._ai_progress)

            ok = download_update(self._update_url, dest, progress_callback=_cb)
            if ok:
                return {"ok": True, "path": dest, "message": "下载完成，准备安装"}
            return {"ok": False, "message": "下载失败"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    @Slot(str, result=bool)
    def installUpdate(self, installer_path):
        """运行安装包进行原地覆盖升级"""
        import os, subprocess, sys
        try:
            # 获取当前安装目录
            if getattr(sys, 'frozen', False):
                install_dir = os.path.dirname(sys.executable)
            else:
                install_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cmd = [installer_path, "/S", f"/D={install_dir}"]
            subprocess.Popen(cmd, shell=False)
            return True
        except Exception:
            return False

    @Property(bool, notify=exportStarted)
    def isExporting(self):
        return self._is_exporting

    @Property(int, notify=errorLogChanged)
    def errorLogCount(self):
        return len(self._error_logs)

    @Property(str, notify=errorLogChanged)
    def appVersion(self):
        return "6.1.1"

    # V6.1: 自动更新
    def _getUpdateAvailable(self): return self._update_available
    def _getUpdateVersion(self): return self._update_version or ""
    def _getUpdateUrl(self): return self._update_url or ""
    def _getUpdateBody(self): return self._update_body or ""
    updateAvailableChanged = Signal()
    updateVersionChanged = Signal()
    updateUrlChanged = Signal()
    updateBodyChanged = Signal()
    updateAvailable = Property(bool, _getUpdateAvailable, notify=updateAvailableChanged)
    updateVersion = Property(str, _getUpdateVersion, notify=updateVersionChanged)
    updateUrl = Property(str, _getUpdateUrl, notify=updateUrlChanged)
    updateBody = Property(str, _getUpdateBody, notify=updateBodyChanged)

    @Property("QVariantList", notify=errorLogChanged)
    def errorLogList(self):
        return self._error_logs

    # ── V6.0: 模型切换 Properties ───────────────
    @Property("QVariantList", notify=deepseekModelsChanged)
    def deepseekModels(self):
        return self._deepseek_models

    @Property("QVariantList", notify=qwenModelsChanged)
    def qwenModels(self):
        return self._qwen_models

    @Property(str, notify=currentDeepseekModelChanged)
    def currentDeepseekModel(self):
        return self._current_deepseek_model

    @Property(str, notify=currentQwenModelChanged)
    def currentQwenModel(self):
        return self._current_qwen_model

    @Property(bool, notify=modelsLoadingChanged)
    def modelsLoading(self):
        return self._models_loading

    # ── V6.0: 模型切换 Slots ────────────────────
    @Slot()
    def fetchModels(self):
        """从 API 获取可用模型列表（后台线程）"""
        if self._models_loading:
            return
        import threading
        self._models_loading = True
        self.modelsLoadingChanged.emit()

        def _fetch():
            try:
                from ..engine.model_provider import ModelProviderFactory
                ds_key = self._config.api_key
                if ds_key:
                    ds_list = ModelProviderFactory.list_deepseek_models(ds_key)
                    self._deepseek_models = [{"id": m.get("id", "")} for m in ds_list]
                else:
                    self._deepseek_models = [{"id": "deepseek-v4-flash"}]
                self._qwen_models = [{"id": m.get("id", "")} for m in ModelProviderFactory.list_qwen_models()]
            except Exception as e:
                logger.warning("fetchModels failed: %s", e)
            finally:
                self._models_loading = False
                self.deepseekModelsChanged.emit()
                self.qwenModelsChanged.emit()
                self.modelsLoadingChanged.emit()

        threading.Thread(target=_fetch, daemon=True, name="model-fetch").start()

    @Slot(str)
    def switchDeepseekModel(self, name: str):
        """切换 DeepSeek 模型并持久化"""
        if name and name != self._current_deepseek_model:
            self._current_deepseek_model = name
            self._config.deepseek_model = name
            self.currentDeepseekModelChanged.emit()
            logger.info("DeepSeek model switched to: %s", name)

    @Slot(str)
    def switchQwenModel(self, name: str):
        """切换 Qwen-VL 模型并持久化"""
        if name and name != self._current_qwen_model:
            self._current_qwen_model = name
            self._config.qwen_model = name
            self.currentQwenModelChanged.emit()
            logger.info("Qwen-VL model switched to: %s", name)

    # ── Project Slots ───────────────────────────
    @Slot(str, result=bool)
    def createProject(self, name):
        try:
            pid = self._pm.create_project(name.strip())
            if pid:
                self.projectsChanged.emit()
                return True
        except Exception as e:
            logger.error("createProject: %s", e)
        return False

    @Slot(str, result=bool)
    def deleteProject(self, pid):
        try:
            self._pm.delete_project(pid)
            self.projectDeleted.emit(pid)
            self.projectsChanged.emit()
            if self._current_project_id == pid:
                self._current_project_id = ""
                self.currentProjectChanged.emit("")
            return True
        except Exception as e:
            logger.error("deleteProject: %s", e)
            return False

    @Slot(str, str, result=bool)
    def renameProject(self, pid, name):
        try:
            self._db.update_project_name(pid, name.strip())
            self.projectsChanged.emit()
            return True
        except Exception as e:
            logger.error("renameProject: %s", e)
            return False

    # ── Import Slots ────────────────────────────
    @Slot(str)
    def pickAndImportFiles(self, pid):
        try:
            fps, _ = QFileDialog.getOpenFileNames(
                None, "选择工程文件",
                self._config.last_project_dir or os.path.expanduser("~"),
                "工程文件 (*.dwg *.dxf *.pdf *.docx *.xlsx);;所有文件 (*)"
            )
            if fps:
                self._config.last_project_dir = str(Path(fps[0]).parent)
                self.importFiles(pid, fps)
        except Exception as e:
            logger.error("pickAndImportFiles: %s", e)

    def importFiles(self, pid, fps):
        if not fps:
            return
        added = self._pm.add_files(pid, fps)
        if not added:
            return
        fg = {"cad": [], "pdf": [], "word": [], "excel": []}
        for fp in fps:
            ext = Path(fp).suffix.lower()
            if ext in (".dwg", ".dxf"):
                fg["cad"].append(fp)
            elif ext == ".pdf":
                fg["pdf"].append(fp)
            elif ext in (".docx", ".doc"):
                fg["word"].append(fp)
            elif ext in (".xlsx", ".xls"):
                fg["excel"].append(fp)

        # V5.3: 检测混合文件类型
        type_counts = []
        for t, files in fg.items():
            if files:
                type_counts.append({"type": t, "count": len(files)})
        if len(type_counts) > 1:
            has_cad = bool(fg["cad"])
            has_pdf = bool(fg["pdf"])
            if has_cad and has_pdf:
                logger.info("importFiles: 检测到混合类型 CAD+PDF (%d种, %d文件)",
                           len(type_counts), sum(c["count"] for c in type_counts))
                self.mixedFileTypesDetected.emit(type_counts)

        self._is_importing = True
        self._import_current = 0
        self._import_total = len(fps)
        self._import_message = "开始导入..."
        self._import_start_time = time.time()
        self.importProgress.emit(0, len(fps), "开始导入...")
        self.importStarted.emit()
        self._import_thread = FileImportThread(fg, pid, self._db)
        self._import_thread.progress.connect(self._on_import_progress)
        self._import_thread.file_done.connect(self._on_file_done)
        self._import_thread.error.connect(self._on_import_error)
        self._import_thread.queue_finished.connect(lambda: self._on_import_finished(pid))
        self._import_thread.start()

    def _on_import_progress(self, c, t, m):
        self._import_current = c
        self._import_total = t
        self._import_message = m
        self.importProgress.emit(c, t, m)

    def _on_file_done(self, fp, pid, r):
        if pid:
            self._db.get_files(pid)

    def _on_import_error(self, m):
        self._add_error_log("导入错误", m)
        if not hasattr(self, '_import_errors'):
            self._import_errors = []
        self._import_errors.append(m)

    def _on_import_finished(self, pid):
        el = (time.time() - self._import_start_time) * 1000 if self._import_start_time else 0
        if el < 1500:
            QThread.msleep(int(1500 - el))
        self._is_importing = False
        self._import_message = "导入完成"
        self._import_thread = None
        # V6.1.1: 收集的导入错误弹出提示
        import_errors = getattr(self, '_import_errors', [])
        if import_errors:
            # 去重 + 截取前 5 条
            unique = list(dict.fromkeys(import_errors))
            msg = f"{len(unique)} 个文件导入失败:\n" + "\n".join(f"• {e[:120]}" for e in unique[:5])
            if len(unique) > 5:
                msg += f"\n... 还有 {len(unique) - 5} 个错误"
            self.importError.emit(pid, msg)
            self._import_errors = []
        self.importStarted.emit()
        self.importFinished.emit(pid)
        # V6.0: 不 emit projectsChanged（importFinished→refreshProject 已做增量刷新，projectsChanged 会导致全树折叠）
        self._ensure_files_parsed(pid)

    def _ensure_files_parsed(self, pid):
        import threading as _th
        def _pp():
            pending = self._db.get_unparsed_files(pid)
            if not pending:
                return
            for f in pending:
                fp = f.get("file_path", "")
                if not fp or not os.path.exists(fp):
                    continue
                ft = f.get("file_type", "cad")
                try:
                    if ft == "cad":
                        r = parse_dwg(fp, auto_convert=True)
                    elif ft == "pdf":
                        r = extract_pdf_content(fp)
                    elif ft == "word":
                        from ..engine.word_parser import extract_word_content
                        r = extract_word_content(fp)
                    elif ft == "excel":
                        from ..engine.excel_parser import extract_excel_content
                        r = extract_excel_content(fp)
                    else:
                        continue
                    if r:
                        if ft == "cad":
                            entities = [{"text": t.get("text", str(t)), "layer": t.get("layer", ""),
                                        "x": t.get("pos_x", t.get("x", 0)), "y": t.get("pos_y", t.get("y", 0))}
                                       for t in (r.text_entities or [])]
                            self._db.store_text_entities(f["id"], entities)
                            self._db.update_file_parse_status(f["id"], "done",
                                getattr(r, "discipline", ""), getattr(r, "description", ""))
                        elif isinstance(r, dict) and "text" in r:
                            entities = [{"text": l, "layer": ft.upper(), "x": 0, "y": 0}
                                       for l in r["text"].split("\n")[:20000]]
                            self._db.store_text_entities(f["id"], entities)
                            self._db.update_file_parse_status(f["id"], "done", ft.upper(), "")
                except Exception:
                    import logging; _pp_log = logging.getLogger(__name__)
                    _pp_log.warning("_ensure_files_parsed: 后台解析失败 — file_id=%s", f.get("id"), exc_info=True)
            self.projectsChanged.emit()
        _th.Thread(target=_pp, daemon=True).start()

    @Slot(str, str)
    def replaceFile(self, pid, fid_str):
        try:
            fp, _ = QFileDialog.getOpenFileName(
                None, "选择替换文件",
                self._config.last_project_dir or os.path.expanduser("~"),
                "工程文件 (*.dwg *.dxf *.pdf *.docx *.xlsx);;所有文件 (*)"
            )
            if fp:
                self._db.delete_file(int(fid_str))
                self.importFiles(pid, [fp])
        except Exception as e:
            logger.error("replaceFile: %s", e)

    @Slot(str, int)
    def deleteFile(self, pid, fid):
        try:
            self._db.delete_file(fid)
            # V6.0: 不 emit projectsChanged（会导致全树收起）
            # QML 通过 onImportFinished 触发单个项目的增量刷新
            self.importFinished.emit(pid)
        except Exception as e:
            logger.error("deleteFile: %s", e)

    # ── Conversion Slots ────────────────────────
    @Slot(str)
    def startConversion(self, pid):
        if self._is_converting:
            return
        files = self._db.get_files(pid)
        fc = [f for f in files if f.get("conversion_status") != "done"
              and f.get("file_type") in ("cad", "pdf")]
        if not fc:
            self.conversionStarted.emit()
            self.conversionFinished.emit(pid)
            return
        self._is_converting = True
        self._conversion_current = 0
        self._conversion_total = len(fc)
        self._ai_progress = "预分析文件中..."
        self.analysisProgress.emit("预分析文件中...")
        self.conversionProgress.emit(0, len(fc), "预分析文件中...")
        self.conversionStarted.emit()
        self._profile_thread = ProfileThread(pid, self._db, [f["id"] for f in fc])
        self._profile_thread.progress.connect(self._on_profile_progress)
        self._profile_thread.finished.connect(lambda r: self._start_strategy_conversion(pid, fc))
        logger.info("startConversion: starting ProfileThread with %d files", len(fc))
        self._profile_thread.start()
        logger.info("startConversion: ProfileThread.start() called")

    def _on_profile_progress(self, m):
        self._ai_progress = m
        # V6.0.1: 预分析阶段不递增 _conversion_current（转换阶段会从0开始计数）
        # 避免进度条在预分析阶段就跑到100%
        self._throttled_progress(0, 0, m)  # indeterminate 模式

    def _start_strategy_conversion(self, pid, files):
        self._conversion_thread = StrategyConversionThread(pid, self._db, files)
        self._conversion_thread.progress.connect(lambda m: (setattr(self, '_ai_progress', m), self._throttled_progress(self._conversion_current, self._conversion_total, m)))
        self._conversion_thread.file_progress.connect(self._on_conversion_progress)
        self._conversion_thread.conversion_done.connect(self._on_conversion_done)
        self._conversion_thread.conversion_error.connect(self._on_conversion_error)
        self._conversion_thread.finished.connect(lambda: self._on_conversion_finished(pid))
        self._conversion_thread.start()

    def _on_conversion_progress(self, c, t, m):
        self._conversion_current = c
        self._conversion_total = t
        self._ai_progress = m
        self._throttled_progress(c, t, m)

    def _throttled_progress(self, c, t, m):
        """节流: 最多每 300ms 发射一次进度信号"""
        import time as _t
        now = _t.time()
        last = getattr(self, '_last_progress_ts', 0)
        if now - last >= 0.3 or c >= t:
            self.conversionProgress.emit(c, t, m)
            self.analysisProgress.emit(m)
            self._last_progress_ts = now

    def _on_conversion_done(self, fid, png):
        if not self._is_converting:
            return

    def _on_conversion_error(self, fid, m):
        if not self._is_converting:
            return
        self._add_error_log("转换错误", m, file_id=fid, phase="conversion")

    def _on_conversion_finished(self, pid):
        if not self._is_converting:
            return
        self._is_converting = False
        self._conversion_thread = None
        self._profile_thread = None
        self.conversionStarted.emit()
        self.conversionFinished.emit(pid)
        self.projectsChanged.emit()

    @Slot()
    def cancelConversion(self):
        if self._profile_thread and hasattr(self._profile_thread, 'cancel'):
            self._profile_thread.cancel()
        if self._conversion_thread and hasattr(self._conversion_thread, 'cancel'):
            self._conversion_thread.cancel()
        self._is_converting = False
        self._profile_thread = None
        self._conversion_thread = None
        self.conversionStarted.emit()

    # ── Analysis Slots ──────────────────────────
    @Slot(str)
    def startAnalysis(self, pid):
        if self._is_analyzing:
            return
        # V5.3: 检查后台线程更新的离线状态
        if self._is_offline:
            self._ai_progress = "需要网络连接"
            self.analysisError.emit(pid, "离线状态：需要网络连接才能进行 AI 分析")
            return
        if self._ai_thread:
            self._ai_thread.cancel()
            self._ai_thread = None
        self._is_analyzing = True
        self._is_analysis_paused = False
        self._analysis_current = 0
        self._analysis_total = 100
        self._ai_progress = "准备分析..."
        self.analysisProgress.emit("准备分析...")
        self.analysisStarted.emit()
        dsk = self._config.api_key
        qk = self._config.qwen_api_key
        if not dsk:
            self._ai_progress = "未配置 DeepSeek API Key"
            self._is_analyzing = False
            self.analysisStarted.emit()
            self.analysisError.emit(pid, "未配置 DeepSeek API Key")
            return
        self._ai_thread = AIAnalysisThread(pid, self._db, dsk, qk, self._config)
        self._ai_thread.progress.connect(self._on_analysis_progress)
        self._ai_thread.finished.connect(lambda r: self._on_analysis_finished(pid, r))
        self._ai_thread.error.connect(lambda e: self._on_analysis_error(pid, e))
        self._ai_thread.start()

    def _on_analysis_progress(self, m):
        self._ai_progress = m
        # V6.0.1: 根据消息内容动态更新真实进度
        # 解析阶段: "解析 5 个待处理文件..." → "解析 3/5: xxx"
        # Vision阶段: "Vision: 5 文件, 80 张图"
        # AI阶段: "第1步/第2步"
        import re
        # 解析进度: "解析 N/M: filename"
        parse_match = re.search(r"解析\s+(\d+)/(\d+)", m)
        if parse_match:
            self._analysis_current = int(parse_match.group(1))
            self._analysis_total = max(self._analysis_total, int(parse_match.group(2)))
        # Vision进度: "✅ filename" 在 Vision 阶段
        elif "Vision:" in m:
            # "Vision: 3 缓存, 5 新" → 设置总数为缓存+新
            v_match = re.search(r"Vision:\s*(\d+)\s*缓存.*?(\d+)\s*新", m)
            if v_match:
                self._analysis_total = int(v_match.group(1)) + int(v_match.group(2))
        elif "Vision" in m and "文件" in m:
            v2_match = re.search(r"Vision:\s*(\d+)\s*文件", m)
            if v2_match:
                self._analysis_total = max(self._analysis_total, int(v2_match.group(1)))
        # AI text analysis
        elif "结构检测分析中" in m:
            chunk_match = re.search(r"(\d+)\s*分片", m)
            if chunk_match:
                self._analysis_current += 1
        elif "材料分析中" in m:
            group_match = re.search(r"(\d+)\s*组", m)
            if group_match:
                self._analysis_current += 1
                self._analysis_total = max(self._analysis_total, self._analysis_current + 1)
        elif "完成:" in m:
            self._analysis_current = self._analysis_total  # 100%
        self.analysisProgress.emit(m)

    def _on_analysis_finished(self, pid, r):
        if not self._ai_thread:
            return
        try:
            self._db.store_analysis_result(pid, r)
            # V5.2: 同步路段到 road_sections 表（供 SectionListModel 读取）
            sections = r.get("sections", [])
            if sections:
                self._db.store_road_sections(pid, sections)
        except Exception as e:
            logger.error("store_analysis_result: %s", e)
        self._is_analyzing = False
        self._is_analysis_paused = False
        self._ai_thread = None
        self.analysisStarted.emit()
        self.analysisFinished.emit(pid, r)
        self.projectsChanged.emit()

    def _on_analysis_error(self, pid, m):
        if not self._ai_thread:
            return
        self._is_analyzing = False
        self._is_analysis_paused = False
        self._ai_thread = None
        self._add_error_log("分析错误", m)
        self.analysisStarted.emit()
        self.analysisError.emit(pid, m)

    @Slot()
    def cancelAnalysis(self):
        if self._ai_thread:
            old = self._ai_thread
            old.cancel()         # V5.3: 先 cancel（让信号处理完），再清引用
            self._ai_thread = None
        self._is_analyzing = False
        self._is_analysis_paused = False
        self.analysisStarted.emit()

    @Slot()
    def pauseAnalysis(self):
        if self._ai_thread:
            self._ai_thread.pause()
            self._is_analysis_paused = True
            self.analysisProgress.emit(self._ai_progress)

    @Slot()
    def resumeAnalysis(self):
        if self._ai_thread:
            self._ai_thread.resume()
            self._is_analysis_paused = False
            self.analysisProgress.emit(self._ai_progress)

    # ── Export Slots ─────────────────────────────
    @Slot(str, str, "QVariantList")
    def exportExcel(self, pid, output_path="", selected_sections=None):
        if self._is_exporting:
            return
        proj = self._db.get_project(pid)
        if not proj:
            return
        result = self._db.get_latest_analysis(pid) or {}
        # V6.0: 从 testing_plan_items 表读取（用户编辑后的数据），非 analysis_results（AI原始输出）
        plan = self._db.get_testing_plan_items(pid)
        if not plan:
            # 回退：无编辑数据时使用原始 AI 结果
            plan = result.get("testing_plan", [])
        if selected_sections:
            sec_names = set()
            for s in selected_sections:
                if isinstance(s, dict):
                    sec_names.add(s.get("sectionName", s.get("section", "")))
                else:
                    sec_names.add(str(s))
            plan = [p for p in plan if p.get("section", "") in sec_names]
        if not output_path:
            output_path, _ = QFileDialog.getSaveFileName(
                None, "导出检测计划",
                f"{proj.get('name', '检测计划')}.xlsx",
                "Excel文件 (*.xlsx)"
            )
        if not output_path:
            return
        self._is_exporting = True
        self.exportStarted.emit()
        self._export_thread = ExportThread(
            output_path, result.get("project_info", {}), plan,
            result.get("contract_info", {}), result.get("key_notes", []),
            proj.get("name", ""), result.get("sections", []),
            result.get("construction_layers"),
        )
        self._export_thread.finished.connect(self._on_export_finished)
        self._export_thread.error.connect(self._on_export_error)
        self._export_thread.progress.connect(lambda m: setattr(self, '_ai_progress', m))  # V6.0.1
        self._export_thread.start()

    def _on_export_finished(self, op):
        self._is_exporting = False
        self._export_thread = None
        self.exportStarted.emit()
        self.exportFinished.emit(op)

    def _on_export_error(self, m):
        self._is_exporting = False
        self._export_thread = None
        self._add_error_log("导出错误", m)
        self.exportStarted.emit()
        self.exportError.emit(m)

    # ── Settings ─────────────────────────────────
    @Slot(str, str)
    def configureApiKey(self, dk, qk):
        self._config.api_key = dk
        self._config.qwen_api_key = qk

    @Slot(result="QVariantMap")
    def getApiKeys(self):
        return {"ds_key": self._config.api_key or "", "qwen_key": self._config.qwen_api_key or ""}

    @Slot(result="QVariantMap")
    def getApiUsageStats(self):
        """V5.2: 返回 API 用量统计（总调用次数/总Token/平均耗时）"""
        try:
            rows = self._db._conn.execute(
                "SELECT COUNT(*) as calls, COALESCE(SUM(latency_ms),0) as total_ms, "
                "COALESCE(SUM(token_count),0) as total_tokens, "
                "COALESCE(AVG(latency_ms),0) as avg_ms "
                "FROM ai_cache WHERE latency_ms > 0"
            ).fetchone()
            if rows and rows[0] > 0:
                return {
                    "total_calls": rows[0],
                    "total_tokens": rows[2],
                    "total_latency_ms": rows[1],
                    "avg_latency_ms": int(rows[3]),
                }
        except Exception:
            pass
        return {"total_calls": 0, "total_tokens": 0, "total_latency_ms": 0, "avg_latency_ms": 0}

    @Slot(result="QVariantList")
    def getStandards(self, keyword=""):
        """V5.2: 返回标准列表（供 QML 直接调用）"""
        try:
            return self._db.search_standards(keyword)
        except Exception:
            return []

    @Slot(str, result="QVariantMap")
    def importStandardsUpdate(self, file_path):
        """V5.3: 导入标准年度替换文件，返回预览"""
        try:
            from ..engine.standards_updater import (
                parse_standard_file, match_series, generate_preview,
                validate_standards, _extract_series,
            )
            parsed = parse_standard_file(file_path)
            if parsed["errors"]:
                return {"ok": False, "error": "\n".join(parsed["errors"]), "preview": ""}

            new_standards = parsed["standards"]
            # 为每个标准计算 series
            for s in new_standards:
                s["series"] = _extract_series(s.get("code", ""))

            # 获取现有活跃标准
            existing = []
            if self._db:
                try:
                    rows = self._db._conn.execute(
                        "SELECT code, name, type, discipline, keywords, scope, version_year "
                        "FROM standards WHERE is_active=1"
                    ).fetchall()
                    for r in rows:
                        existing.append({
                            "code": r[0], "name": r[1], "type": r[2],
                            "discipline": r[3], "keywords": json.loads(r[4]) if r[4] else [],
                            "scope": r[5], "version_year": r[6],
                        })
                except Exception as e:
                    logger.warning("importStandardsUpdate: 获取现有标准失败 — %s", e)

            replacements, new_only = match_series(new_standards, existing)
            preview = generate_preview(replacements, new_only)

            # 校验新标准
            validation_errors = validate_standards(new_standards)
            if validation_errors:
                return {"ok": False, "error": "校验失败:\n" + "\n".join(validation_errors), "preview": preview}

            # 执行替换
            if self._db and (replacements or new_only):
                replace_map = [
                    {"old_code": r["old"]["code"], "new": r["new"]}
                    for r in replacements
                ]
                result = self._db.update_standards(replace_map, new_only)
                if result["errors"]:
                    return {"ok": False, "error": "\n".join(result["errors"]), "preview": preview}
                logger.info(
                    "importStandardsUpdate: replaced=%d, added=%d",
                    result["replaced"], result["added"],
                )
                return {
                    "ok": True,
                    "preview": preview,
                    "replaced": result["replaced"],
                    "added": result["added"],
                }

            return {"ok": True, "preview": preview, "replaced": 0, "added": 0}
        except Exception as e:
            import traceback
            logger.error("importStandardsUpdate: %s", traceback.format_exc())
            return {"ok": False, "error": str(e), "preview": ""}

    @Slot("QVariantList", result=int)
    def saveEditingChanges(self, modified_cells):
        """V5.3: 保存编辑模式下的批量修改"""
        if not modified_cells or not self._db:
            return 0
        try:
            items = []
            for cell in (modified_cells or []):
                if isinstance(cell, dict):
                    items.append({
                        "id": cell.get("id", 0),
                        "key": cell.get("key", ""),
                        "value": cell.get("value", ""),
                    })
            count = self._db.batch_update_plan_items(items)
            logger.info("saveEditingChanges: saved %d cells", count)
            return count
        except Exception as e:
            logger.error("saveEditingChanges failed: %s", e)
            return -1

    @Slot()
    def openStandardsWindow(self):
        """V6.1: 打开参考标准库独立窗口"""
        from PySide6.QtQml import QQmlApplicationEngine
        from PySide6.QtCore import QUrl
        import logging
        _log = logging.getLogger(__name__)
        try:
            engine = getattr(self, '_standards_engine', None)
            if engine is not None:
                for obj in engine.rootObjects():
                    obj.show()
                    obj.raise_()
                    obj.requestActivate()
                    return
            engine = QQmlApplicationEngine()
            self._standards_engine = engine
            engine.rootContext().setContextProperty("AppState", self)
            # AppTheme 已由 main.py 的 qmlRegisterSingletonInstance 进程级注册，无需再注册
            # V6.1: _MEIPASS 兼容
            import sys, os as _os
            _meipass = getattr(sys, "_MEIPASS", None)
            if _meipass:
                qml_path = _os.path.join(_meipass, "qml", "StandardsWindow.qml")
            else:
                qml_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "qml", "StandardsWindow.qml")
            engine.load(QUrl.fromLocalFile(qml_path))
        except Exception as e:
            _log.error("openStandardsWindow: %s", e, exc_info=True)

    @Slot(str, str, result="QVariantMap")
    def testConnection(self, dk, qk):
        """V5.2: 同步连接测试，直接返回结果给 QML"""
        import requests
        r = {"ds_ok": False, "ds_msg": "", "qwen_ok": False, "qwen_msg": ""}
        if dk:
            try:
                resp = requests.post("https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {dk}", "Content-Type": "application/json"},
                    json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "say ok"}], "max_tokens": 10},
                    timeout=10)
                if resp.status_code == 200:
                    r["ds_ok"] = True; r["ds_msg"] = "连接成功"
                elif resp.status_code == 401:
                    r["ds_msg"] = "API Key无效(401)"
                else:
                    r["ds_msg"] = f"HTTP {resp.status_code}"
            except Exception as e:
                r["ds_msg"] = f"{type(e).__name__}: {str(e)[:80]}"
        else:
            r["ds_msg"] = "未配置"
        if qk:
            try:
                resp = requests.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                    headers={"Authorization": f"Bearer {qk}", "Content-Type": "application/json"},
                    json={"model": "qwen-plus", "messages": [{"role": "user", "content": "say ok"}], "max_tokens": 10},
                    timeout=10)
                if resp.status_code == 200:
                    r["qwen_ok"] = True; r["qwen_msg"] = "连接成功"
                elif resp.status_code == 401:
                    r["qwen_msg"] = "API Key无效(401)"
                else:
                    r["qwen_msg"] = f"HTTP {resp.status_code}"
            except Exception as e:
                r["qwen_msg"] = f"{type(e).__name__}: {str(e)[:80]}"
        else:
            r["qwen_msg"] = "未配置"
        return r

    @Slot(str, str, result="QVariantList")
    def getConstructionLayers(self, pid, sn):
        try:
            return self._db.get_construction_layers(pid, sn) or []
        except Exception:
            return []

    @Slot(result=str)
    def getAboutInfo(self):
        from PySide6.QtWidgets import QApplication
        ver = QApplication.applicationVersion() or "6.0.0"
        return (
            f"工程材料送检分析系统 V{ver}\n\n"
            "基于 GB55032-2022\n"
            "自动分析工程图纸并生成材料检测送检计划\n\n"
            "技术栈: Python/PySide6 + DeepSeek + Qwen-VL\n\n"
            "V5.2: shadcn Zinc主题 + 结构化异常 + AI可观测性 + 离线可用 + 标准知识库"
        )

    # ── Error Log ────────────────────────────────
    def _add_error_log(self, level, msg, file_id=None, phase=None):
        from datetime import datetime
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": msg,
        }
        if file_id is not None:
            entry["file_id"] = file_id
        if phase is not None:
            entry["phase"] = phase
        self._error_logs.append(entry)
        if len(self._error_logs) > self._error_log_max:
            self._error_logs = self._error_logs[-self._error_log_max:]
        self.errorLogChanged.emit()

    @Slot(result="QVariantList")
    def getErrorLog(self):
        return self._error_logs

    @Slot()
    def clearErrorLog(self):
        self._error_logs.clear()
        self.errorLogChanged.emit()


_app_state_instance = None


def get_app_state() -> AppState:
    global _app_state_instance
    if _app_state_instance is None:
        _app_state_instance = AppState()
    return _app_state_instance
