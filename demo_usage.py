#!/usr/bin/env python3
"""
使用示例：演示如何使用中文字符串提取工具
这个脚本展示了如何通过代码直接调用工具的功能
"""

from chinese_string_extractor import ChineseStringExtractor, TranslationService, StringReplacer
import json

def demo_extract_and_translate():
    """演示提取和翻译功能"""
    
    # 1. 初始化提取器
    project_root = "D:/projects/kotlin/Transtation"  # 修改为你的项目路径
    extractor = ChineseStringExtractor(project_root)
    
    print("🔍 正在提取中文字符串...")
    
    # 2. 提取所有中文字符串
    strings = extractor.extract_all_strings()
    
    print(f"✅ 找到 {len(strings)} 个中文字符串")
    
    # 3. 显示提取结果
    for i, s in enumerate(strings[:5], 1):  # 只显示前5个
        print(f"\n{i}. 文本: {s.text}")
        print(f"   文件: {s.file_path}:{s.line_number}")
        print(f"   上下文: {s.context[:100]}...")
        if s.is_format_string:
            print(f"   格式化参数: {s.format_params}")
    
    if len(strings) > 5:
        print(f"\n... 还有 {len(strings) - 5} 个字符串")
    
    # 4. 模拟翻译（需要API Key）
    api_key = input("\n请输入你的 OpenAI API Key (按回车跳过翻译): ").strip()
    
    if api_key:
        print("\n🌐 正在翻译...")
        translator = TranslationService(api_key)
        
        # 选择前3个字符串进行翻译
        selected_strings = strings[:3]
        results = translator.translate_batch(selected_strings)
        
        print(f"✅ 翻译完成，共 {len(results)} 个结果")
        
        # 更新字符串信息
        result_dict = {r['hash_id']: r for r in results}
        for s in strings:
            if s.hash_id in result_dict:
                result = result_dict[s.hash_id]
                s.resource_name = result.get('resource_name', '')
                s.translation = result.get('translation', '')
        
        # 显示翻译结果
        for s in selected_strings:
            if s.resource_name:
                print(f"\n原文: {s.text}")
                print(f"资源名: {s.resource_name}")
                print(f"翻译: {s.translation}")
    
    # 5. 保存结果到文件（用于调试）
    output_file = "extracted_strings.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump([{
            'text': s.text,
            'file_path': s.file_path,
            'line_number': s.line_number,
            'resource_name': s.resource_name,
            'english_translation': s.translation,
            'is_format_string': s.is_format_string,
            'format_params': s.format_params
        } for s in strings], f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 结果已保存到 {output_file}")
    
    return strings

def demo_file_analysis():
    """演示单个文件分析"""
    from pathlib import Path
    
    project_root = "D:/projects/kotlin/Transtation"  # 修改为你的项目路径
    extractor = ChineseStringExtractor(project_root)
    
    # 分析AsrViewModel.kt文件
    file_path = Path(project_root) / "ai/src/commonMain/kotlin/com/funny/compose/ai/voice/viewmodel/AsrViewModel.kt"
    
    if file_path.exists():
        print(f"🔍 正在分析文件: {file_path.name}")
        strings = extractor.extract_strings_from_file(file_path)
        
        print(f"✅ 在该文件中找到 {len(strings)} 个中文字符串")
        
        for i, s in enumerate(strings, 1):
            print(f"\n{i}. 第{s.line_number}行: {s.text}")
            if s.is_format_string:
                print(f"   格式化参数: {s.format_params}")
    else:
        print(f"❌ 文件不存在: {file_path}")

def demo_generate_xml():
    """演示XML文件生成"""
    from pathlib import Path
    
    project_root = "D:/projects/kotlin/Transtation"
    replacer = StringReplacer(project_root)
    
    # 创建示例字符串数据
    from chinese_string_extractor import ChineseString
    
    sample_strings = [
        ChineseString(
            text="登录成功",
            file_path="login/src/main/kotlin/Login.kt",
            line_number=42,
            context="toast(\"登录成功\")",
            hash_id="test001",
            resource_name="login_success",
            translation="Login successful"
        ),
        ChineseString(
            text="用户名不能为空",
            file_path="login/src/main/kotlin/Login.kt", 
            line_number=55,
            context="if (username.isEmpty()) { error(\"用户名不能为空\") }",
            hash_id="test002",
            resource_name="username_cannot_be_empty",
            translation="Username cannot be empty"
        )
    ]
    
    # 生成XML文件
    module_path = Path(project_root) / "login"
    
    print("📝 正在生成示例 XML 文件...")
    
    success_zh = replacer.generate_strings_xml(module_path, sample_strings, "zh")
    success_en = replacer.generate_strings_xml(module_path, sample_strings, "en")
    
    if success_zh and success_en:
        print("✅ XML 文件生成成功")
        print(f"中文文件: {module_path}/src/commonMain/libres/strings/strings_zh.xml")
        print(f"英文文件: {module_path}/src/commonMain/libres/strings/strings_en.xml")
    else:
        print("❌ XML 文件生成失败")

if __name__ == "__main__":
    print("🌐 Transtation 中文字符串提取工具 - 使用演示")
    print("=" * 50)
    
    while True:
        print("\n请选择演示功能:")
        print("1. 完整的提取和翻译流程")
        print("2. 单个文件分析")
        print("3. XML文件生成演示")
        print("4. 退出")
        
        choice = input("\n请输入选项 (1-4): ").strip()
        
        if choice == "1":
            try:
                demo_extract_and_translate()
            except Exception as e:
                print(f"❌ 演示失败: {e}")
                
        elif choice == "2":
            try:
                demo_file_analysis()
            except Exception as e:
                print(f"❌ 分析失败: {e}")
                
        elif choice == "3":
            try:
                demo_generate_xml()
            except Exception as e:
                print(f"❌ 生成失败: {e}")
                
        elif choice == "4":
            print("👋 再见!")
            break
            
        else:
            print("❌ 无效选项，请重新选择")
        
        input("\n按回车键继续...")