#!/usr/bin/env python3
import json
import os
import signal
import sys
import atexit
from pathlib import Path
from typing import List, Optional
from dataclasses import asdict
from flask import Flask, request, jsonify
from helper import ChineseString, StringReplacer, TranslationService, ChineseStringExtractor

# Flask Web应用
app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

# 全局变量
extractor = None
translation_service = None
current_strings: List[ChineseString] = []
batch_translation_state = {
    'is_running': False,
    'current_batch': 0,
    'total_batches': 0,
    'failed_batches': []
}
 
extracted_dir = "static/extracted"
extracted_file = extracted_dir + "/test.json"

# 赞助信息
SPONSOR_URL = "https://web.funnysaltyfish.fun/?source=string_extractor_api"
_sponsor_tip_printed = False


def print_sponsor_tip_once(reason: Optional[str] = None) -> None:
    """在退出/中断时打印赞助提示，只打印一次。"""
    global _sponsor_tip_printed
    if _sponsor_tip_printed:
        return
    _sponsor_tip_printed = True
    if reason:
        print(f"\n提示：{reason}")
    print("觉得好用？感觉有帮助？支持作者以继续开发：")
    print(SPONSOR_URL + "\n")


def _register_exit_hooks() -> None:
    """注册退出钩子与信号处理。"""
    # atexit 钩子
    atexit.register(lambda: print_sponsor_tip_once("程序已退出"))

    # SIGINT (Ctrl+C)
    try:
        previous_sigint = signal.getsignal(signal.SIGINT)

        def _handle_sigint(signum, frame):
            print_sponsor_tip_once("检测到 Ctrl+C，正在退出")
            if callable(previous_sigint) and previous_sigint not in (signal.SIG_DFL, signal.SIG_IGN):
                try:
                    previous_sigint(signum, frame)
                except Exception:
                    pass

        signal.signal(signal.SIGINT, _handle_sigint)
    except Exception:
        pass

    # SIGTERM
    try:
        sigterm = getattr(signal, "SIGTERM", None)
        if sigterm is not None:
            previous_sigterm = signal.getsignal(sigterm)

            def _handle_sigterm(signum, frame):
                print_sponsor_tip_once("收到停止信号，正在退出")
                if callable(previous_sigterm) and previous_sigterm not in (signal.SIG_DFL, signal.SIG_IGN):
                    try:
                        previous_sigterm(signum, frame)
                    except Exception:
                        pass

            signal.signal(sigterm, _handle_sigterm)
    except Exception:
        pass

@app.route('/')
def index():
    """主页"""
    return app.send_static_file('index.html')

@app.route('/api/load_extracted', methods=['POST'])
def load_extracted():
    """加载已提取的字符串API"""
    global current_strings
    path = Path(extracted_dir)
    if not path.exists():
        return jsonify({'success': False, 'message': '提取文件不存在'})
    with open(path, 'r', encoding='utf-8') as f:
        current_strings = [ChineseString(**s) for s in json.load(f)]
    return jsonify({'success': True, 'strings': current_strings})

@app.route("/api/update_current_strings", methods=['POST'])
def update_current_strings():
    """更新当前字符串API"""
    global current_strings
    data = request.json
    strings = data.get('strings', [])
    for s in strings:
        s.pop("unique_id", None)
        s["translation"] = s.pop("english_translation", "")
    current_strings = [ChineseString(**s) for s in strings]
    return jsonify({'success': True})

@app.route('/api/extract', methods=['POST'])
def extract_strings():
    """提取字符串API"""
    global current_strings, extractor
    
    data = request.json
    project_path = data.get('project_path', '')
    extraction_globs = data.get('extraction_globs') or []
    
    if not project_path:
        return jsonify({'error': '请提供项目路径'}), 400
    
    try:
        extractor = ChineseStringExtractor(project_path)
        current_strings = extractor.extract_all_strings(extraction_globs or None)
        
        return jsonify({
            'success': True,
            'count': len(current_strings),
            'strings': [asdict(s) for s in current_strings]
        })
    except Exception as e:
        return jsonify({'error': f'提取失败: {str(e)}'}), 500

