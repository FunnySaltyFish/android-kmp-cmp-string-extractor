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
    
    if not project_path:
        return jsonify({'error': '请提供项目路径'}), 400
    
    try:
        extractor = ChineseStringExtractor(project_path)
        current_strings = extractor.extract_all_strings()
        
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
        
        # 更新字符串信息
        result_dict = {}
        for i, id in enumerate(selected_ids):
            if i >= len(results):
                print(f"翻译结果数量不足，selected_ids size: {len(selected_ids)}, results size: {len(results)}")
                break
            trans = results[i]
            if (idx := id.find(":")) > 0:
                unique_id = id[:idx] + ":" + trans.get("name")
                result_dict[unique_id] = trans
        
        print("result_dict: ", result_dict)

        for s in current_strings:
            if s.unique_id in result_dict:
                result = result_dict[s.unique_id]
                s.translation = result.get('translation', '')
                s.resource_name = result.get('resource_name', '')
        
        return jsonify({
            'success': True,
            'results': results,
            'strings': [asdict(s) for s in current_strings]
        })
        
    except Exception as e:
        return jsonify({'error': f'翻译失败: {str(e)}'}), 500

@app.route('/api/save', methods=['POST'])
def save_changes():
    """保存更改API"""
    global current_strings, extractor
    
    data = request.json
    updated_strings = data.get('strings', [])
    ignored_strings = data.get('ignored_strings', [])
    
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
        replacer = StringReplacer(extractor.project_root)
        
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
            
            # 生成中文strings.xml
            replacer.generate_strings_xml(module_path, strings, "zh")
            # 生成英文strings.xml  
            replacer.generate_strings_xml(module_path, strings, "en")
            
            # 执行字符串替换
            for s in strings:
                file_path = extractor.project_root / s.file_path
                replacer.replace_strings_in_file(file_path, {s.text: s.resource_name})
        
        return jsonify({'success': True, 'message': '保存成功'})
        
    except Exception as e:
        return jsonify({'error': f'保存失败: {str(e)}'}), 500

if __name__ == '__main__':
    print("启动中文字符串提取工具...")
    print("请在浏览器中访问: http://localhost:5000")
    app.run(debug=True, port=5000)