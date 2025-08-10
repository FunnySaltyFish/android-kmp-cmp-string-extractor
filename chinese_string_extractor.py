#!/usr/bin/env python3
import json
from pathlib import Path
from typing import List
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
        
        print(f"翻译完成，更新了 {min(len(selected_ids), len(results))} 个字符串")
        
        return jsonify({
            'success': True,
            'results': results,
            'strings': [asdict(s) for s in current_strings]
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
        
        response_data = {
            'success': True,
            'batch_index': batch_index,
            'current_batch_size': len(selected_ids),
            'updated_count': updated_count,
            'errors': translation_errors if translation_errors else None,
            'strings': [asdict(s) for s in current_strings]
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
                s.resource_name = updated.get('resource_name', s.resource_name)
                s.translation = updated.get('english_translation', s.translation)
        
        # 保存忽略的字符串
        if ignored_strings:
            extractor.ignored_strings.update(ignored_strings)
            extractor.save_ignored_strings(extractor.ignored_strings)
        
        # 按模块分组字符串
        modules = {}
        replacer = StringReplacer(extractor.project_root, replacement_script=replacement_script)
        
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
            module_path = extractor.project_root / module_name

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
                file_path = extractor.project_root / rel_path
                replacer.replace_strings_in_file_advanced(file_path, strs, module_name)
        
        return jsonify({'success': True, 'message': '保存成功'})
        
    except Exception as e:
        return jsonify({'error': f'保存失败: {str(e)}'}), 500

if __name__ == '__main__':
    print("启动中文字符串提取工具...")
    print("请在浏览器中访问: http://localhost:5000")
    app.run(debug=True, port=5000)