@app.route('/api/translate', methods=['POST'])
def translate_strings():
    """翻译字符串API"""
    global current_strings, translation_service
    
    data = request.json
    api_key = data.get('api_key', '')
    base_url = data.get('base_url', '')
    selected_ids: list[str] = data.get('selected_ids', [])
    
    # 新增配置参数
    model_name = data.get('model_name', 'gpt-4o-mini')
    custom_prompt = data.get('custom_prompt', '')
    batch_size = data.get('batch_size', 50)
    reference_translations = data.get('reference_translations', '')
    
    if not api_key:
        return jsonify({'error': '请提供API Key'}), 400
    
    try:
        translation_service = TranslationService(
            api_key, 
            base_url, 
            model_name=model_name,
            custom_prompt=custom_prompt,
            batch_size=batch_size,
            reference_translations=reference_translations
        )
        
        print("selected_ids:", selected_ids)
        print("current_strings:", current_strings[:5])
        # 筛选选中的字符串
        selected_strings = [s for s in current_strings if s.unique_id in selected_ids]
        
        if not selected_strings:
            return jsonify({'error': '没有选择要翻译的字符串'}), 400
        
        # 批量翻译
        results = translation_service.translate_batch(selected_strings)
        
        # 更新字符串信息，按index直接匹配
        selected_strings_dict = {s.unique_id: s for s in selected_strings}
        
        for i, unique_id in enumerate(selected_ids):
            if i >= len(results):
                print(f"翻译结果数量不足，selected_ids size: {len(selected_ids)}, results size: {len(results)}")
                break
            
            if unique_id in selected_strings_dict:
                trans = results[i]
                string_obj = selected_strings_dict[unique_id]
                string_obj.translation = trans.get('translation', '')
                string_obj.resource_name = trans.get('name', '') or trans.get('resource_name', '')
                # 新增：可选参数名列表（仅在必要时由 AI 提供）
                if isinstance(trans.get('arg_names'), list):
                    string_obj.arg_names = [str(x) for x in trans.get('arg_names')]
                # 新增：可选 args 鍵值对（优先于 arg_names 使用）
                if isinstance(trans.get('args'), list):
                    try:
                        string_obj.args = [
                            { 'name': str(it.get('name', '')).strip(), 'value': str(it.get('value', '')).strip() }
                            for it in trans.get('args') if isinstance(it, dict)
                        ]
                    except Exception:
                        pass
        
        print(f"翻译完成，更新了 {min(len(selected_ids), len(results))} 个字符串")
        
        # 仅返回本次选择的条目（增量返回），避免前端被全量列表覆盖
        incremental_strings = [asdict(selected_strings_dict[uid]) for uid in selected_ids if uid in selected_strings_dict]
        return jsonify({
            'success': True,
            'results': results,
            'updated_count': min(len(selected_ids), len(results)),
            'strings': incremental_strings
        })
        
    except Exception as e:
        return jsonify({'error': f'翻译失败: {str(e)}'}), 500

@app.route('/api/translate_batch', methods=['POST'])
def translate_batch_api():
    """批次翻译API - 支持分批处理大量字符串"""
    global current_strings, translation_service
    
    data = request.json
    api_key = data.get('api_key', '')
    base_url = data.get('base_url', '')
    selected_ids: list[str] = data.get('selected_ids', [])
    batch_index = data.get('batch_index', 0)
    
    # 配置参数
    model_name = data.get('model_name', 'gpt-4o-mini')
    custom_prompt = data.get('custom_prompt', '')
    reference_translations = data.get('reference_translations', '')
    target_language = data.get('target_language', 'en')
    
    if not api_key:
        return jsonify({'error': '请提供API Key'}), 400
    
    print(f"开始处理批次 {batch_index + 1}，包含 {len(selected_ids)} 个字符串")
    
    try:
        # 筛选当前批次的字符串
        selected_strings = [s for s in current_strings if s.unique_id in selected_ids]
        
        if not selected_strings:
            return jsonify({'error': f'批次 {batch_index + 1} 中没有找到要翻译的字符串'}), 400
        
        # 初始化或更新翻译服务
        translation_service = TranslationService(
            api_key, 
            base_url, 
            model_name=model_name,
            custom_prompt=custom_prompt,
            batch_size=len(selected_strings),  # 使用实际批次大小
            reference_translations=reference_translations,
            target_language=target_language
        )
        
        print(f"翻译服务初始化完成，准备翻译 {len(selected_strings)} 个字符串")
        
        # 翻译当前批次
        results = translation_service.translate_batch(selected_strings)
        
        if not results:
            return jsonify({'error': f'批次 {batch_index + 1} 翻译失败：未获得翻译结果'}), 500
        
        print(f"翻译完成，获得 {len(results)} 个翻译结果")
        
        # 更新字符串信息
        selected_strings_dict = {s.unique_id: s for s in selected_strings}
        updated_count = 0
        translation_errors = []
        
        for i, unique_id in enumerate(selected_ids):
            if i >= len(results):
                translation_errors.append(f"结果索引 {i} 超出范围")
                break
            
            if unique_id in selected_strings_dict:
                trans = results[i]
                string_obj = selected_strings_dict[unique_id]
                
                # 验证翻译结果
                if isinstance(trans, dict):
                    translation = trans.get('translation', '').strip()
                    resource_name = (trans.get('name', '') or trans.get('resource_name', '')).strip()
                    
                    if translation and resource_name:
                        string_obj.translation = translation
                        string_obj.resource_name = resource_name
                        # 新增：写入可选 arg_names
                        if isinstance(trans.get('arg_names'), list):
                            string_obj.arg_names = [str(x) for x in trans.get('arg_names')]
                        # 新增：可选 args（优先于 arg_names 使用）
                        if isinstance(trans.get('args'), list):
                            try:
                                string_obj.args = [
                                    { 'name': str(it.get('name', '')).strip(), 'value': str(it.get('value', '')).strip() }
                                    for it in trans.get('args') if isinstance(it, dict)
                                ]
                            except Exception:
                                pass
                        updated_count += 1
                    else:
                        translation_errors.append(f"字符串 '{string_obj.text}' 翻译结果不完整")
                else:
                    translation_errors.append(f"字符串 '{string_obj.text}' 翻译结果格式错误")
            else:
                translation_errors.append(f"未找到 unique_id: {unique_id}")
        
        print(f"批次 {batch_index + 1} 处理完成，成功更新 {updated_count} 个字符串")
        
        if translation_errors:
            print(f"翻译过程中出现的错误: {translation_errors}")
        
        # 仅返回本批更新涉及的条目（增量返回）
        incremental_strings = [asdict(selected_strings_dict[uid]) for uid in selected_ids if uid in selected_strings_dict]
        response_data = {
            'success': True,
            'batch_index': batch_index,
            'current_batch_size': len(selected_ids),
            'updated_count': updated_count,
            'errors': translation_errors if translation_errors else None,
            'strings': incremental_strings
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        error_msg = f'批次 {batch_index + 1} 翻译失败: {str(e)}'
        print(error_msg)
        import traceback
        traceback.print_exc()
        return jsonify({'error': error_msg}), 500

@app.route('/api/extract_references', methods=['POST'])
def extract_references():
    """提取参考翻译API"""
    global extractor
    
    data = request.json
    project_path = data.get('project_path', '')
    source_xml_path = data.get('source_xml_path', '{module_name}/src/commonMain/libres/strings/strings_zh.xml')
    target_language = data.get('target_language', 'en')
    target_xml_path = data.get('target_xml_path', '{module_name}/src/commonMain/libres/strings/strings_{target_language}.xml')
    limit = data.get('limit', 10)
    
    if not project_path:
        return jsonify({'error': '请提供项目路径'}), 400
    
    try:
        # 初始化extractor（如果还没有）
        if not extractor:
            extractor = ChineseStringExtractor(project_path)
        
        # 提取参考翻译
        references = extractor.extract_reference_translations(
            source_xml_path, target_language, target_xml_path, limit
        )
        
        return jsonify({
            'success': True,
            'references': references,
            'count': len(references)
        })
        
    except Exception as e:
        return jsonify({'error': f'提取参考翻译失败: {str(e)}'}), 500

@app.route('/api/save', methods=['POST'])
def save_changes():
    """保存更改API"""
    global current_strings, extractor
    
    data = request.json
    project_root = data.get('project_root', '')
    if not project_root:
        return jsonify({'error': '请提供项目路径'}), 400
    
    project_root = Path(project_root)
    if not project_root.exists():
        return jsonify({'error': f'项目路径 {project_root} 不存在'}), 400
    
    # 仅接收已翻译好的字符串（增量），避免全量覆盖
    updated_strings = data.get('strings', [])
    ignored_strings = data.get('ignored_strings', [])
    target_xml_path_template = data.get('target_xml_path_template')
    target_language = data.get('target_language', 'en')
    replacement_script = data.get('replacement_script', '')
    
    try:
        # 更新字符串信息
        strings_dict = {s.unique_id: s for s in current_strings}
        for updated in updated_strings:
            unique_id = updated.get('unique_id') or f"{updated.get('file_path', '')}:{updated.get('line_number', '')}"
            if unique_id in strings_dict:
                s = strings_dict[unique_id]
                # 覆盖资源名与翻译
                s.resource_name = updated.get('resource_name', s.resource_name)
                # 兼容前端字段名可能为 translation
                s.translation = updated.get('translation', updated.get('english_translation', s.translation))
                # 兼容 args（优先）
                if isinstance(updated.get('args'), list):
                    try:
                        s.args = [
                            { 'name': str(it.get('name', '')).strip(), 'value': str(it.get('value', '')).strip() }
                            for it in updated.get('args') if isinstance(it, dict)
                        ]
                    except Exception:
                        pass
        
        # 保存忽略的字符串
        if ignored_strings:
            extractor.ignored_strings.update(ignored_strings)
            extractor.save_ignored_strings(extractor.ignored_strings)
        
        # 按模块分组字符串
        modules = {}
        replacer = StringReplacer(project_root, replacement_script=replacement_script)
        
        for s in current_strings:
            if not s.resource_name or not s.translation:
                continue
                
            # 确定模块路径
            file_path = Path(s.file_path)
            module_name = file_path.parts[0] if file_path.parts else "common"
            
            if module_name not in modules:
                modules[module_name] = []
            modules[module_name].append(s)
        
        # 生成XML文件和执行替换
        for module_name, strings in modules.items():

            # 根据模板生成中文/目标语言 XML
            replacer.generate_strings_xml_with_template(
                module_name, strings, "zh", target_xml_path_template.replace('{target_language}', 'zh') if target_xml_path_template else None
            )
            replacer.generate_strings_xml_with_template(
                module_name, strings, target_language, target_xml_path_template
            )

            # 执行高级替换（带脚本与 import 插入）
            # 按文件聚合，减少重复读写
            file_to_strings: dict[str, list] = {}
            for s in strings:
                file_to_strings.setdefault(s.file_path, []).append(s)

            for rel_path, strs in file_to_strings.items():
                file_path = project_root / rel_path
                replacer.replace_strings_in_file_advanced(file_path, strs, module_name)
        
        return jsonify({'success': True, 'message': '保存成功'})
        
    except Exception as e:
        return jsonify({'error': f'保存失败: {str(e)}'}), 500

if __name__ == '__main__':
    # 仅在实际运行的进程中注册（避免 Flask debug 重载导致多次注册）
    is_reloader_child = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    if not os.environ.get('FLASK_RUN_FROM_CLI') or is_reloader_child:
        _register_exit_hooks()

    print("启动中文字符串提取工具...")
    print("请在浏览器中访问: http://localhost:5000")
    try:
        app.run(debug=True, port=5000)
    except KeyboardInterrupt:
        # 兜底：Ctrl+C 时打印一次提示
        print_sponsor_tip_once("检测到 Ctrl+C，正在退出")
        sys.exit(0)